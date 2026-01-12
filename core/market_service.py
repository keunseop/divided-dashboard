from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import List

from sqlalchemy import Select, desc, select
from sqlalchemy.orm import Session

from core.market_data import (
    DividendPoint,
    MarketDataProvider,
    PriceQuote,
    get_registered_provider,
    is_price_cache_enabled,
)
from core.models import DividendCache, PriceCache
from core.utils import infer_market_from_ticker, normalize_ticker

CACHE_PRICE_MAX_AGE = timedelta(hours=6)


def resolve_provider(market: str | None) -> MarketDataProvider:
    market_code = (market or "US").upper()
    return get_registered_provider(market_code)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _to_naive(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def get_price_quote_for_ticker(
    session: Session,
    ticker: str,
    *,
    market: str | None = None,
    force_refresh: bool = False,
) -> PriceQuote:
    normalized = normalize_ticker(ticker)
    market_code = infer_market_from_ticker(normalized, market)

    if not force_refresh and is_price_cache_enabled():
        cached = session.execute(
            select(PriceCache)
            .where(PriceCache.ticker == normalized)
            .order_by(desc(PriceCache.as_of))
            .limit(1)
        ).scalar_one_or_none()
        if cached:
            age = _now_utc() - _to_naive(cached.as_of)
            if age <= CACHE_PRICE_MAX_AGE:
                return PriceQuote(
                    ticker=cached.ticker,
                    price=cached.price,
                    currency=cached.currency,
                    as_of=_to_naive(cached.as_of),
                    source=cached.source,
                )

    provider = resolve_provider(market_code)
    return provider.get_current_price(session, normalized)


def get_dividend_history_for_ticker(
    session: Session,
    ticker: str,
    *,
    market: str | None = None,
    start_date: date | None = None,
    force_refresh: bool = False,
) -> List[DividendPoint]:
    normalized = normalize_ticker(ticker)
    market_code = infer_market_from_ticker(normalized, market)

    if not force_refresh:
        rows = session.execute(
            select(DividendCache)
            .where(DividendCache.ticker == normalized)
            .order_by(DividendCache.event_date)
        ).scalars().all()
        if rows:
            points: list[DividendPoint] = []
            for row in rows:
                if start_date and row.event_date < start_date:
                    continue
                points.append(
                    DividendPoint(
                        ticker=row.ticker,
                        event_date=row.event_date,
                        amount=row.amount,
                        currency=row.currency,
                        source=row.source,
                    )
                )
            if points:
                return points

    provider = resolve_provider(market_code)
    return provider.get_dividend_history(session, normalized, start_date=start_date)
