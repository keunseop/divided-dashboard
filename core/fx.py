from __future__ import annotations

from datetime import date

import requests


FX_API_BASE = "https://api.exchangerate.host"


def fetch_fx_rate(base_currency: str, target_currency: str, on_date: date) -> float | None:
    """
    Fetch a historical FX rate using exchangerate.host.

    Returns None when the API does not respond or when the currencies are not supported.
    """
    if base_currency.upper() == target_currency.upper():
        return 1.0

    url = f"{FX_API_BASE}/{on_date.isoformat()}"
    params = {"base": base_currency.upper(), "symbols": target_currency.upper()}

    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return None

    rates = data.get("rates") or {}
    rate = rates.get(target_currency.upper())
    if rate is None:
        return None
    return float(rate)
