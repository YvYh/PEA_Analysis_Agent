from __future__ import annotations

from datetime import datetime

import streamlit as st

from pea_agent.analysis import analyze_portfolio
from pea_agent.market_data import fetch_market_data
from pea_agent.models import AnalysisConfig
from pea_agent.news import analyze_user_text, fetch_user_urls, search_market_news
from pea_agent.portfolio import parse_dca_amounts, parse_positions
from pea_agent.report import render_report

st.set_page_config(page_title="PEA 投资组合与市场分析助手", page_icon="📈", layout="wide")
st.title("📈 PEA 投资组合与市场分析助手")
st.caption("面向 BoursoBank PEA 账户的量化诊断。所有建议仅供参考，请在下单前自行核实。")

with st.sidebar:
    st.header("持仓与风险限制")
    monthly_cap = st.number_input("每月买入预算硬上限 (€)", min_value=0.0, value=500.0, step=50.0)
    month_to_date = st.number_input("本月已买入或已承诺额度 (€)", min_value=0.0, value=0.0, step=25.0)
    cash = st.number_input("可用现金 (€)", min_value=0.0, value=0.0, step=100.0)
    include_dca = st.checkbox("本次分析包含基础定投", value=True)
    stop_loss = st.number_input("卫星仓硬性止损 (%)", min_value=1.0, max_value=50.0, value=15.0, step=1.0)
    max_weight = st.number_input("单只卫星仓最大占比 (%)", min_value=1.0, max_value=100.0, value=15.0, step=1.0)
    target_weight = st.number_input("再平衡目标占比 (%)", min_value=0.0, max_value=100.0, value=10.0, step=1.0)
    take_profit_rsi = st.number_input("止盈 RSI 阈值", min_value=50.0, max_value=100.0, value=70.0, step=1.0)
    take_profit_premium = st.number_input("高于 MA200 的止盈阈值 (%)", min_value=1.0, max_value=100.0, value=20.0, step=1.0)
    take_profit_fraction = st.number_input("阶段止盈卖出比例 (%)", min_value=1.0, max_value=100.0, value=25.0, step=1.0)
    dip_drawdown = st.number_input("抄底触发：距近三个月高点回撤 (%)", min_value=1.0, max_value=50.0, value=8.0, step=1.0)
    dip_rsi = st.number_input("抄底 RSI 上限", min_value=1.0, max_value=100.0, value=45.0, step=1.0)
    dip_multiplier = st.number_input("动态抄底追加定投倍数", min_value=0.0, max_value=5.0, value=0.5, step=0.1)
    removed_symbols_text = st.text_input("已确认剔除 CAC 40 的代码 (逗号分隔)")
    fundamental_exit_text = st.text_input("已确认基本面恶化需清仓的代码 (逗号分隔)")

holdings_text = st.text_area(
    "持仓数据 (CSV/空格分隔文本)",
    value="",
    height=140,
    placeholder="symbol,shares,average_cost,kind\nCW8,10,450,core\nMC,2,700,satellite",
    help="必需列：symbol, shares, average_cost。可选 kind (core/satellite)、name。也可粘贴空格分隔行，例如 CW8 10 450 core。",
)
dca_text = st.text_area(
    "每月基础定投目标 (代码, 欧元金额)",
    value="",
    height=90,
    placeholder="CW8,200\nESE,100",
    help="每行填写一个标的和金额。建议股数向下取整，实际买入额不会超过本月剩余硬上限。",
)
left, right = st.columns(2)
with left:
    user_news_text = st.text_area("粘贴市场新闻或投资资讯", height=140)
with right:
    user_urls = st.text_area("新闻网页链接 (每行一个)", height=140)

search_web = st.checkbox("联网搜索公开市场资讯", value=False)
instant = st.checkbox("生成 24 小时即时诊断", value=False)

if st.button("开始分析", type="primary"):
    try:
        positions = parse_positions(holdings_text)
        if not positions:
            st.error("请先添加至少一项持仓。")
            st.stop()
        dca_amounts = parse_dca_amounts(dca_text)
        config = AnalysisConfig(
            monthly_budget_cap=monthly_cap,
            month_to_date_buys=month_to_date,
            cash_available=cash,
            include_base_dca=include_dca,
            dca_amounts=dca_amounts,
            dip_drawdown_pct=dip_drawdown,
            satellite_stop_loss_pct=stop_loss,
            max_satellite_weight_pct=max_weight,
            target_satellite_weight_pct=target_weight,
            take_profit_rsi=take_profit_rsi,
            take_profit_ma200_premium_pct=take_profit_premium,
            take_profit_fraction=take_profit_fraction / 100,
            dip_rsi_threshold=dip_rsi,
            dip_additional_multiplier=dip_multiplier,
            removed_from_cac40=frozenset(item.strip() for item in removed_symbols_text.split(",") if item.strip()),
            fundamental_exit_symbols=frozenset(item.strip() for item in fundamental_exit_text.split(",") if item.strip()),
        )
        symbols = tuple(dict.fromkeys([position.symbol for position in positions] + list(dca_amounts)))
        news = list(analyze_user_text(user_news_text, symbols))
        urls = tuple(line.strip() for line in user_urls.splitlines() if line.strip())
        if urls:
            news.extend(fetch_user_urls(urls, symbols))
        if search_web:
            news.extend(search_market_news(symbols))
        with st.spinner("正在获取行情并计算持仓指标…"):
            analysis = analyze_portfolio(positions, config, fetch_market_data, news)
        report = render_report(analysis, instant=instant)
        st.markdown(report)
        st.download_button(
            "下载 Markdown 报告",
            data=report,
            file_name=f"pea-report-{datetime.now().strftime('%Y%m%d-%H%M')}.md",
            mime="text/markdown",
        )
        if analysis.warnings:
            st.warning("部分标的无法获取行情，请查看报告中的警告信息。")
    except (ValueError, RuntimeError) as error:
        st.error(str(error))
