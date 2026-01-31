# -*- coding: utf-8 -*-
# Streamlit 版：基金历史净值趋势（东方财富 pingzhongdata）
#
# 运行：
#   pip install -r requirements.txt
#   streamlit run app.py
#
import re
import json
import requests
import streamlit as st
from datetime import datetime, timedelta, date
from typing import Dict, List, Tuple, Optional
from streamlit_echarts import st_echarts

st.set_page_config(
    page_title="基金历史净值趋势 · Streamlit",
    page_icon="📈",
    layout="wide"
)

# ========== 默认基金映射 ==========
DEFAULT_FUND_MAP: Dict[str, str] = {
    "011892": "易方达先锋成长混合C",
    "021760": "中欧中证港股通创新药指数C",
    "020398": "中银港股通创新药混合C",
    "012805": "广发恒生科技ETF联接(QDII)C",
    "024420": "华夏创业板新能源ETF发起式联接C",
    "022654": "华安创业板50ETF联接I",
    "110022": "易方达消费行业"
}

RANGE_ITEMS = [
    {"key": "1m",  "label": "1月",   "days": 31},
    {"key": "3m",  "label": "3月",   "days": 93},
    {"key": "6m",  "label": "6月",   "days": 186},
    {"key": "1y",  "label": "1年",   "days": 365},
    {"key": "3y",  "label": "3年",   "days": 365*3},
    {"key": "5y",  "label": "5年",   "days": 365*5},
    {"key": "ytd", "label": "今年",   "days": None},
    {"key": "all", "label": "成立来", "days": None},
]
RANGE_LABELS = {i["key"]: i["label"] for i in RANGE_ITEMS}

# ========== 均线配置：5 / 10 / 20 ==========
MA_ITEMS = [
    {"key": "ma5",  "label": "MA5",  "win": 5},
    {"key": "ma10", "label": "MA10", "win": 10},
    {"key": "ma20", "label": "MA20", "win": 20},
]
MA_META = {i["key"]: i for i in MA_ITEMS}

# ========== 工具函数 ==========
def ytd_start() -> date:
    d = date.today()
    return date(d.year, 1, 1)

def fmt_date(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms/1000).strftime("%Y-%m-%d")

def in_range(d: date, key: str) -> bool:
    if key == "all":
        return True
    if key == "ytd":
        return d >= ytd_start()
    conf = next((x for x in RANGE_ITEMS if x["key"] == key), None)
    if not conf or not conf["days"]:
        return True
    threshold = date.today() - timedelta(days=conf["days"])
    return d >= threshold

def moving_average(series: List[Tuple[int, float]], win: int) -> List[Tuple[int, Optional[float]]]:
    out = []
    q_sum = 0.0
    q: List[float] = []
    for ts, v in series:
        q.append(v)
        q_sum += v
        if len(q) > win:
            q_sum -= q.pop(0)
        out.append((ts, None if len(q) < win else (q_sum / len(q))))
    return out

def calc_extremes(rows: List[Dict]) -> Optional[Dict]:
    n = len(rows)
    if n < 2:
        return None
    min_val = rows[0]["unit"]; min_idx = 0
    max_gain = -1e18; gain_from = 0; gain_to = 0
    for i in range(1, n):
        v = rows[i]["unit"]
        g = v / min_val - 1
        if g > max_gain:
            max_gain = g; gain_from = min_idx; gain_to = i
        if v < min_val:
            min_val = v; min_idx = i
    max_val = rows[0]["unit"]; max_idx = 0
    max_drawdown = 1e18; dd_from = 0; dd_to = 0
    for i in range(1, n):
        v = rows[i]["unit"]
        d = v / max_val - 1
        if d < max_drawdown:
            max_drawdown = d; dd_from = max_idx; dd_to = i
        if v > max_val:
            max_val = v; max_idx = i
    return dict(
        upPct=max_gain*100, upFrom=gain_from, upTo=gain_to,
        downPct=max_drawdown*100, downFrom=dd_from, downTo=dd_to
    )

# ========== 数据抓取与解析 ==========
PINGZHONG_URL = "https://fund.eastmoney.com/pingzhongdata/{code}.js"
PAT_NET = re.compile(r"var\s+Data_netWorthTrend\s*=\s*(\[[\s\S]*?\]);")
PAT_ACC = re.compile(r"var\s+Data_ACWorthTrend\s*=\s*(\[[\s\S]*?\]);")
PAT_NAME = re.compile(r'var\s+fS_name\s*=\s*"([^"]*)"\s*;')

def fetch_pingzhong(code: str) -> Tuple[List[Dict], List[List], Optional[str]]:
    url = PINGZHONG_URL.format(code=code)
    resp = requests.get(url, timeout=8)
    resp.raise_for_status()
    text = resp.text
    m1 = PAT_NET.search(text)
    m2 = PAT_ACC.search(text)
    if not (m1 and m2):
        raise ValueError("未解析到历史净值数据，请检查基金代码")
    net = json.loads(m1.group(1))
    acc = json.loads(m2.group(1))
    mn = PAT_NAME.search(text)
    name = mn.group(1).strip() if mn and mn.group(1) else None
    return net, acc, name

# ========== 会话状态 ==========
if "fund_map" not in st.session_state:
    st.session_state.fund_map = DEFAULT_FUND_MAP.copy()
if "range_key" not in st.session_state:
    st.session_state.range_key = "6m"
if "enabled_mas" not in st.session_state:
    st.session_state.enabled_mas = set()
if "datazoom" not in st.session_state:
    st.session_state.datazoom = {"start": 0, "end": 100}
if "sel_code" not in st.session_state:
    st.session_state.sel_code = "110022" if "110022" in st.session_state.fund_map else next(iter(st.session_state.fund_map.keys()), "")

# ========== 侧栏（控制区）==========
with st.sidebar:
    st.markdown("### 📈 基金历史净值趋势")
    st.caption("数据源：东方财富 pingzhongdata")

    up = st.file_uploader("导入基金配置（JSON）", type=["json"])
    if up is not None:
        try:
            data = json.load(up)
            new_map = {}
            for k, v in (data or {}).items():
                if re.fullmatch(r"\d{6}", str(k)) and isinstance(v, str) and v.strip():
                    new_map[str(k)] = v.strip()
            if not new_map:
                st.error("配置为空或格式不符合要求")
            else:
                st.session_state.fund_map = new_map
                if st.session_state.sel_code not in st.session_state.fund_map:
                    st.session_state.sel_code = next(iter(st.session_state.fund_map.keys()), "")
                st.success(f"已加载 {len(new_map)} 只基金")
        except Exception as e:
            st.error(f"读取失败：{e}")

    # ====== 输入基金代码：直接检索并抓取（不限制在映射表内） ======
    st.markdown("##### 基金代码")
    default_code = st.session_state.sel_code or ("110022" if "110022" in st.session_state.fund_map else next(iter(st.session_state.fund_map.keys()), ""))
    inp_code = st.text_input("输入基金代码（6位）", value=default_code, max_chars=6)
    inp_code = (inp_code or "").strip()
    if re.fullmatch(r"\d{6}", inp_code):
        st.session_state.sel_code = inp_code
    else:
        st.caption("请输入 6 位数字基金代码")

    # ====== 下拉选择（可选） ======
    st.markdown("##### 基金（可选下拉）")
    codes_sorted = sorted(st.session_state.fund_map.keys())
    code_label_map = {c: f"{c} · {st.session_state.fund_map[c]}" for c in codes_sorted}
    options = [code_label_map[c] for c in codes_sorted] if codes_sorted else []
    label_code_map = {v: k for k, v in code_label_map.items()}

    if options:
        cur = st.session_state.sel_code
        default_label = code_label_map.get(cur, options[0])
        idx = options.index(default_label) if default_label in options else 0
        sel_label = st.selectbox("映射表", options=options, index=idx)
        sel_code_dd = label_code_map[sel_label]
        if sel_code_dd != st.session_state.sel_code:
            st.session_state.sel_code = sel_code_dd

    # 区间
    range_key = st.radio(
        "区间",
        options=[i["key"] for i in RANGE_ITEMS],
        format_func=lambda k: RANGE_LABELS[k],
        horizontal=True,
        index=[i["key"] for i in RANGE_ITEMS].index(st.session_state.range_key)
    )
    if range_key != st.session_state.range_key:
        st.session_state.range_key = range_key
        st.session_state.datazoom = {"start": 0, "end": 100}

    # 均线开关（含全选）
    st.markdown("##### 指标")
    all_on = st.checkbox("全选", value=len(st.session_state.enabled_mas) == len(MA_ITEMS))
    cols = st.columns(len(MA_ITEMS))
    picked = set()
    for i, it in enumerate(MA_ITEMS):
        with cols[i]:
            ck = st.checkbox(it["label"], value=(all_on or (it["key"] in st.session_state.enabled_mas)))
            if ck:
                picked.add(it["key"])
    st.session_state.enabled_mas = picked

    # 高亮开关
    st.markdown("##### 高亮区间")
    highlight_up = st.checkbox("高亮最大涨幅", value=True)
    highlight_down = st.checkbox("高亮最大跌幅", value=True)

    st.divider()
    st.caption("小贴士：Streamlit 后端抓取数据，不受浏览器 CORS 限制。")

sel_code = st.session_state.sel_code

# ========== 主体内容 ==========
left, right = st.columns([7, 3], gap="large")

with left:
    col_a, col_b = st.columns([1, 6])
    with col_a:
        if st.button("今年"):
            st.session_state.range_key = "ytd"
            st.session_state.datazoom = {"start": 0, "end": 100}
            st.rerun()

    status = st.empty()
    errbox = st.empty()

    try:
        status.info("加载中…")
        net_raw, acc_raw, fetched_name = fetch_pingzhong(sel_code)
        if fetched_name and (sel_code not in st.session_state.fund_map or not st.session_state.fund_map.get(sel_code)):
            st.session_state.fund_map[sel_code] = fetched_name
        status.success(f"数据就绪（单位净值 {len(net_raw)} 条，累计净值 {len(acc_raw)} 条）")
    except Exception as e:
        status.empty()
        errbox.error(str(e))
        st.stop()

    fund_name = st.session_state.fund_map.get(sel_code, fetched_name or "")
    st.markdown(f"### {sel_code} · {fund_name}")

    acc_map = {int(ts): float(v) for ts, v in acc_raw}
    rows_all = []
    for obj in net_raw:
        ts = int(obj.get("x"))
        d = datetime.fromtimestamp(ts/1000).date()
        if in_range(d, st.session_state.range_key):
            rows_all.append(dict(
                ts=ts,
                date=fmt_date(ts),
                unit=float(obj.get("y")),
                acc=acc_map.get(ts, None)
            ))
    rows_all.sort(key=lambda r: r["ts"])

    if rows_all:
        meta = f"区间：{rows_all[0]['date']} ~ {rows_all[-1]['date']}（{len(rows_all)} 日）"
    else:
        meta = "所选区间暂无数据"
    st.caption(meta)

    net_series = [(r["ts"], r["unit"]) for r in rows_all]
    ma_series_map = {}
    for key in st.session_state.enabled_mas:
        win = MA_META[key]["win"]
        ma_series_map[key] = moving_average(net_series, win)

    x = [r["date"] for r in rows_all]
    y_unit = [r["unit"] for r in rows_all]
    y_acc = [r["acc"] for r in rows_all]

    dz = st.session_state.datazoom or {"start": 0, "end": 100}
    if rows_all:
        n = len(rows_all)
        s_idx = max(0, min(n-1, round(dz["start"]/100 * (n-1))))
        e_idx = max(0, min(n-1, round(dz["end"]/100 * (n-1))))
        if e_idx < s_idx:
            s_idx, e_idx = e_idx, s_idx
        rows_visible = rows_all[s_idx:e_idx+1]
    else:
        rows_visible = []

    ex = calc_extremes(rows_visible) if rows_visible else None

    mark_areas = []
    if rows_visible and ex:
        up_start = rows_visible[ex["upFrom"]]["date"]
        up_end   = rows_visible[ex["upTo"]]["date"]
        dn_start = rows_visible[ex["downFrom"]]["date"]
        dn_end   = rows_visible[ex["downTo"]]["date"]
        if highlight_up:
            mark_areas.append([
                {"itemStyle": {"color": "rgba(244,63,94,0.18)"}, "xAxis": up_start},
                {"xAxis": up_end}
            ])
        if highlight_down:
            mark_areas.append([
                {"itemStyle": {"color": "rgba(16,185,129,0.18)"}, "xAxis": dn_start},
                {"xAxis": dn_end}
            ])

    series = [
        {"name": "单位净值", "type": "line", "smooth": True, "showSymbol": False,
         "data": y_unit, "lineStyle": {"width": 2},
         "markArea": {"silent": True, "data": mark_areas}},
        {"name": "累计净值", "type": "line", "smooth": True, "showSymbol": False,
         "data": y_acc, "lineStyle": {"width": 2}},
    ]
    for key, arr in ma_series_map.items():
        m = {int(ts): v for ts, v in arr}
        y = [(None if m.get(r["ts"]) is None else round(float(m.get(r["ts"])), 6)) for r in rows_all]
        series.append({
            "name": key.upper(),
            "type": "line",
            "smooth": True,
            "showSymbol": False,
            "data": y,
            "lineStyle": {"width": 1.5, "type": "dashed"},
            "emphasis": {"focus": "series"}
        })

    legend_items = ["单位净值", "累计净值"] + [k.upper() for k in st.session_state.enabled_mas]

    option = {
        "backgroundColor": "#ffffff",
        "grid": {"left": 44, "right": 20, "top": 28, "bottom": 48},
        "tooltip": {"trigger": "axis"},
        "legend": {"data": legend_items, "top": 0, "textStyle": {"color": "#374151"},
                   "selected": {"单位净值": True, "累计净值": False}},
        "xAxis": {"type": "category", "data": x, "boundaryGap": False,
                  "axisLabel": {"color": "#6B7280", "hideOverlap": True}},
        "yAxis": {"type": "value", "scale": True,
                  "axisLabel": {"color": "#6B7280"},
                  "splitLine": {"lineStyle": {"color": "#F3F4F6"}}},
        "dataZoom": [
            {"type": "inside", "start": st.session_state.datazoom["start"], "end": st.session_state.datazoom["end"]},
            {"type": "slider", "height": 24, "bottom": 8, "start": st.session_state.datazoom["start"], "end": st.session_state.datazoom["end"]}
        ],
        "series": series,
    }

    events = {
        "datazoom": """
            function(params) {
                var p = params;
                if (Array.isArray(params.batch) && params.batch.length > 0) {
                    p = params.batch[0];
                }
                return {start: p.start, end: p.end};
            }
        """
    }

    event = st_echarts(options=option, height="480px", events=events, key=f"chart-{sel_code}-{st.session_state.range_key}")
    if isinstance(event, dict) and "start" in event and "end" in event:
        st.session_state.datazoom = {"start": float(event["start"]), "end": float(event["end"])}

with right:
    st.markdown("#### 数据看板")
    if rows_visible:
        st.write(f"**起始日期：** {rows_visible[0]['date']}")
        st.write(f"**结束日期：** {rows_visible[-1]['date']}")
    else:
        st.write("**起始日期：** -")
        st.write("**结束日期：** -")

    st.divider()

    if ex and rows_visible:
        up_pct = ("+" if ex["upPct"] >= 0 else "") + f"{ex['upPct']:.2f}%"
        down_pct = f"{ex['downPct']:.2f}%"
        up_from, up_to = rows_visible[ex["upFrom"]]["date"], rows_visible[ex["upTo"]]["date"]
        down_from, down_to = rows_visible[ex["downFrom"]]["date"], rows_visible[ex["downTo"]]["date"]
        up_days = ex["upTo"] - ex["upFrom"] + 1
        down_days = ex["downTo"] - ex["downFrom"] + 1

        st.markdown(f"**最大涨幅：** :green[{up_pct}]")
        st.caption(f"{up_from} → {up_to}（{up_days} 日）")

        st.markdown(f"**最大跌幅：** :red[{down_pct}]")
        st.caption(f"{down_from} → {down_to}（{down_days} 日）")
    else:
        st.write("**最大涨幅：** -")
        st.write("**最大跌幅：** -")

    st.caption("统计基于“单位净值”，与图上缩放窗口保持一致。")
