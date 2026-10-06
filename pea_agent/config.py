from __future__ import annotations

import json
from pathlib import Path

from pea_agent.models import AnalysisConfig
from pea_agent.portfolio import parse_dca_amounts


def load_config(path: Path) -> AnalysisConfig:
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read JSON config {path}: {error}") from error
    if not isinstance(raw, dict):
        raise ValueError("The JSON config must contain an object.")
    dca_amounts = raw.get("dca_amounts", {})
    if isinstance(dca_amounts, str):
        dca_amounts = parse_dca_amounts(dca_amounts)
    if not isinstance(dca_amounts, dict):
        raise ValueError("'dca_amounts' must be an object mapping tickers to amounts.")
    include_base_dca = raw.get("include_base_dca", True)
    if not isinstance(include_base_dca, bool):
        raise ValueError("'include_base_dca' must be true or false.")
    symbols_to_exit = {}
    for key in ("removed_from_cac40", "fundamental_exit_symbols"):
        values = raw.get(key, [])
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise ValueError(f"'{key}' must be a list of ticker strings.")
        symbols_to_exit[key] = frozenset(values)
    try:
        return AnalysisConfig(
            monthly_budget_cap=float(raw.get("monthly_budget_cap", 500)),
            month_to_date_buys=float(raw.get("month_to_date_buys", 0)),
            cash_available=float(raw.get("cash_available", 0)),
            include_base_dca=include_base_dca,
            dca_amounts={str(symbol): float(amount) for symbol, amount in dca_amounts.items()},
            dip_drawdown_pct=float(raw.get("dip_drawdown_pct", 8)),
            dip_rsi_threshold=float(raw.get("dip_rsi_threshold", 45)),
            dip_additional_multiplier=float(raw.get("dip_additional_multiplier", 0.5)),
            satellite_stop_loss_pct=float(raw.get("satellite_stop_loss_pct", 15)),
            max_satellite_weight_pct=float(raw.get("max_satellite_weight_pct", 15)),
            target_satellite_weight_pct=float(raw.get("target_satellite_weight_pct", 10)),
            take_profit_rsi=float(raw.get("take_profit_rsi", 70)),
            take_profit_ma200_premium_pct=float(raw.get("take_profit_ma200_premium_pct", 20)),
            take_profit_fraction=float(raw.get("take_profit_fraction", 0.25)),
            removed_from_cac40=symbols_to_exit["removed_from_cac40"],
            fundamental_exit_symbols=symbols_to_exit["fundamental_exit_symbols"],
        )
    except (TypeError, ValueError) as error:
        raise ValueError(f"Invalid value in JSON config: {error}") from error
