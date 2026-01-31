# -*- coding: utf-8 -*-
# Streamlit 版：基金历史净值趋势（支持代码检索与5/10/20均线）
import re
import json
import requests
import streamlit as st
from datetime import datetime, timedelta, date
from typing import Dict, List, Tuple, Optional
from streamlit_echarts import st_echarts

st.set_page_config(
    page_title="基金历史净值趋势",
    page_icon="📈",
    layout="wide"
)

# ========== 常量配置 ==========
DEFAULT_FUND_MAP: Dict[str, str] = {
    "011892": "易方达先锋成长混合C",
    "021760": "中欧中证港股通创新药指数C",
    "020398": "中银港股通创新药混合C",
    "012805": "广发恒生科技ETF联接(QDII)C",
    "110022": "易方达消费行业"
}

RANGE_ITEMS = [
    {"key": "1m",  "label": "1月",   "days": 31},
    {"key": "3m",  "label": "3月",   "days": 93},
    {"key": "6m",  "label": "6月",   "days": 186},
    {"key": "1y",  "label": "1年",   "days": 365},
    {"key": "all", "label": "全部",   "days": None},
]

MA_CONFIG = [
    {"key": "ma5",  "label": "MA5",  "win": 5, "color": "#FF7F50"},
    {"key": "ma10", "label": "MA10", "win": 10, "color": "#87CEFA"},
    {"key": "ma20", "label": "MA20", "win": 20, "color": "#DA70D6"},
]

# ========== 工具函数 ==========
def fetch_fund_name(code: str) -> str:
    """尝试获取未在列表中的基金名称"""
    try:
        url = f"https://fundgz.1234567.com.cn/js/{code}.js"
        resp = requests.get(url, timeout=3)
        if resp.status_code == 200:
            match = re.search(r'"name":"(.*?)"', resp.text)
            if match: return match.group(1)
    except: pass
    return "未知基金"

def fetch_pingzhong(code: str):
    url = f"https://fund.eastmoney.com/pingzhongdata/{code}.js"
    resp = requests.get(url, timeout=8)
    resp.raise_for_status()
    net = json.loads(re.search(r"var\s+Data_netWorthTrend\s*=\s*(\[[\s\S]*?\]);", resp.text).group(1))
    acc = json.loads(re.search(r"var\s+Data_ACWorthTrend\s*=\s*(\[[\s\S]*?\]);", resp.text).group(1))
    return net, acc

def moving_average(data: List[float], win: int) -> List[Optional[float]]:
    res = []
    for i in range(len(data)):
        if i < win - 1:
            res.append(None)
        else:
            res.append(round(sum(data[i-win+1:i+1]) / win, 4))
    return res

# ========== 会话状态 ==========
if "fund_map" not in st.session_state:
    st.session_state.fund_map = DEFAULT_FUND_MAP.copy()
if "range_key" not in st.session_state:
    st.session_state.range_key = "6m"

# ========== 侧边栏 ==========
with st.sidebar:
    st.header("⚙️ 配置")
    
    # 基金检索与添加
    search_code = st.text_input("🔍 输入基金代码检索", placeholder="例如: 000001")
    if search_code and len(search_code) == 6:
        if search_code not in st.session_state.fund_map:
            with st.spinner("获取基金信息..."):
                name = fetch_fund_name(search_code)
                st.session_state.fund_map[search_code] = name
    
    # 下拉选择
    fund_options = {f"{k} - {v}": k for k, v in st.session_state.fund_map.items()}
    selected_label = st.selectbox("选择已关注基金", options=list(fund_options.keys()))
    current_code = fund_options[selected_label]

    # 均线开关
    st.subheader("均线设置")
    enabled_ma = []
    for ma in MA_CONFIG:
        if st.checkbox(ma["label"], value=True):
            enabled_ma.append(ma)

    # 区间选择
    range_label = st.radio("时间跨度", [i["label"] for i in RANGE_ITEMS], index=2, horizontal=True)
    current_range = next(i for i in RANGE_ITEMS if i["label"] == range_label)

# ========== 数据处理 ==========
try:
    net_data, acc_data = fetch_pingzhong(current_code)
    
    # 时间过滤
    if current_range["days"]:
        cutoff = datetime.now() - timedelta(days=current_range["days"])
        filtered_net = [d for d in net_data if datetime.fromtimestamp(d['x']/1000) > cutoff]
    else:
        filtered_net = net_data

    dates = [datetime.fromtimestamp(d['x']/1000).strftime('%Y-%m-%d') for d in filtered_net]
    units = [d['y'] for d in filtered_net]
    
    # 提取累计净值
    acc_dict = {d[0]: d[1] for d in acc_data}
    acc_values = [acc_dict.get(d['x'], None) for d in filtered_net]

    # 计算均线
    series_list = [
        {"name": "单位净值", "type": "line", "data": units, "smooth": True, "showSymbol": False},
        {"name": "累计净值", "type": "line", "data": acc_values, "smooth": True, "showSymbol": False, "visible": False}
    ]

    for ma in enabled_ma:
        series_list.append({
            "name": ma["label"],
            "type": "line",
            "data": moving_average(units, ma["win"]),
            "smooth": True,
            "showSymbol": False,
            "lineStyle": {"width": 1, "type": "dashed", "color": ma["color"]}
        })

    # ========== 图表渲染 ==========
    st.title(f"📈 {st.session_state.fund_map[current_code]} ({current_code})")
    
    options = {
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "cross"}},
        "legend": {"data": [s["name"] for s in series_list]},
        "grid": {"left": "3%", "right": "4%", "bottom": "15%", "containLabel": True},
        "xAxis": {"type": "category", "data": dates, "boundaryGap": False},
        "yAxis": {"type": "value", "scale": True},
        "dataZoom": [{"type": "inside"}, {"type": "slider"}],
        "series": series_list
    }
    
    st_echarts(options=options, height="600px")

except Exception as e:
    st.error(f"获取数据失败: {e}")

st.divider()
st.caption(f"当前查询代码: {current_code} | 数据来源: 东方财富")
