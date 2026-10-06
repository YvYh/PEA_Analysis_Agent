from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

AssetKind = Literal["core", "satellite"]
Action = Literal["buy", "hold", "reduce", "liquidate"]
NewsKind = Literal["market_search", "user_url", "user_text"]


@dataclass(frozen=True)
class Position:
    symbol: str
    shares: int
    average_cost: float
    kind: AssetKind
    name: str = ""


@dataclass(frozen=True)
class MarketData:
    symbol: str
    name: str
    price: float
    currency: str
    as_of: date
    ma20: float | None
    ma50: float | None
    ma200: float | None
    rsi: float | None
    drawdown_from_recent_high: float | None
    weekly_closes_below_ma200: int


@dataclass(frozen=True)
class AnalysisConfig:
    monthly_budget_cap: float = 500.0
    month_to_date_buys: float = 0.0
    cash_available: float = 0.0
    include_base_dca: bool = True
    dca_amounts: dict[str, float] = field(default_factory=dict)
    dip_drawdown_pct: float = 8.0
    dip_rsi_threshold: float = 45.0
    dip_additional_multiplier: float = 0.5
    satellite_stop_loss_pct: float = 15.0
    max_satellite_weight_pct: float = 15.0
    target_satellite_weight_pct: float = 10.0
    take_profit_rsi: float = 70.0
    take_profit_ma200_premium_pct: float = 20.0
    take_profit_fraction: float = 0.25
    removed_from_cac40: frozenset[str] = frozenset()
    fundamental_exit_symbols: frozenset[str] = frozenset()


@dataclass(frozen=True)
class NewsItem:
    title: str
    summary: str
    url: str
    source: str
    kind: NewsKind = "market_search"
    published: str = ""
    related_symbols: tuple[str, ...] = ()
    risk_flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class Directive:
    symbol: str
    name: str
    price: float | None
    action: Action
    shares: int
    amount: float
    rationale: str


@dataclass(frozen=True)
class PortfolioAnalysis:
    positions: tuple[Position, ...]
    quotes: dict[str, MarketData]
    directives: tuple[Directive, ...]
    portfolio_value: float
    month_to_date_buys: float
    budget_cap: float
    remaining_budget: float
    cash_available: float
    warnings: tuple[str, ...] = ()
    news: tuple[NewsItem, ...] = ()
