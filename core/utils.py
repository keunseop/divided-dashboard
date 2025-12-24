from __future__ import annotations

import pandas as pd


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
