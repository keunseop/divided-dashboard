from __future__ import annotations

from datetime import date, datetime
from typing import Sequence

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from core.firestore_reader import is_firestore_enabled, list_dividends
from core.models import AccountType, DividendEvent
from core.utils import normalize_ticker


def _parse_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except Exception:
            return None
    return None


def list_dividend_events(
    session: Session | None,
    *,
    account_type: AccountType | None = None,
    archived: bool | None = False,
    tickers: Sequence[str] | None = None,
    limit: int | None = None,
    order_desc: bool = False,
) -> list[dict]:
    if is_firestore_enabled():
        rows = list_dividends()
        if archived is not None:
            rows = [row for row in rows if bool(row.get("archived")) is bool(archived)]
        if account_type is not None:
            rows = [row for row in rows if row.get("account_type") == account_type.value]
        if tickers:
            normalized = {normalize_ticker(t) for t in tickers if normalize_ticker(t)}
            rows = [row for row in rows if normalize_ticker(str(row.get("ticker", ""))) in normalized]
        if order_desc:
            rows.sort(key=lambda r: _parse_date(r.get("pay_date")) or date.min, reverse=True)
        else:
            rows.sort(key=lambda r: _parse_date(r.get("pay_date")) or date.min)
        if limit:
            rows = rows[:limit]
        return rows

    if session is None:
        raise RuntimeError("SQLAlchemy session is required when Firestore is disabled.")

    stmt = select(DividendEvent)
    if archived is not None:
        stmt = stmt.where(DividendEvent.archived == archived)
    if account_type is not None:
        stmt = stmt.where(DividendEvent.account_type == account_type)
    if tickers:
        normalized = [normalize_ticker(t) for t in tickers if normalize_ticker(t)]
        if normalized:
            stmt = stmt.where(DividendEvent.ticker.in_(normalized))
    if order_desc:
        stmt = stmt.order_by(desc(DividendEvent.pay_date))
    else:
        stmt = stmt.order_by(DividendEvent.pay_date)
    if limit:
        stmt = stmt.limit(limit)

    return [
        {
            "row_id": row.row_id,
            "pay_date": row.pay_date,
            "year": row.year,
            "month": row.month,
            "ticker": row.ticker,
            "currency": row.currency,
            "fx_rate": row.fx_rate,
            "gross_dividend": row.gross_dividend,
            "tax": row.tax,
            "net_dividend": row.net_dividend,
            "krw_gross": row.krw_gross,
            "krw_net": row.krw_net,
            "account_type": row.account_type.value,
            "source": row.source,
            "archived": row.archived,
            "raw_text": row.raw_text,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
        for row in session.execute(stmt).scalars().all()
    ]
