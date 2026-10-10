from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import streamlit as st

from pea_agent.analysis import analyze_portfolio
from pea_agent.market_data import fetch_market_data
from pea_agent.models import AnalysisConfig, Position, WatchItem
from pea_agent.news import analyze_user_text, fetch_user_urls, search_market_news
from pea_agent.portfolio import parse_positions
from pea_agent.report import render_report
from pea_agent.storage import (
    load_cash,
    load_positions,
    load_watchlist,
    save_cash,
    save_positions,
    save_watchlist,
)
from pea_agent.universe import infer_kind, known_name, normalize_symbol

DATA_DIR = Path(
    os.environ.get("PEA_AGENT_DATA_DIR", Path(__file__).resolve().parent)
).expanduser().resolve()
HOLDINGS_PATH = DATA_DIR / "holdings.csv"
WATCHLIST_PATH = DATA_DIR / "watchlist.csv"
CASH_PATH = DATA_DIR / "pea-agent-cash.csv"

st.set_page_config(page_title="PEA 投资组合与市场分析助手", page_icon="📈", layout="wide")
st.title("📈 PEA 投资组合与市场分析助手")
st.caption("本地 CSV 持久化持仓与观察名单；分析行情后，买入建议以可用现金为上限。")

try:
    positions = load_positions(HOLDINGS_PATH)
    watchlist = load_watchlist(WATCHLIST_PATH)
    if "cash_available" not in st.session_state:
        st.session_state.cash_available = load_cash(CASH_PATH)
except (OSError, ValueError) as error:
    st.error(f"读取本地数据失败：{error}")
    st.stop()


def persist_cash() -> None:
    try:
        save_cash(CASH_PATH, st.session_state.cash_available)
        st.session_state.last_analysis = None
        st.session_state.last_report = ""
    except (OSError, ValueError) as error:
        st.session_state.cash_save_error = str(error)


with st.sidebar:
    st.header("账户资产与风险设置")
    st.number_input(
        "可用现金 (€)",
        min_value=0.0,
        step=100.0,
        key="cash_available",
        on_change=persist_cash,
        help="手动维护并保存在本地 CSV。买入建议的总金额不会超过该值。",
    )
    if st.session_state.get("cash_save_error"):
        st.error(f"现金数据保存失败：{st.session_state.pop('cash_save_error')}")
    latest_analysis = st.session_state.get("last_analysis")
    st.metric(
        "Evaluation titre / 持仓证券估值",
        f"€{latest_analysis.securities_value:,.2f}" if latest_analysis else "请先运行分析",
    )
    st.metric(
        "Total value actuelle / 当前总资产",
        f"€{latest_analysis.portfolio_value:,.2f}" if latest_analysis else "请先运行分析",
    )
    st.caption("证券估值按最近成功获取的行情计算；现金金额由用户维护。")
    st.divider()
    st.subheader("风险阈值")
    stop_loss = st.number_input("卫星仓硬性止损 (%)", min_value=1.0, max_value=50.0, value=15.0, step=1.0)
    max_weight = st.number_input("单只卫星仓最大占比 (%)", min_value=1.0, max_value=100.0, value=15.0, step=1.0)
    target_weight = st.number_input("再平衡目标占比 (%)", min_value=0.0, max_value=100.0, value=10.0, step=1.0)
    take_profit_rsi = st.number_input("止盈 RSI 阈值", min_value=50.0, max_value=100.0, value=70.0, step=1.0)
    take_profit_premium = st.number_input("高于 MA200 的止盈阈值 (%)", min_value=1.0, max_value=100.0, value=20.0, step=1.0)
    take_profit_fraction = st.number_input("阶段止盈卖出比例 (%)", min_value=1.0, max_value=100.0, value=25.0, step=1.0)
    dip_drawdown = st.number_input("观察名单回撤买入阈值 (%)", min_value=1.0, max_value=50.0, value=8.0, step=1.0)
    dip_rsi = st.number_input("观察名单 RSI 买入上限", min_value=1.0, max_value=100.0, value=45.0, step=1.0)
    removed_symbols_text = st.text_input("已确认剔除 CAC 40 的代码 (逗号分隔)")
    fundamental_exit_text = st.text_input("已确认基本面恶化需清仓的代码 (逗号分隔)")

holdings_tab, watchlist_tab, analysis_tab = st.tabs(["持仓管理", "Watch list 管理", "分析与报告"])

with holdings_tab:
    st.subheader("本地持仓")
    st.caption(f"CSV：{HOLDINGS_PATH}")
    if positions:
        st.dataframe(
            [
                {
                    "代码": item.symbol,
                    "名称": item.name,
                    "持仓股数": item.shares,
                    "持仓均价 (€)": item.average_cost,
                    "类型": item.kind,
                }
                for item in positions
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("当前没有持仓记录。")

    add_col, update_col, delete_col = st.columns(3)
    with add_col:
        st.markdown("#### 新增持仓")
        with st.form("add_holding_form", clear_on_submit=True):
            new_symbol = st.text_input("标的代码")
            new_shares = st.number_input("持仓股数", min_value=1, value=1, step=1)
            new_average_cost = st.number_input("持仓均价 (€)", min_value=0.01, value=100.0, step=1.0)
            new_kind = st.selectbox("类型", ["自动识别", "core", "satellite"])
            new_name = st.text_input("名称 (可选)")
            add_holding = st.form_submit_button("添加并保存")
        if add_holding:
            try:
                symbol = normalize_symbol(new_symbol)
                if not symbol:
                    raise ValueError("请输入标的代码。")
                if any(item.symbol == symbol for item in positions):
                    raise ValueError(f"{symbol} 已在持仓中，请使用“修改持仓”更新股数。")
                kind = infer_kind(symbol) if new_kind == "自动识别" else new_kind
                updated = positions + (
                    Position(symbol, int(new_shares), float(new_average_cost), kind, new_name.strip() or known_name(symbol) or symbol),
                )
                save_positions(HOLDINGS_PATH, updated)
                st.session_state.last_analysis = None
                st.session_state.last_report = ""
                st.success(f"已保存 {symbol}。")
                st.rerun()
            except (OSError, ValueError) as error:
                st.error(f"添加持仓失败：{error}")

    with update_col:
        st.markdown("#### 修改持仓")
        if positions:
            with st.form("update_holding_form"):
                update_symbol = st.selectbox("选择标的", [item.symbol for item in positions])
                selected = next(item for item in positions if item.symbol == update_symbol)
                updated_shares = st.number_input("更新持仓股数", min_value=1, value=selected.shares, step=1)
                updated_average = st.number_input("更新持仓均价 (€)", min_value=0.01, value=float(selected.average_cost), step=1.0)
                updated_kind = st.selectbox("更新类型", ["core", "satellite"], index=0 if selected.kind == "core" else 1)
                updated_name = st.text_input("更新名称", value=selected.name)
                update_holding = st.form_submit_button("保存修改")
            if update_holding:
                try:
                    updated = tuple(
                        Position(item.symbol, int(updated_shares), float(updated_average), updated_kind, updated_name.strip() or item.name)
                        if item.symbol == update_symbol
                        else item
                        for item in positions
                    )
                    save_positions(HOLDINGS_PATH, updated)
                    st.session_state.last_analysis = None
                    st.session_state.last_report = ""
                    st.success(f"已更新 {update_symbol}。")
                    st.rerun()
                except (OSError, ValueError) as error:
                    st.error(f"修改持仓失败：{error}")
        else:
            st.info("暂无可修改的持仓。")

    with delete_col:
        st.markdown("#### 删除持仓")
        if positions:
            with st.form("delete_holding_form"):
                delete_symbol = st.selectbox("选择要删除的标的", [item.symbol for item in positions])
                delete_holding = st.form_submit_button("删除并保存")
            if delete_holding:
                try:
                    save_positions(HOLDINGS_PATH, tuple(item for item in positions if item.symbol != delete_symbol))
                    st.session_state.last_analysis = None
                    st.session_state.last_report = ""
                    st.success(f"已删除 {delete_symbol}。")
                    st.rerun()
                except OSError as error:
                    st.error(f"删除持仓失败：{error}")
        else:
            st.info("暂无可删除的持仓。")

with watchlist_tab:
    st.subheader("本地 Watch list")
    st.caption(f"CSV：{WATCHLIST_PATH}。所有观察名单标的都会获取行情并纳入分析。")
    if watchlist:
        st.dataframe(
            [{"代码": item.symbol, "名称": item.name, "类型": item.kind} for item in watchlist],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Watch list 目前为空。")

    watch_add_col, watch_delete_col = st.columns(2)
    with watch_add_col:
        st.markdown("#### 添加观察标的")
        with st.form("add_watch_item_form", clear_on_submit=True):
            watch_symbol = st.text_input("观察标的代码")
            watch_kind = st.selectbox("观察标的类型", ["自动识别", "core", "satellite"])
            watch_name = st.text_input("观察标的名称 (可选)")
            add_watch_item = st.form_submit_button("添加到 Watch list")
        if add_watch_item:
            try:
                symbol = normalize_symbol(watch_symbol)
                if not symbol:
                    raise ValueError("请输入标的代码。")
                if any(item.symbol == symbol for item in watchlist):
                    raise ValueError(f"{symbol} 已存在于 Watch list。")
                kind = infer_kind(symbol) if watch_kind == "自动识别" else watch_kind
                updated = watchlist + (WatchItem(symbol, kind, watch_name.strip() or known_name(symbol) or symbol),)
                save_watchlist(WATCHLIST_PATH, updated)
                st.session_state.last_analysis = None
                st.session_state.last_report = ""
                st.success(f"已将 {symbol} 加入 Watch list。")
                st.rerun()
            except (OSError, ValueError) as error:
                st.error(f"添加观察标的失败：{error}")

    with watch_delete_col:
        st.markdown("#### 删除观察标的")
        if watchlist:
            with st.form("delete_watch_item_form"):
                remove_symbol = st.selectbox("选择要删除的代码", [item.symbol for item in watchlist])
                delete_watch_item = st.form_submit_button("从 Watch list 删除")
            if delete_watch_item:
                try:
                    save_watchlist(WATCHLIST_PATH, tuple(item for item in watchlist if item.symbol != remove_symbol))
                    st.session_state.last_analysis = None
                    st.session_state.last_report = ""
                    st.success(f"已从 Watch list 删除 {remove_symbol}。")
                    st.rerun()
                except OSError as error:
                    st.error(f"删除观察标的失败：{error}")
        else:
            st.info("Watch list 目前为空。")

with analysis_tab:
    st.subheader("行情、资讯与分析")
    left, right = st.columns(2)
    with left:
        user_news_text = st.text_area("粘贴市场新闻或投资资讯", height=120)
    with right:
        user_urls = st.text_area("新闻网页链接 (每行一个)", height=120)
    search_web = st.checkbox("联网搜索公开市场资讯", value=False)
    instant = st.checkbox("生成 24 小时即时诊断", value=False)

    if st.button("分析持仓与 Watch list", type="primary"):
        if not positions and not watchlist:
            st.error("请先添加持仓或 Watch list 标的。")
        else:
            try:
                config = AnalysisConfig(
                    cash_available=float(st.session_state.cash_available),
                    dip_drawdown_pct=dip_drawdown,
                    dip_rsi_threshold=dip_rsi,
                    satellite_stop_loss_pct=stop_loss,
                    max_satellite_weight_pct=max_weight,
                    target_satellite_weight_pct=target_weight,
                    take_profit_rsi=take_profit_rsi,
                    take_profit_ma200_premium_pct=take_profit_premium,
                    take_profit_fraction=take_profit_fraction / 100,
                    removed_from_cac40=frozenset(item.strip() for item in removed_symbols_text.split(",") if item.strip()),
                    fundamental_exit_symbols=frozenset(item.strip() for item in fundamental_exit_text.split(",") if item.strip()),
                )
                symbols = tuple(dict.fromkeys(
                    [item.symbol for item in positions] + [item.symbol for item in watchlist]
                ))
                news = list(analyze_user_text(user_news_text, symbols))
                urls = tuple(line.strip() for line in user_urls.splitlines() if line.strip())
                if urls:
                    news.extend(fetch_user_urls(urls, symbols))
                if search_web:
                    news.extend(search_market_news(symbols))
                with st.spinner("正在获取持仓及 Watch list 行情并计算指标…"):
                    analysis = analyze_portfolio(
                        positions,
                        config,
                        fetch_market_data,
                        news,
                        watchlist,
                    )
                st.session_state.last_analysis = analysis
                st.session_state.last_report = render_report(analysis, instant=instant)
                st.rerun()
            except (ValueError, RuntimeError, OSError) as error:
                st.error(f"分析失败：{error}")

    if st.session_state.get("last_report"):
        st.markdown(st.session_state.last_report)
        st.download_button(
            "下载 Markdown 报告",
            data=st.session_state.last_report,
            file_name=f"pea-report-{datetime.now().strftime('%Y%m%d-%H%M')}.md",
            mime="text/markdown",
        )
        last_analysis = st.session_state.last_analysis
        if last_analysis.warnings:
            st.warning("部分标的无法获取行情，请查看报告中的警告信息。")
