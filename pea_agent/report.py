from __future__ import annotations

from datetime import datetime

from pea_agent.models import Directive, NewsItem, PortfolioAnalysis


def _euro(value: float) -> str:
    return f"€{value:,.2f}"


def _format_directive(directive: Directive) -> tuple[str, str]:
    if directive.action == "buy":
        instruction = f"买入 {directive.shares} 股 (约 {_euro(directive.amount)})"
    elif directive.action in {"reduce", "liquidate"}:
        instruction = f"卖出全部持仓 (约 {_euro(directive.amount)})" if directive.action == "liquidate" else f"卖出 {directive.shares} 股 (约 {_euro(directive.amount)})"
    else:
        instruction = "不操作"
    labels = {"buy": "买入", "hold": "持有", "reduce": "减仓", "liquidate": "清仓"}
    return labels[directive.action], instruction


def _news_lines(items: tuple[NewsItem, ...], category: str) -> list[str]:
    selected = [
        item
        for item in items
        if (category == "cac" and item.kind == "market_search")
        or (category == "user" and item.kind in {"user_url", "user_text"})
    ]
    if not selected:
        return ["- 暂无可核验的资讯。"]
    lines = []
    for item in selected:
        title = item.title or item.source
        symbols = f" ({', '.join(item.related_symbols)})" if item.related_symbols else ""
        link = f" — [{item.source}]({item.url})" if item.url else ""
        risks = f" **需核实的风险信号:** {', '.join(item.risk_flags)}。" if item.risk_flags else ""
        lines.append(f"- **{title}**{symbols}: {item.summary}{link}{risks}")
    return lines


def render_report(analysis: PortfolioAnalysis, instant: bool = False) -> str:
    title = "# 📈 PEA 24h 即时诊断" if instant else "# 📈 PEA 投资周报"
    recommended_buys = sum(directive.amount for directive in analysis.directives if directive.action == "buy")
    lines = [
        title,
        "",
        f"生成时间: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M %Z')}",
        "",
        "## 1. 持仓概览与资金状态",
        f"- 可用现金 (当前填写值): {_euro(analysis.cash_available)}",
        f"- Evaluation titre / 持仓证券估值: {_euro(analysis.securities_value)}",
        f"- Total value actuelle / 当前总资产: {_euro(analysis.portfolio_value)}",
        f"- 本次建议买入: {_euro(recommended_buys)} (不超过可用现金)",
        "",
        "## 2. 核心量化操作指令",
        "| 标的名称/代码 | 当前价格 | 建议操作 | 建议金额/股数 | 触发逻辑/依据 |",
        "| :--- | ---: | :--- | :--- | :--- |",
    ]
    if analysis.directives:
        for directive in analysis.directives:
            action, instruction = _format_directive(directive)
            quote = analysis.quotes.get(directive.symbol)
            if quote is None:
                price = "不可用"
                technicals = ""
            else:
                price = f"{_euro(quote.price)} ({quote.as_of.isoformat()})"
                values = [
                    f"MA20 {_euro(quote.ma20)}" if quote.ma20 is not None else "MA20 未计算",
                    f"MA50 {_euro(quote.ma50)}" if quote.ma50 is not None else "MA50 未计算",
                    f"MA200 {_euro(quote.ma200)}" if quote.ma200 is not None else "MA200 未计算",
                    f"RSI {quote.rsi:.1f}" if quote.rsi is not None else "RSI 未计算",
                    (
                        f"距近期高点 {quote.drawdown_from_recent_high:+.1f}%"
                        if quote.drawdown_from_recent_high is not None
                        else "近期高点回撤 N/A"
                    ),
                ]
                technicals = " | 指标: " + ", ".join(values)
            lines.append(
                f"| {directive.name} ({directive.symbol}) | {price} | {action} | {instruction} | "
                f"{directive.rationale}{technicals} |"
            )
    else:
        lines.append("| — | — | 持有 | 暂无操作 | 添加持仓或观察名单标的以获取分析。 |")
    lines.extend(
        [
            "",
            "## 3. 市场动态与要闻解析",
            "- **CAC 40 重点资讯：**",
            *_news_lines(analysis.news, "cac"),
            "- **用户自选资讯解析：**",
            *_news_lines(analysis.news, "user"),
            "",
            "## 4. 风险与警示提醒",
        ]
    )
    if analysis.warnings:
        lines.extend(f"- {warning}" for warning in analysis.warnings)
    else:
        lines.append("- 所有分析标的均已获取行情数据；下单前请核实价格和资讯。")
    if any(position.symbol not in analysis.quotes for position in analysis.positions):
        lines.append("- 持仓估值不完整：存在行情缺失的持仓，总资产显示值可能偏低。")
    if recommended_buys > analysis.cash_available:
        lines.append("- 买入建议金额超过可用现金，检查现金分配逻辑后再交易。")
    for item in analysis.news:
        if item.risk_flags:
            lines.append(f"- 请核实资讯风险信号 ({', '.join(item.related_symbols) or item.title}): {', '.join(item.risk_flags)}。")
    lines.extend(
        [
            "",
            "> 本报告仅供分析参考，不构成个性化投资建议或交易指令。交易前请核实 PEA 合规性、价格、流动性、税务影响及自身风险承受能力。",
        ]
    )
    return "\n".join(lines)
