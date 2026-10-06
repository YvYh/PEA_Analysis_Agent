from __future__ import annotations

from pea_agent.models import AssetKind

CORE_ALIASES = {
    "CW8": ("CW8.PA", "Amundi MSCI World"),
    "CW8.PA": ("CW8.PA", "Amundi MSCI World"),
    "ESE": ("ESE.PA", "Amundi S&P 500"),
    "ESE.PA": ("ESE.PA", "Amundi S&P 500"),
    "WPEA": ("WPEA.PA", "iShares MSCI World Swap PEA"),
    "WPEA.PA": ("WPEA.PA", "iShares MSCI World Swap PEA"),
}

SATELLITE_ALIASES = {
    "MC": ("MC.PA", "LVMH"),
    "MC.PA": ("MC.PA", "LVMH"),
    "TTE": ("TTE.PA", "TotalEnergies"),
    "TTE.PA": ("TTE.PA", "TotalEnergies"),
    "ASML": ("ASML.AS", "ASML"),
    "SAN": ("SAN.PA", "Sanofi"),
    "SAN.PA": ("SAN.PA", "Sanofi"),
    "OR": ("OR.PA", "L'Oréal"),
    "OR.PA": ("OR.PA", "L'Oréal"),
    "AIR": ("AIR.PA", "Airbus"),
    "AIR.PA": ("AIR.PA", "Airbus"),
    "SU": ("SU.PA", "Schneider Electric"),
    "SU.PA": ("SU.PA", "Schneider Electric"),
    "BNP": ("BNP.PA", "BNP Paribas"),
    "BNP.PA": ("BNP.PA", "BNP Paribas"),
    "RMS": ("RMS.PA", "Hermès"),
    "RMS.PA": ("RMS.PA", "Hermès"),
    "AI": ("AI.PA", "Air Liquide"),
    "AI.PA": ("AI.PA", "Air Liquide"),
}

_ALIASES = {**CORE_ALIASES, **SATELLITE_ALIASES}


def normalize_symbol(raw_symbol: str) -> str:
    symbol = raw_symbol.strip().upper()
    return _ALIASES.get(symbol, (symbol, ""))[0]


def infer_kind(symbol: str) -> AssetKind:
    normalized = normalize_symbol(symbol)
    if normalized in {item[0] for item in CORE_ALIASES.values()}:
        return "core"
    return "satellite"


def known_name(symbol: str) -> str:
    return _ALIASES.get(symbol.strip().upper(), ("", ""))[1]

