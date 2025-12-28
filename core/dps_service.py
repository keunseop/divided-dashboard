from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import date
from typing import Iterable, List

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from core.dart_api import DartApiUnavailable, DartDividendFetcher
from core.models import DividendDpsCache
from core.utils import normalize_ticker

PARSER_VERSION = "v1"
DEFAULT_REPRT_CODE = "11011"

_fetcher: DartDividendFetcher | None = None


@dataclass
class DpsSeriesItem:
    ticker: str
    fiscal_year: int
    reprt_code: str
    dps_cash: float | None
    currency: str | None


def _get_fetcher() -> DartDividendFetcher:
    global _fetcher
    if _fetcher is None:
        _fetcher = DartDividendFetcher()
    return _fetcher


def _serialize_record(record) -> str:
    payload = asdict(record)
    payload["event_date"] = record.event_date.isoformat() if record.event_date else None
    return json.dumps(payload, ensure_ascii=False)


def _select_cache_stmt(
    ticker: str,
    reprt_code: str,
    *,
    start_year: int | None = None,
    end_year: int | None = None,
) -> Select[tuple[DividendDpsCache]]:
    stmt = select(DividendDpsCache).where(
        DividendDpsCache.ticker == ticker,
        DividendDpsCache.reprt_code == reprt_code,
    )
    if start_year is not None:
        stmt = stmt.where(DividendDpsCache.fiscal_year >= start_year)
    if end_year is not None:
        stmt = stmt.where(DividendDpsCache.fiscal_year <= end_year)
    return stmt.order_by(DividendDpsCache.fiscal_year)


def _ensure_year_range(start_year: int | None, end_year: int | None) -> tuple[int, int]:
    current_year = date.today().year
    start = start_year or (current_year - 10)
    end = end_year or current_year
    if end < start:
        start, end = end, start
    return start, end


def get_dps_series(
    session: Session,
    ticker: str,
    *,
    start_year: int | None = None,
    end_year: int | None = None,
    reprt_code: str = DEFAULT_REPRT_CODE,
    force_refresh: bool = False,
) -> List[DpsSeriesItem]:
    """Return DPS 정보 목록을 반환하고, 누락 연도는 DART에서 조회해 캐시를 upsert한다."""
    normalized = normalize_ticker(ticker)
    if not normalized:
        return []

    reprt = reprt_code or DEFAULT_REPRT_CODE
    start, end = _ensure_year_range(start_year, end_year)

    existing_rows = session.execute(
        _select_cache_stmt(normalized, reprt, start_year=start, end_year=end)
    ).scalars().all()
    existing_years = {row.fiscal_year for row in existing_rows}

    if force_refresh or existing_years != set(range(start, end + 1)):
        missing_years: set[int]
        if force_refresh:
            missing_years = set(range(start, end + 1))
        else:
            missing_years = {year for year in range(start, end + 1) if year not in existing_years}

        if missing_years:
            fetcher = _get_fetcher()
            try:
                records = fetcher.fetch_dividend_records(
                    normalized,
                    start_year=min(missing_years),
                    end_year=max(missing_years),
                )
            except DartApiUnavailable:
                raise
            else:
                fetched_years = _upsert_records(session, normalized, reprt, records)
                _mark_no_data_years(session, normalized, reprt, missing_years - fetched_years)

        if force_refresh:
            existing_rows = session.execute(
                _select_cache_stmt(normalized, reprt, start_year=start, end_year=end)
            ).scalars().all()
        else:
            if missing_years:
                additional_rows = session.execute(
                    _select_cache_stmt(normalized, reprt, start_year=min(missing_years), end_year=max(missing_years))
                ).scalars().all()
                existing_map = {row.fiscal_year: row for row in existing_rows}
                for row in additional_rows:
                    existing_map[row.fiscal_year] = row
                existing_rows = [existing_map[year] for year in sorted(existing_map.keys())]

    return [
        DpsSeriesItem(
            ticker=row.ticker,
            fiscal_year=row.fiscal_year,
            reprt_code=row.reprt_code,
            dps_cash=row.dps_cash,
            currency=row.currency,
        )
        for row in existing_rows
    ]


def _upsert_records(
    session: Session,
    ticker: str,
    reprt_code: str,
    records: Iterable,
) -> set[int]:
    updated_years: set[int] = set()
    for record in records:
        year = getattr(record, "year", None)
        if not year:
            continue
        stmt = select(DividendDpsCache).where(
            DividendDpsCache.ticker == ticker,
            DividendDpsCache.fiscal_year == year,
            DividendDpsCache.reprt_code == reprt_code,
        )
        cached = session.execute(stmt).scalar_one_or_none()

        payload = _serialize_record(record)
        if cached:
            cached.dps_cash = record.amount
            cached.currency = record.currency
            cached.parser_version = PARSER_VERSION
            cached.raw_payload = payload
        else:
            session.add(
                DividendDpsCache(
                    ticker=ticker,
                    fiscal_year=year,
                    reprt_code=reprt_code,
                    currency=record.currency,
                    dps_cash=record.amount,
                    parser_version=PARSER_VERSION,
                    raw_payload=payload,
                )
            )
        updated_years.add(year)
    return updated_years


def _mark_no_data_years(
    session: Session,
    ticker: str,
    reprt_code: str,
    years: Iterable[int],
) -> None:
    for year in years:
        stmt = select(DividendDpsCache).where(
            DividendDpsCache.ticker == ticker,
            DividendDpsCache.fiscal_year == year,
            DividendDpsCache.reprt_code == reprt_code,
        )
        cached = session.execute(stmt).scalar_one_or_none()
        payload = json.dumps({"status": "NO_DATA"}, ensure_ascii=False)
        if cached:
            if cached.dps_cash is not None:
                continue
            cached.parser_version = PARSER_VERSION
            cached.raw_payload = payload
        else:
            session.add(
                DividendDpsCache(
                    ticker=ticker,
                    fiscal_year=year,
                    reprt_code=reprt_code,
                    currency=None,
                    dps_cash=None,
                    parser_version=PARSER_VERSION,
                    raw_payload=payload,
                )
            )
