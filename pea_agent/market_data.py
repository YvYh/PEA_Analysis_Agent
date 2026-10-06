from __future__ import annotations

import math
from datetime import date, timedelta

import pandas as pd

from pea_agent.models import MarketData


def calculate_rsi(close: pd.Series, period: int = 14) -> float | None:
    changes = close.astype(float).diff()
    gains = changes.clip(lower=0)
    losses = -changes.clip(upper=0)
    average_gain = gains.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    average_loss = losses.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    if average_gain.empty or pd.isna(average_gain.iloc[-1]) or pd.isna(average_loss.iloc[-1]):
        return None
    if average_loss.iloc[-1] == 0:
        return 100.0 if average_gain.iloc[-1] > 0 else 50.0
    return float(100 - 100 / (1 + average_gain.iloc[-1] / average_loss.iloc[-1]))


def analyze_history(symbol: str, history: pd.DataFrame, name: str = "") -> MarketData:
    if history.empty or "Close" not in history:
        raise ValueError(f"No usable price history returned for {symbol}.")
    close = history["Close"].dropna().astype(float)
    if close.empty:
        raise ValueError(f"No closing prices returned for {symbol}.")
    latest = float(close.iloc[-1])
    if not math.isfinite(latest) or latest <= 0:
        raise ValueError(f"Latest closing price for {symbol} must be a finite positive amount.")
    moving_average = lambda period: float(close.rolling(period).mean().iloc[-1]) if len(close) >= period else None

    weekly_close = close.resample("W-FRI").last().dropna()
    timestamp = close.index[-1]
    observed_date = timestamp.date() if hasattr(timestamp, "date") else date.today()
    if observed_date.weekday() < 4:
        current_week_start = observed_date - timedelta(days=observed_date.weekday())
        weekly_close = weekly_close[weekly_close.index.date < current_week_start]
    weekly_ma200 = weekly_close.rolling(200).mean()
    below_count = 0
    for weekly_price, weekly_average in zip(reversed(weekly_close.tail(2).tolist()), reversed(weekly_ma200.tail(2).tolist())):
        if weekly_average > 0 and weekly_price < weekly_average:
            below_count += 1
        else:
            break

    high_window = close.tail(63)
    recent_high = float(high_window.max())
    as_of = observed_date
    currency = str(history.attrs.get("currency", "EUR"))
    return MarketData(
        symbol=symbol,
        name=name or symbol,
        price=latest,
        currency=currency,
        as_of=as_of,
        ma20=moving_average(20),
        ma50=moving_average(50),
        ma200=moving_average(200),
        rsi=calculate_rsi(close),
        drawdown_from_recent_high=(latest / recent_high - 1) * 100 if recent_high else None,
        weekly_closes_below_ma200=below_count,
    )


def fetch_market_data(symbol: str, name: str = "") -> MarketData:
    try:
        import yfinance as yf
    except ImportError as error:
        raise RuntimeError("yfinance is required to fetch prices; install the project dependencies.") from error

    ticker = yf.Ticker(symbol)
    history = ticker.history(period="5y", interval="1d", auto_adjust=True)
    if history.empty:
        raise ValueError(f"Yahoo Finance returned no price history for {symbol}.")
    try:
        currency = ticker.fast_info.get("currency")
    except (AttributeError, KeyError, TypeError) as error:
        raise RuntimeError(f"Could not determine quote currency for {symbol}: {error}") from error
    if not currency:
        raise RuntimeError(f"Yahoo Finance did not provide a quote currency for {symbol}.")
    if str(currency).upper() != "EUR":
        raise RuntimeError(f"{symbol} is quoted in {currency}, not EUR; EUR conversion is not configured.")
    history.attrs["currency"] = currency
    return analyze_history(symbol, history, name or symbol)
