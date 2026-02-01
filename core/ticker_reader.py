from __future__ import annotations

from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.firestore_reader import is_firestore_enabled, list_ticker_master
from core.models import TickerMaster
from core.utils import normalize_ticker


def get_ticker_meta_map(
    session: Session | None,
    tickers: Sequence[str] | None = None,
) -> dict[str, dict]:
    normalized = [normalize_ticker(t) for t in (tickers or []) if normalize_ticker(t)]
    if is_firestore_enabled():
        return list_ticker_master(normalized or None)

    if session is None:
        raise RuntimeError("SQLAlchemy session is required when Firestore is disabled.")

    stmt = select(TickerMaster)
    if normalized:
        stmt = stmt.where(TickerMaster.ticker.in_(normalized))
    rows = session.execute(stmt).scalars().all()
    return {
        row.ticker: {
            "ticker": row.ticker,
            "name_ko": row.name_ko,
            "market": row.market,
            "currency": row.currency,
        }
        for row in rows
    }
