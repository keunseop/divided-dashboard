from __future__ import annotations

import pandas as pd

MARKET_ALIASES = {
    "KRX": "KR",
    "KOSPI": "KR",
    "KOSDAQ": "KR",
    "KONEX": "KR",
    "KR": "KR",
    "US": "US",
    "USA": "US",
    "NYSE": "US",
    "NASDAQ": "US",
    "AMEX": "US",
}


def normalize_ticker(value) -> str:
    """Strip whitespace and uppercase ticker strings; return empty string for nullish input."""
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    if pd.isna(value):
        return ""
    s = str(value).strip()
    if s == "":
        return ""
    return s.upper()


def normalize_market_code(value: str | None) -> str | None:
    """Map various market labels (KRX, KOSPI, NASDAQ, etc.) to canonical KR/US codes."""
    if not value:
        return None
    normalized = str(value).strip().upper()
    if not normalized:
        return None
    return MARKET_ALIASES.get(normalized, normalized)


def infer_market_from_ticker(ticker: str, declared: str | None = None) -> str:
    """Infer market code (KR/US) from ticker pattern and optional declared value."""
    normalized_declared = normalize_market_code(declared)
    if normalized_declared:
        return normalized_declared

    if not ticker:
        return "US"

    normalized = normalize_ticker(ticker)
    if normalized.isdigit():
        return "KR"

    # KRX tickers often start with letters followed by digits (e.g., A005930)
    if len(normalized) >= 5 and normalized[0].isalpha() and normalized[1:].isdigit():
        return "KR"

    # KRX identifiers can be 6-char alnum codes starting with digits (e.g., ETF/ETN-like).
    if (
        len(normalized) == 6
        and normalized.isalnum()
        and any(ch.isdigit() for ch in normalized)
        and any(ch.isalpha() for ch in normalized)
        and normalized[0].isdigit()
    ):
        return "KR"

    return "US"
