from __future__ import annotations

import math
from collections.abc import Callable, Iterable

from pea_agent.models import AnalysisConfig, Directive, MarketData, NewsItem, PortfolioAnalysis, Position
from pea_agent.universe import known_name, normalize_symbol

MarketDataProvider = Callable[[str, str], MarketData]


def _validated_config(config: AnalysisConfig) -> None:
    non_negative = {
        "monthly budget cap": config.monthly_budget_cap,
        "month-to-date buys": config.month_to_date_buys,
        "cash available": config.cash_available,
        "drawdown threshold": config.dip_drawdown_pct,
        "additional DCA multiplier": config.dip_additional_multiplier,
        "satellite stop loss": config.satellite_stop_loss_pct,
        "maximum satellite weight": config.max_satellite_weight_pct,
        "target satellite weight": config.target_satellite_weight_pct,
        "take-profit RSI": config.take_profit_rsi,
        "take-profit premium": config.take_profit_ma200_premium_pct,
        "dip RSI threshold": config.dip_rsi_threshold,
        "take-profit fraction": config.take_profit_fraction,
    }
    non_negative.update({f"DCA amount for {symbol}": amount for symbol, amount in config.dca_amounts.items()})
    for label, value in non_negative.items():
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{label} must be a finite non-negative number.")
    if config.target_satellite_weight_pct > config.max_satellite_weight_pct:
        raise ValueError("Target satellite weight must not exceed the maximum satellite weight.")
    if config.take_profit_fraction <= 0 or config.take_profit_fraction > 1:
        raise ValueError("Take-profit fraction must be greater than 0 and at most 1.")
    if config.take_profit_rsi > 100 or config.dip_rsi_threshold > 100:
        raise ValueError("RSI thresholds must not exceed 100.")


def _build_directives(
    positions: tuple[Position, ...],
    quotes: dict[str, MarketData],
    config: AnalysisConfig,
    news: tuple[NewsItem, ...],
) -> tuple[Directive, ...]:
    position_by_symbol = {position.symbol: position for position in positions}
    portfolio_prices_complete = all(position.symbol in quotes for position in positions)
    total_value = config.cash_available + sum(
        position.shares * quotes[position.symbol].price
        for position in positions
        if position.symbol in quotes
    )
    directives: list[Directive] = []

    removed = {normalize_symbol(symbol) for symbol in config.removed_from_cac40}
    fundamental_exits = {normalize_symbol(symbol) for symbol in config.fundamental_exit_symbols}
    user_reported_removals = {
        symbol
        for item in news
        if any("CAC 40 removal" in flag for flag in item.risk_flags)
        for symbol in item.related_symbols
    }

    for position in positions:
        quote = quotes.get(position.symbol)
        if quote is None:
            continue
        name = position.name or quote.name or known_name(position.symbol) or position.symbol
        market_value = position.shares * quote.price
        return_pct = (quote.price / position.average_cost - 1) * 100
        if position.kind == "satellite" and position.symbol in removed | user_reported_removals:
            directives.append(Directive(position.symbol, name, quote.price, "liquidate", position.shares, market_value, "已明确报告该股被剔除 CAC 40；下单前请核实来源。"))
            continue
        if position.kind == "satellite" and position.symbol in fundamental_exits:
            directives.append(
                Directive(
                    position.symbol,
                    name,
                    quote.price,
                    "liquidate",
                    position.shares,
                    market_value,
                    "用户已确认重大基本面恶化；交易前请复核相关依据。",
                )
            )
            continue
        if position.kind == "satellite" and return_pct <= -config.satellite_stop_loss_pct:
            directives.append(
                Directive(
                    position.symbol,
                    name,
                    quote.price,
                    "liquidate",
                    position.shares,
                    market_value,
                    f"触发硬性止损：较持仓均价下跌 {return_pct:.1f}% (阈值 -{config.satellite_stop_loss_pct:.1f}%)。",
                )
            )
            continue
        if position.kind == "satellite" and quote.weekly_closes_below_ma200 >= 2:
            directives.append(
                Directive(
                    position.symbol,
                    name,
                    quote.price,
                    "liquidate",
                    position.shares,
                    market_value,
                    "周线连续两周收于 200 周均线下方，触发防守型清仓条件。",
                )
            )
            continue
        if position.kind == "satellite" and portfolio_prices_complete and total_value > 0:
            weight_pct = market_value / total_value * 100
            if weight_pct > config.max_satellite_weight_pct:
                target_value = total_value * config.target_satellite_weight_pct / 100
                shares_to_sell = min(position.shares, max(1, math.ceil((market_value - target_value) / quote.price)))
                amount = shares_to_sell * quote.price
                directives.append(
                    Directive(
                        position.symbol,
                        name,
                        quote.price,
                        "liquidate" if shares_to_sell == position.shares else "reduce",
                        shares_to_sell,
                        amount,
                        f"个股仓位占比 {weight_pct:.1f}% 超过 {config.max_satellite_weight_pct:.1f}%；"
                        f"建议再平衡至 {config.target_satellite_weight_pct:.1f}%。",
                    )
                )
                continue
        profit_triggers = []
        if quote.rsi is not None and quote.rsi >= config.take_profit_rsi:
            profit_triggers.append(f"RSI {quote.rsi:.1f} 达到/超过 {config.take_profit_rsi:.1f}")
        if quote.ma200 is not None and quote.price >= quote.ma200 * (1 + config.take_profit_ma200_premium_pct / 100):
            premium = (quote.price / quote.ma200 - 1) * 100
            profit_triggers.append(f"价格高于 MA200 {premium:.1f}%")
        if position.kind == "satellite" and profit_triggers and (
            position.shares > 1 or config.take_profit_fraction == 1
        ):
            shares_to_sell = min(position.shares, max(1, math.floor(position.shares * config.take_profit_fraction)))
            directives.append(
                Directive(
                    position.symbol,
                    name,
                    quote.price,
                    "liquidate" if shares_to_sell == position.shares else "reduce",
                    shares_to_sell,
                    shares_to_sell * quote.price,
                    f"阶段性止盈 ({'；'.join(profit_triggers)})；建议卖出约 {config.take_profit_fraction:.0%}。",
                )
            )
            continue
        directives.append(
            Directive(
                position.symbol,
                name,
                quote.price,
                "hold",
                0,
                0.0,
                (
                    f"持仓行情不完整，跳过仓位占比再平衡；当前未实现收益率 {return_pct:+.1f}%。"
                    if position.kind == "satellite" and not portfolio_prices_complete
                    else (
                        f"触发止盈信号 ({'；'.join(profit_triggers)})，但持仓仅 {position.shares} 股，无法执行部分减仓。"
                        if position.kind == "satellite" and profit_triggers
                        else f"未触发设定的卖出条件；当前未实现收益率 {return_pct:+.1f}%。"
                    )
                ),
            )
        )

    requested_buys: list[tuple[str, float, str]] = []
    normalized_dca: dict[str, float] = {}
    for raw_symbol, raw_amount in config.dca_amounts.items():
        symbol = normalize_symbol(raw_symbol)
        if symbol in normalized_dca:
            raise ValueError(f"Duplicate DCA target for {symbol} after ticker normalization.")
        normalized_dca[symbol] = float(raw_amount)
    for symbol, raw_amount in normalized_dca.items():
        amount = raw_amount if config.include_base_dca else 0.0
        triggers: list[str] = []
        quote = quotes.get(symbol)
        if quote is not None:
            drawdown = quote.drawdown_from_recent_high
            drawdown_trigger = drawdown is not None and drawdown <= -config.dip_drawdown_pct
            technical_trigger = (
                quote.ma20 is not None
                and quote.price < quote.ma20
                and quote.rsi is not None
                and quote.rsi < config.dip_rsi_threshold
            )
            if drawdown_trigger:
                triggers.append("较近期高点回撤")
            if technical_trigger:
                triggers.append("价格低于 MA20 且 RSI 低于阈值")
            if triggers:
                amount += raw_amount * config.dip_additional_multiplier
        if amount > 0 and quote is not None:
            requested_buys.append(
                (
                    symbol,
                    amount,
                    (
                        f"{'基础定投 + 动态抄底' if config.include_base_dca else '动态抄底'} ({'；'.join(triggers)})。"
                        if triggers
                        else "基础定投"
                    ),
                )
            )
        elif amount > 0:
            continue

    remaining = max(0.0, config.monthly_budget_cap - config.month_to_date_buys)
    requested_total = sum(amount for _, amount, _ in requested_buys)
    scale = min(1.0, remaining / requested_total) if requested_total else 0.0
    for symbol, requested, rationale in requested_buys:
        quote = quotes[symbol]
        allocated = requested * scale
        shares_to_buy = math.floor((allocated + 1e-9) / quote.price)
        amount = shares_to_buy * quote.price
        position = position_by_symbol.get(symbol)
        name = (position.name if position else "") or quote.name or known_name(symbol) or symbol
        if shares_to_buy:
            directives.append(
                Directive(
                    symbol,
                    name,
                    quote.price,
                    "buy",
                    shares_to_buy,
                    amount,
                    f"{rationale} 本月额度分配：€{amount:.2f} (目标 €{requested:.2f})。",
                )
            )

    for symbol, raw_amount in normalized_dca.items():
        if symbol in quotes and raw_amount > 0 and not any(item.symbol == symbol and item.action == "buy" for item in directives):
            reason = "本月买入额度已用尽，暂停所有买入。" if remaining <= 0 else "剩余额度不足以买入一整股，或已关闭基础定投。"
            position = position_by_symbol.get(symbol)
            quote = quotes[symbol]
            directives.append(
                Directive(
                    symbol,
                    (position.name if position else "") or quote.name or known_name(symbol) or symbol,
                    quote.price,
                    "hold",
                    0,
                    0.0,
                    reason,
                )
            )
    bought_symbols = {directive.symbol for directive in directives if directive.action == "buy"}
    return tuple(
        directive
        for directive in directives
        if directive.action != "hold" or directive.symbol not in bought_symbols
    )


def analyze_portfolio(
    positions: Iterable[Position],
    config: AnalysisConfig,
    market_data_provider: MarketDataProvider,
    news: Iterable[NewsItem] = (),
) -> PortfolioAnalysis:
    _validated_config(config)
    position_tuple = tuple(positions)
    news_tuple = tuple(news)
    symbols = list(dict.fromkeys([position.symbol for position in position_tuple]))
    for symbol in config.dca_amounts:
        normalized = normalize_symbol(symbol)
        if normalized not in symbols:
            symbols.append(normalized)
    quotes: dict[str, MarketData] = {}
    warnings: list[str] = []
    for symbol in symbols:
        position = next((item for item in position_tuple if item.symbol == symbol), None)
        try:
            quotes[symbol] = market_data_provider(symbol, position.name if position else known_name(symbol))
        except Exception as error:
            warnings.append(f"Market data unavailable for {symbol}: {error}")

    directives = _build_directives(position_tuple, quotes, config, news_tuple)
    portfolio_value = sum(position.shares * quotes[position.symbol].price for position in position_tuple if position.symbol in quotes)
    return PortfolioAnalysis(
        positions=position_tuple,
        quotes=quotes,
        directives=directives,
        portfolio_value=portfolio_value + config.cash_available,
        month_to_date_buys=config.month_to_date_buys,
        budget_cap=config.monthly_budget_cap,
        remaining_budget=max(0.0, config.monthly_budget_cap - config.month_to_date_buys),
        cash_available=config.cash_available,
        warnings=tuple(warnings),
        news=news_tuple,
    )
