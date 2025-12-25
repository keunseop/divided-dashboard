from __future__ import annotations
from datetime import date, timedelta
import requests

FRANKFURTER_BASE = "https://api.frankfurter.dev/v1"

def fetch_fx_rate_frankfurter(base_currency: str, target_currency: str, on_date: date, *,
                              max_backtrack_days: int = 7) -> float | None:
    if base_currency.upper() == target_currency.upper():
        return 1.0

    base = base_currency.upper()
    target = target_currency.upper()

    d = on_date
    for _ in range(max_backtrack_days + 1):
        url = f"{FRANKFURTER_BASE}/{d.isoformat()}"
        params = {"base": base, "symbols": target}
        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            rate = (data.get("rates") or {}).get(target)
            if rate is not None:
                return float(rate)
        except Exception:
            pass
        d -= timedelta(days=1)  # 주말/휴일 대비: 하루씩 뒤로
    return None
