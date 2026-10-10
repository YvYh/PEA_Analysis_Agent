from __future__ import annotations

import csv
import math
import os
import tempfile
from pathlib import Path

from pea_agent.models import AssetKind, Position, WatchItem
from pea_agent.portfolio import parse_positions
from pea_agent.universe import infer_kind, known_name, normalize_symbol


def load_positions(path: Path) -> tuple[Position, ...]:
    if not path.exists():
        return ()
    return parse_positions(path.read_text(encoding="utf-8-sig"))


def save_positions(path: Path, positions: tuple[Position, ...]) -> None:
    _save_csv(
        path,
        ("symbol", "shares", "average_cost", "kind", "name"),
        (
            (position.symbol, position.shares, position.average_cost, position.kind, position.name)
            for position in positions
        ),
    )


def parse_watchlist(text: str) -> tuple[WatchItem, ...]:
    source = text.strip()
    if not source:
        return ()
    first_line = source.splitlines()[0]
    delimiter = ";" if first_line.count(";") > first_line.count(",") else ","
    rows = list(csv.reader(source.splitlines(), delimiter=delimiter))
    header = [cell.strip().lower().replace(" ", "_") for cell in rows[0]]
    has_header = any(cell in {"symbol", "ticker", "code"} for cell in header)
    if has_header:
        rows = rows[1:]
        columns = {name: index for index, name in enumerate(header)}
        symbol_index = next(columns[key] for key in ("symbol", "ticker", "code") if key in columns)
        kind_index = next((columns[key] for key in ("kind", "type", "layer") if key in columns), None)
        name_index = columns.get("name")
    else:
        symbol_index, kind_index, name_index = 0, 1, 2

    items: list[WatchItem] = []
    seen: set[str] = set()
    for line_number, row in enumerate(rows, start=2 if has_header else 1):
        if not row or not any(cell.strip() for cell in row):
            continue
        try:
            symbol = normalize_symbol(row[symbol_index])
            raw_kind = row[kind_index].strip().lower() if kind_index is not None and kind_index < len(row) else ""
            if raw_kind not in {"", "core", "satellite"}:
                raise ValueError(f"Kind on line {line_number} must be 'core' or 'satellite'.")
            kind: AssetKind = raw_kind or infer_kind(symbol)
            name = row[name_index].strip() if name_index is not None and name_index < len(row) else ""
        except (IndexError, ValueError) as error:
            raise ValueError(f"Invalid watchlist item on line {line_number}: {error}") from error
        if not symbol:
            raise ValueError(f"Missing ticker on watchlist line {line_number}.")
        if symbol in seen:
            raise ValueError(f"Duplicate watchlist ticker: {symbol}.")
        seen.add(symbol)
        items.append(WatchItem(symbol, kind, name or known_name(symbol) or symbol))
    return tuple(items)


def load_watchlist(path: Path) -> tuple[WatchItem, ...]:
    if not path.exists():
        return ()
    return parse_watchlist(path.read_text(encoding="utf-8-sig"))


def save_watchlist(path: Path, items: tuple[WatchItem, ...]) -> None:
    _save_csv(
        path,
        ("symbol", "kind", "name"),
        ((item.symbol, item.kind, item.name) for item in items),
    )


def load_cash(path: Path) -> float:
    if not path.exists():
        return 0.0
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        if len(rows) != 1 or "cash_available" not in rows[0]:
            raise ValueError("Cash CSV must contain exactly one cash_available value.")
        amount = float(rows[0]["cash_available"])
    except (OSError, TypeError, ValueError, csv.Error) as error:
        raise ValueError(f"Could not read available cash from {path}: {error}") from error
    if not math.isfinite(amount) or amount < 0:
        raise ValueError(f"Available cash in {path} must be finite and non-negative.")
    return amount


def save_cash(path: Path, amount: float) -> None:
    if not math.isfinite(amount) or amount < 0:
        raise ValueError("Available cash must be finite and non-negative.")
    _save_csv(path, ("cash_available",), ((amount,),))


def _save_csv(path: Path, headers: tuple[str, ...], rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8-sig",
            newline="",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            writer = csv.writer(stream)
            writer.writerow(headers)
            writer.writerows(rows)
        os.replace(temporary_path, path)
    except OSError:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise
