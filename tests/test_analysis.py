from datetime import date

import pandas as pd
import pytest

from pea_agent.analysis import analyze_portfolio
from pea_agent.market_data import analyze_history
from pea_agent.models import AnalysisConfig, MarketData, NewsItem, Position
from pea_agent.news import analyze_user_text
from pea_agent.portfolio import parse_dca_amounts, parse_positions
from pea_agent.report import render_report


def quote(symbol: str, name: str, price: float, **overrides) -> MarketData:
    values = dict(
        symbol=symbol,
        name=name,
        price=price,
        currency="EUR",
        as_of=date(2026, 10, 6),
        ma20=price + 1,
        ma50=price + 2,
        ma200=price - 20,
        rsi=40,
        drawdown_from_recent_high=-10,
        weekly_closes_below_ma200=0,
    )
    values.update(overrides)
    return MarketData(**values)


def provider_factory(quotes):
    def provider(symbol, name):
        return quotes[symbol]
    return provider


def test_parses_holdings_aliases_and_optional_columns():
    positions = parse_positions("ticker,quantity,avg_cost,kind\nCW8,10,450,core\nMC,2,700,satellite")
    assert positions[0].symbol == "CW8.PA"
    assert positions[1].name == "LVMH"
    assert positions[1].shares == 2


@pytest.mark.parametrize("text", [
    "symbol,shares,average_cost\nCW8,0,450",
    "symbol,shares,average_cost\nCW8,1.5,450",
    "symbol,shares,average_cost,kind\nMC,1,20,other",
    "symbol,shares,average_cost\nCW8,1,450\nCW8.PA,2,455",
])
def test_rejects_invalid_holdings(text):
    with pytest.raises(ValueError):
        parse_positions(text)


def test_parses_french_semicolon_csv_and_decimal_comma():
    position = parse_positions("symbol;shares;average_cost;kind\nCW8;2;450,50;core")[0]
    assert position.symbol == "CW8.PA"
    assert position.average_cost == 450.5


def test_dca_respects_monthly_cap_and_whole_share_orders():
    positions = (Position("CW8.PA", 1, 90, "core"),)
    quotes = {"CW8.PA": quote("CW8.PA", "World ETF", 100, drawdown_from_recent_high=0)}
    config = AnalysisConfig(monthly_budget_cap=250, month_to_date_buys=100, dca_amounts={"CW8.PA": 200})
    quotes["CW8.PA"] = quote("CW8.PA", "World ETF", 100, ma20=101, rsi=50, drawdown_from_recent_high=0)
    result = analyze_portfolio(positions, config, provider_factory(quotes))
    buys = [item for item in result.directives if item.action == "buy"]
    assert len(buys) == 1
    assert buys[0].shares == 1
    assert buys[0].amount == 100
    assert sum(item.amount for item in buys) <= result.remaining_budget


def test_hard_stop_loss_takes_precedence_over_other_signals():
    positions = (Position("MC.PA", 10, 100, "satellite", "LVMH"),)
    quotes = {"MC.PA": quote("MC.PA", "LVMH", 80, rsi=90)}
    result = analyze_portfolio(positions, AnalysisConfig(), provider_factory(quotes))
    directive = next(item for item in result.directives if item.symbol == "MC.PA")
    assert directive.action == "liquidate"
    assert directive.shares == 10
    assert "止损" in directive.rationale


def test_concentration_rebalance_reduces_to_target():
    positions = (
        Position("MC.PA", 20, 70, "satellite", "LVMH"),
        Position("CW8.PA", 10, 100, "core", "World"),
    )
    quotes = {
        "MC.PA": quote("MC.PA", "LVMH", 100, rsi=50),
        "CW8.PA": quote("CW8.PA", "World", 100, rsi=50),
    }
    result = analyze_portfolio(
        positions,
        AnalysisConfig(max_satellite_weight_pct=15, target_satellite_weight_pct=10),
        provider_factory(quotes),
    )
    directive = next(item for item in result.directives if item.symbol == "MC.PA")
    assert directive.action == "reduce"
    assert directive.shares == 17


def test_cash_is_included_in_position_weight_calculation():
    positions = (
        Position("MC.PA", 20, 70, "satellite", "LVMH"),
        Position("CW8.PA", 10, 100, "core", "World"),
    )
    quotes = {
        "MC.PA": quote("MC.PA", "LVMH", 100, rsi=50),
        "CW8.PA": quote("CW8.PA", "World", 100, rsi=50),
    }
    result = analyze_portfolio(
        positions,
        AnalysisConfig(cash_available=7000, max_satellite_weight_pct=15, target_satellite_weight_pct=10),
        provider_factory(quotes),
    )
    directive = next(item for item in result.directives if item.symbol == "MC.PA")
    assert directive.action == "reduce"
    assert directive.shares == 10


def test_missing_holding_quote_disables_concentration_sizing():
    positions = (
        Position("MC.PA", 20, 70, "satellite", "LVMH"),
        Position("CW8.PA", 10, 100, "core", "World"),
    )
    result = analyze_portfolio(
        positions,
        AnalysisConfig(max_satellite_weight_pct=100, target_satellite_weight_pct=80),
        provider_factory({"MC.PA": quote("MC.PA", "LVMH", 100, rsi=50, ma200=100)}),
    )
    directive = next(item for item in result.directives if item.symbol == "MC.PA")
    assert directive.action == "hold"
    assert "行情不完整" in directive.rationale
    assert result.warnings


def test_weekly_defensive_exit_precedes_partial_take_profit():
    positions = (Position("MC.PA", 4, 50, "satellite"),)
    result = analyze_portfolio(
        positions,
        AnalysisConfig(),
        provider_factory(
            {
                "MC.PA": quote(
                    "MC.PA",
                    "LVMH",
                    100,
                    rsi=90,
                    weekly_closes_below_ma200=2,
                )
            }
        ),
    )
    assert result.directives[0].action == "liquidate"


def test_one_share_is_not_mislabeled_as_partial_take_profit():
    result = analyze_portfolio(
        (Position("MC.PA", 1, 50, "satellite"),),
        AnalysisConfig(max_satellite_weight_pct=100, target_satellite_weight_pct=80),
        provider_factory({"MC.PA": quote("MC.PA", "LVMH", 100, rsi=90, ma200=100)}),
    )
    assert result.directives[0].action == "hold"
    assert "仅 1 股" in result.directives[0].rationale


def test_configured_full_take_profit_is_reported_as_liquidation():
    result = analyze_portfolio(
        (Position("MC.PA", 1, 50, "satellite"),),
        AnalysisConfig(
            max_satellite_weight_pct=100,
            target_satellite_weight_pct=80,
            take_profit_fraction=1,
        ),
        provider_factory({"MC.PA": quote("MC.PA", "LVMH", 100, rsi=90, ma200=100)}),
    )
    assert result.directives[0].action == "liquidate"
    assert result.directives[0].shares == 1


def test_news_input_matches_whole_ticker_symbols_only():
    items = analyze_user_text("AI is not the focus of this market summary.", ("AI.PA", "MC.PA"))
    assert items[0].related_symbols == ("AI.PA",)


def test_user_supplied_links_and_text_are_reported_separately():
    items = (
        NewsItem("Market result", "Market summary", "https://example.com", "example.com", kind="market_search"),
        NewsItem("Article", "Article text", "https://example.org", "example.org", kind="user_url"),
    )
    from pea_agent.models import PortfolioAnalysis

    analysis = PortfolioAnalysis((), {}, (), 0, 0, 500, 500, 0, news=items)
    report = render_report(analysis)
    market_section = report.split("**CAC 40 重点资讯：**", 1)[1].split("**用户自选资讯解析：**", 1)[0]
    user_section = report.split("**用户自选资讯解析：**", 1)[1].split("## 4.", 1)[0]
    assert "Market result" in market_section
    assert "Article" not in market_section
    assert "Article" in user_section


def test_report_has_required_sections_and_clear_share_counts():
    positions = (Position("CW8.PA", 1, 90, "core"),)
    result = analyze_portfolio(
        positions,
        AnalysisConfig(dca_amounts={"CW8.PA": 100}),
        provider_factory({"CW8.PA": quote("CW8.PA", "World ETF", 100, drawdown_from_recent_high=0)}),
    )
    report = render_report(result)
    assert "## 1. 持仓概览与资金状态" in report
    assert "## 2. 核心量化操作指令" in report
    assert "## 3. 市场动态与要闻解析" in report
    assert "## 4. 风险与警示提醒" in report
    assert "买入 1 股" in report
    assert "执行后剩余硬顶额度: €400.00" in report


def test_calculates_market_metrics_from_price_history():
    index = pd.date_range("2020-01-01", periods=600, freq="B")
    history = pd.DataFrame({"Close": range(100, 700)}, index=index)
    metrics = analyze_history("CW8.PA", history)
    assert metrics.price == 699
    assert metrics.ma20 == pytest.approx(sum(range(680, 700)) / 20)
    assert metrics.ma200 == pytest.approx(sum(range(500, 700)) / 200)
    assert metrics.rsi == 100
    assert metrics.weekly_closes_below_ma200 == 0


def test_unfinished_current_week_is_not_a_weekly_exit_signal():
    index = pd.bdate_range("2020-01-01", periods=1600)
    prices = [100.0] * 1599 + [50.0]
    metrics = analyze_history("MC.PA", pd.DataFrame({"Close": prices}, index=index))
    assert index[-1].weekday() < 4
    assert metrics.weekly_closes_below_ma200 == 0


def test_parses_dca_amounts():
    assert parse_dca_amounts("ticker,amount\nCW8,€200\nESE,75.5") == {"CW8.PA": 200, "ESE.PA": 75.5}


def test_fundamental_exit_overrides_partial_profit_taking():
    positions = (Position("MC.PA", 4, 50, "satellite"),)
    result = analyze_portfolio(
        positions,
        AnalysisConfig(
            fundamental_exit_symbols=frozenset({"MC"}),
        ),
        provider_factory({"MC.PA": quote("MC.PA", "LVMH", 100, rsi=90)}),
    )
    directive = result.directives[0]
    assert directive.action == "liquidate"
    assert directive.shares == 4
