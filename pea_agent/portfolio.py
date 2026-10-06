from __future__ import annotations

import csv
import io
import math

from pea_agent.models import AssetKind, Position
from pea_agent.universe import infer_kind, known_name, normalize_symbol


def parse_positions(text: str) -> tuple[Position, ...]:
    """Parse CSV or one-position-per-line input with an optional header."""
    source = text.strip()
    first_line = source.splitlines()[0] if source else ""
    delimiter = ";" if first_line.count(";") > first_line.count(",") else ","
    if source and delimiter == "," and "," not in source and ";" not in source:
        source = "\n".join(",".join(line.split()) for line in source.splitlines())
    rows = list(csv.reader(io.StringIO(source), delimiter=delimiter))
    if not rows or not any(cell.strip() for row in rows for cell in row):
        return ()

    header = [cell.strip().lower().replace(" ", "_") for cell in rows[0]]
    has_header = any(cell in {"symbol", "ticker", "code"} for cell in header)
    if has_header:
        rows = rows[1:]
        columns = {name: index for index, name in enumerate(header)}
        symbol_index = next((columns[key] for key in ("symbol", "ticker", "code") if key in columns), 0)
        shares_index = next((columns[key] for key in ("shares", "quantity", "qty") if key in columns), 1)
        cost_index = next((columns[key] for key in ("average_cost", "avg_cost", "average_price", "cost") if key in columns), 2)
        kind_index = next((columns[key] for key in ("kind", "type", "layer") if key in columns), None)
        name_index = columns.get("name")
    else:
        symbol_index, shares_index, cost_index, kind_index, name_index = 0, 1, 2, 3, 4

    positions: list[Position] = []
    seen: set[str] = set()
    for line_number, row in enumerate(rows, start=2 if has_header else 1):
        if not row or not any(cell.strip() for cell in row):
            continue
        try:
            raw_symbol = row[symbol_index].strip()
            symbol = normalize_symbol(raw_symbol)
            raw_shares = row[shares_index].strip()
            raw_cost = row[cost_index].strip().replace("€", "").replace(",", ".")
            shares_float = float(raw_shares)
            average_cost = float(raw_cost)
            kind_text = row[kind_index].strip().lower() if kind_index is not None and kind_index < len(row) else ""
            if kind_text == "core":
                kind: AssetKind = "core"
            elif kind_text == "satellite":
                kind = "satellite"
            elif kind_text:
                raise ValueError(f"Kind on line {line_number} must be 'core' or 'satellite'.")
            else:
                kind = infer_kind(symbol)
            name = row[name_index].strip() if name_index is not None and name_index < len(row) else ""
        except (IndexError, ValueError) as error:
            raise ValueError(f"Invalid holding on line {line_number}: {error}") from error

        if not symbol:
            raise ValueError(f"Missing ticker on line {line_number}.")
        if not math.isfinite(shares_float) or shares_float <= 0 or not shares_float.is_integer():
            raise ValueError(f"Share quantity on line {line_number} must be a positive whole number.")
        if not math.isfinite(average_cost) or average_cost <= 0:
            raise ValueError(f"Average cost on line {line_number} must be a positive amount.")
        if symbol in seen:
            raise ValueError(f"Duplicate holding for {symbol}; combine its shares and average cost first.")
        seen.add(symbol)
        positions.append(
            Position(
                symbol=symbol,
                shares=int(shares_float),
                average_cost=average_cost,
                kind=kind,
                name=name or known_name(symbol) or symbol,
            )
        )
    return tuple(positions)


def parse_dca_amounts(text: str) -> dict[str, float]:
    """Parse ticker,monthly-euros rows, one per line."""
    amounts: dict[str, float] = {}
    first_data_row = True
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        delimiter = ";" if ";" in stripped and "," not in stripped else ","
        parts = next(csv.reader([stripped], delimiter=delimiter))
        if first_data_row and parts[0].strip().lower() in {"symbol", "ticker", "code"}:
            first_data_row = False
            continue
        first_data_row = False
        if len(parts) != 2:
            raise ValueError(f"DCA line {line_number} must contain ticker and amount.")
        symbol = normalize_symbol(parts[0])
        try:
            amount = float(parts[1].strip().replace("€", "").replace(",", "."))
        except ValueError as error:
            raise ValueError(f"Invalid DCA amount on line {line_number}.") from error
        if not symbol or not math.isfinite(amount) or amount < 0:
            raise ValueError(f"DCA line {line_number} must have a ticker and a non-negative amount.")
        if symbol in amounts:
            raise ValueError(f"Duplicate DCA target for {symbol}.")
        amounts[symbol] = amount
    return amounts
