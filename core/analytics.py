from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterable

import pandas as pd

from core.market_data import DividendPoint, PriceQuote


@dataclass(slots=True)
class AnnualDividendPoint:
    year: int
    total: float


def compute_annual_dividends(dividends: Iterable[DividendPoint]) -> pd.DataFrame:
    """Aggregate dividend per-share events into annual totals."""
    totals: dict[int, float] = {}
    for point in dividends:
        year = point.event_date.year
        totals[year] = totals.get(year, 0.0) + float(point.amount)

    rows = [
        {"year": year, "annual_dividend": total}
        for year, total in sorted(totals.items())
    ]
    return pd.DataFrame(rows, columns=["year", "annual_dividend"])


def compute_growth_metrics(annual_df: pd.DataFrame) -> dict:
    """Compute YoY, CAGR, and trend classification from an annual dividend series."""
    if annual_df is None or annual_df.empty:
        return {
            "yoy": {},
            "cagr_3y": None,
            "cagr_5y": None,
            "trend": "Unknown",
        }

    df = annual_df.sort_values("year").reset_index(drop=True)
    yoy = {}
    prev_value = None
    for _, row in df.iterrows():
        year = int(row["year"])
        value = float(row["annual_dividend"])
        if prev_value not in (None, 0):
            yoy[year] = (value / prev_value) - 1
        else:
            yoy[year] = None
        prev_value = value

    def _calc_cagr(window: int) -> float | None:
        if len(df) < window:
            return None
        tail = df.tail(window)
        start = float(tail.iloc[0]["annual_dividend"])
        end = float(tail.iloc[-1]["annual_dividend"])
        start_year = int(tail.iloc[0]["year"])
        end_year = int(tail.iloc[-1]["year"])
        years_span = end_year - start_year
        if start <= 0 or end <= 0 or years_span <= 0:
            return None
        return (end / start) ** (1 / years_span) - 1

    cagr_3y = _calc_cagr(3)
    cagr_5y = _calc_cagr(5)

    trend = "Volatile"
    last_three = df["annual_dividend"].tail(3).tolist()
    if len(last_three) >= 3:
        non_decreasing = all(b >= a for a, b in zip(last_three, last_three[1:]))
        positive_cagr = any(v is not None and v > 0 for v in [cagr_3y, cagr_5y])
        if non_decreasing and positive_cagr:
            trend = "Growing"
    last_two = df["annual_dividend"].tail(2).tolist()
    if len(last_two) == 2 and last_two[-1] < last_two[0]:
        trend = "Shrinking"
    elif any(v is not None and v < 0 for v in [cagr_3y, cagr_5y]):
        trend = "Shrinking"

    return {
        "yoy": yoy,
        "cagr_3y": cagr_3y,
        "cagr_5y": cagr_5y,
        "trend": trend,
    }


def compute_trailing_dividend_yield(
    dividends: Iterable[DividendPoint],
    price_quote: PriceQuote,
    *,
    as_of: datetime | None = None,
    window_days: int = 365,
) -> dict:
    """Compute trailing 12-month dividend sum and yield using the given price quote."""
    if price_quote.price <= 0:
        raise ValueError("price_quote.price must be positive")

    as_of_dt = as_of or price_quote.as_of
    if isinstance(as_of_dt, date) and not isinstance(as_of_dt, datetime):
        as_of_dt = datetime.combine(as_of_dt, datetime.min.time())

    window_start = as_of_dt.date() - timedelta(days=window_days)

    total = 0.0
    count = 0
    for point in dividends:
        if point.event_date >= window_start:
            total += float(point.amount)
            count += 1

    trailing_yield = total / price_quote.price if price_quote.price else None

    return {
        "trailing_dividend": total,
        "trailing_yield": trailing_yield,
        "event_count": count,
        "window_days": window_days,
    }
