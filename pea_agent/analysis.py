from __future__ import annotations

import math
from collections.abc import Callable, Iterable

from pea_agent.models import (
    AnalysisConfig,
    Directive,
    MarketData,
    NewsItem,
    PortfolioAnalysis,
    Position,
    WatchItem,
)
from pea_agent.universe import known_name, normalize_symbol

MarketDataProvider = Callable[[str, str], MarketData]


def _validate_config(config: AnalysisConfig) -> None:
    values = {
        "available cash": config.cash_available,
        "watchlist drawdown threshold": config.dip_drawdown_pct,
        "watchlist RSI threshold": config.dip_rsi_threshold,
        "satellite stop loss": config.satellite_stop_loss_pct,
        "maximum satellite weight": config.max_satellite_weight_pct,
        "target satellite weight": config.target_satellite_weight_pct,
        "take-profit RSI": config.take_profit_rsi,
        "take-profit premium": config.take_profit_ma200_premium_pct,
        "take-profit fraction": config.take_profit_fraction,
    }
    for label, value in values.items():
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{label} must be a finite non-negative number.")
    if config.target_satellite_weight_pct > config.max_satellite_weight_pct:
        raise ValueError("Target satellite weight must not exceed the maximum satellite weight.")
    if not 0 < config.take_profit_fraction <= 1:
        raise ValueError("Take-profit fraction must be greater than 0 and at most 1.")
    if config.dip_rsi_threshold > 100 or config.take_profit_rsi > 100:
        raise ValueError("RSI thresholds must not exceed 100.")


def _build_directives(
    positions: tuple[Position, ...],
    watchlist: tuple[WatchItem, ...],
    quotes: dict[str, MarketData],
    config: AnalysisConfig,
    news: tuple[NewsItem, ...],
) -> tuple[Directive, ...]:
    portfolio_prices_complete = all(position.symbol in quotes for position in positions)
    securities_value = sum(
        position.shares * quotes[position.symbol].price
        for position in positions
        if position.symbol in quotes
    )
    total_value = config.cash_available + securities_value
    directives: list[Directive] = []

    removed = {normalize_symbol(symbol) for symbol in config.removed_from_cac40}
    fundamental_exits = {normalize_symbol(symbol) for symbol in config.fundamental_exit_symbols}
    user_reported_removals = {
        symbol
        for item in news
        if any("CAC 40 removal" in flag for flag in item.risk_flags)
        for symbol in item.related_symbols
    }

    position_actions: dict[str, str] = {}
    for position in positions:
        quote = quotes.get(position.symbol)
        if quote is None:
            continue
        name = position.name or quote.name or known_name(position.symbol) or position.symbol
        market_value = position.shares * quote.price
        return_pct = (quote.price / position.average_cost - 1) * 100
        directive: Directive
        if position.kind == "satellite" and position.symbol in removed | user_reported_removals:
            directive = Directive(
                position.symbol, name, quote.price, "liquidate", position.shares, market_value,
                "已明确报告该股被剔除 CAC 40；下单前请核实来源。",
            )
        elif position.kind == "satellite" and position.symbol in fundamental_exits:
            directive = Directive(
                position.symbol, name, quote.price, "liquidate", position.shares, market_value,
                "用户已确认重大基本面恶化；交易前请复核相关依据。",
            )
        elif position.kind == "satellite" and return_pct <= -config.satellite_stop_loss_pct:
            directive = Directive(
                position.symbol, name, quote.price, "liquidate", position.shares, market_value,
                f"触发硬性止损：较持仓均价下跌 {return_pct:.1f}% (阈值 -{config.satellite_stop_loss_pct:.1f}%)。",
            )
        elif position.kind == "satellite" and quote.weekly_closes_below_ma200 >= 2:
            directive = Directive(
                position.symbol, name, quote.price, "liquidate", position.shares, market_value,
                "周线连续两周收于 200 周均线下方，触发防守型清仓条件。",
            )
        elif (
            position.kind == "satellite"
            and portfolio_prices_complete
            and total_value > 0
            and market_value / total_value * 100 > config.max_satellite_weight_pct
        ):
            weight_pct = market_value / total_value * 100
            target_value = total_value * config.target_satellite_weight_pct / 100
            shares_to_sell = min(position.shares, max(1, math.ceil((market_value - target_value) / quote.price)))
            directive = Directive(
                position.symbol,
                name,
                quote.price,
                "liquidate" if shares_to_sell == position.shares else "reduce",
                shares_to_sell,
                shares_to_sell * quote.price,
                f"个股仓位占比 {weight_pct:.1f}% 超过 {config.max_satellite_weight_pct:.1f}%；"
                f"建议再平衡至 {config.target_satellite_weight_pct:.1f}%。",
            )
        else:
            profit_triggers = []
            if quote.rsi is not None and quote.rsi >= config.take_profit_rsi:
                profit_triggers.append(f"RSI {quote.rsi:.1f} 达到/超过 {config.take_profit_rsi:.1f}")
            if quote.ma200 is not None and quote.price >= quote.ma200 * (
                1 + config.take_profit_ma200_premium_pct / 100
            ):
                premium = (quote.price / quote.ma200 - 1) * 100
                profit_triggers.append(f"价格高于 MA200 {premium:.1f}%")
            if position.kind == "satellite" and profit_triggers and (
                position.shares > 1 or config.take_profit_fraction == 1
            ):
                shares_to_sell = min(
                    position.shares,
                    max(1, math.floor(position.shares * config.take_profit_fraction)),
                )
                directive = Directive(
                    position.symbol,
                    name,
                    quote.price,
                    "liquidate" if shares_to_sell == position.shares else "reduce",
                    shares_to_sell,
                    shares_to_sell * quote.price,
                    f"阶段性止盈 ({'；'.join(profit_triggers)})；建议卖出约 {config.take_profit_fraction:.0%}。",
                )
            else:
                rationale = f"未触发设定的卖出条件；当前未实现收益率 {return_pct:+.1f}%。"
                if position.kind == "satellite" and not portfolio_prices_complete:
                    rationale = f"持仓行情不完整，跳过仓位占比再平衡；当前未实现收益率 {return_pct:+.1f}%。"
                elif position.kind == "satellite" and profit_triggers:
                    rationale = f"触发止盈信号 ({'；'.join(profit_triggers)})，但持仓仅 {position.shares} 股，无法执行部分减仓。"
                directive = Directive(position.symbol, name, quote.price, "hold", 0, 0.0, rationale)
        directives.append(directive)
        position_actions[position.symbol] = directive.action

    candidates: list[tuple[WatchItem, float, tuple[str, ...]]] = []
    watchlist_symbols: set[str] = set()
    for item in watchlist:
        symbol = normalize_symbol(item.symbol)
        if symbol in watchlist_symbols:
            raise ValueError(f"Duplicate watchlist ticker after normalization: {symbol}.")
        watchlist_symbols.add(symbol)
        quote = quotes.get(symbol)
        if quote is None:
            if symbol not in position_actions:
                directives.append(
                    Directive(
                        symbol,
                        item.name or known_name(symbol) or symbol,
                        None,
                        "hold",
                        0,
                        0.0,
                        "行情获取失败，无法判断买入条件；请稍后重试。",
                    )
                )
            continue
        drawdown_signal = (
            quote.drawdown_from_recent_high is not None
            and quote.drawdown_from_recent_high <= -config.dip_drawdown_pct
        )
        technical_signal = (
            quote.ma20 is not None
            and quote.price < quote.ma20
            and quote.rsi is not None
            and quote.rsi < config.dip_rsi_threshold
        )
        signals = []
        if drawdown_signal:
            signals.append(
                f"距近 63 个交易日高点回撤 {abs(quote.drawdown_from_recent_high):.1f}%"
            )
        if technical_signal:
            signals.append(f"价格低于 MA20 且 RSI {quote.rsi:.1f} 低于 {config.dip_rsi_threshold:.1f}")

        position_action = position_actions.get(symbol)
        has_risk_news = any(
            item.related_symbols
            and symbol in item.related_symbols
            and item.risk_flags
            for item in news
        )
        if signals and not has_risk_news and position_action in {None, "hold"}:
            candidates.append((item, float(len(signals)), tuple(signals)))
        else:
            if has_risk_news:
                rationale = "相关资讯包含风险关键词，先核实新闻，不建议新增仓位。"
            elif position_action in {"reduce", "liquidate"}:
                rationale = f"已有持仓触发{position_action}风险指令，暂不建议买入。"
            elif signals:
                rationale = "；".join(signals)
            else:
                rationale = "当前未满足观察名单的买入信号。"
            if symbol in position_actions:
                existing = next(
                    (entry for entry in directives if entry.symbol == symbol),
                    None,
                )
                if existing is not None:
                    directives[directives.index(existing)] = Directive(
                        existing.symbol,
                        existing.name,
                        existing.price,
                        existing.action,
                        existing.shares,
                        existing.amount,
                        f"{existing.rationale} 观察名单分析：{rationale}",
                    )
            else:
                directives.append(
                    Directive(
                        symbol,
                        item.name or quote.name or known_name(symbol) or symbol,
                        quote.price,
                        "hold",
                        0,
                        0.0,
                        rationale,
                    )
                )

    available_cash = config.cash_available
    candidate_weight = sum(score for _, score, _ in candidates)
    allocations = {
        normalize_symbol(item.symbol): available_cash * score / candidate_weight
        for item, score, _ in candidates
    } if candidate_weight > 0 else {}
    shares_to_buy = {
        normalize_symbol(item.symbol): math.floor(
            allocations[normalize_symbol(item.symbol)]
            / quotes[normalize_symbol(item.symbol)].price
        )
        for item, _, _ in candidates
    }
    spent = sum(
        shares * quotes[symbol].price
        for symbol, shares in shares_to_buy.items()
    )
    remaining_cash = max(0.0, available_cash - spent)
    candidate_by_symbol = {normalize_symbol(item.symbol): (item, score, signals) for item, score, signals in candidates}
    priority = sorted(candidate_by_symbol, key=lambda symbol: (-candidate_by_symbol[symbol][1], symbol))
    for symbol in priority:
        additional_shares = math.floor(remaining_cash / quotes[symbol].price)
        shares_to_buy[symbol] += additional_shares
        remaining_cash -= additional_shares * quotes[symbol].price

    candidate_directives: dict[str, Directive] = {}
    for symbol, (item, score, signals) in candidate_by_symbol.items():
        quote = quotes[symbol]
        shares = shares_to_buy[symbol]
        if shares:
            candidate_directives[symbol] = Directive(
                symbol,
                item.name or quote.name or known_name(symbol) or symbol,
                quote.price,
                "buy",
                shares,
                shares * quote.price,
                f"观察名单买入信号 ({'；'.join(signals)})；按信号强度 {score:.0f} 分配可用现金，未超过预算。",
            )
        else:
            directive = next(
                (entry for entry in directives if entry.symbol == symbol and entry.action == "hold"),
                None,
            )
            if directive:
                directives[directives.index(directive)] = Directive(
                    directive.symbol,
                    directive.name,
                    directive.price,
                    "hold",
                    0,
                    0.0,
                    f"满足买入信号 ({'；'.join(signals)})，但可用现金不足以买入一整股。",
                )
            else:
                candidate_directives[symbol] = Directive(
                    symbol,
                    item.name or quote.name or known_name(symbol) or symbol,
                    quote.price,
                    "hold",
                    0,
                    0.0,
                    f"满足买入信号 ({'；'.join(signals)})，但可用现金不足以买入一整股。",
                )

    for symbol, directive in candidate_directives.items():
        existing = next((entry for entry in directives if entry.symbol == symbol), None)
        if existing:
            directives[directives.index(existing)] = directive
        else:
            directives.append(directive)
    return tuple(directives)


def analyze_portfolio(
    positions: Iterable[Position],
    config: AnalysisConfig,
    market_data_provider: MarketDataProvider,
    news: Iterable[NewsItem] = (),
    watchlist: Iterable[WatchItem] = (),
) -> PortfolioAnalysis:
    _validate_config(config)
    position_tuple = tuple(positions)
    watchlist_tuple = tuple(watchlist)
    news_tuple = tuple(news)
    symbols = list(dict.fromkeys(position.symbol for position in position_tuple))
    for item in watchlist_tuple:
        symbol = normalize_symbol(item.symbol)
        if symbol not in symbols:
            symbols.append(symbol)
    quotes: dict[str, MarketData] = {}
    warnings: list[str] = []
    for symbol in symbols:
        position = next((entry for entry in position_tuple if entry.symbol == symbol), None)
        watch_item = next((entry for entry in watchlist_tuple if normalize_symbol(entry.symbol) == symbol), None)
        name = (
            (position.name if position else "")
            or (watch_item.name if watch_item else "")
            or known_name(symbol)
        )
        try:
            quote = market_data_provider(symbol, name)
            if not math.isfinite(quote.price) or quote.price <= 0:
                raise ValueError("行情价格必须是有限正数。")
            quotes[symbol] = quote
        except Exception as error:
            warnings.append(f"行情数据不可用 ({symbol}): {error}")

    directives = _build_directives(position_tuple, watchlist_tuple, quotes, config, news_tuple)
    securities_value = sum(
        position.shares * quotes[position.symbol].price
        for position in position_tuple
        if position.symbol in quotes
    )
    return PortfolioAnalysis(
        positions=position_tuple,
        watchlist=watchlist_tuple,
        quotes=quotes,
        directives=directives,
        securities_value=securities_value,
        portfolio_value=securities_value + config.cash_available,
        cash_available=config.cash_available,
        warnings=tuple(warnings),
        news=news_tuple,
    )
