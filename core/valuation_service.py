from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db import db_session
from core.fx import fetch_fx_rate_frankfurter
from core.holdings_service import get_positions
from core.market_data import PriceQuote
from core.market_service import get_price_quote_for_ticker
from core.models import AccountType, HoldingValuationSnapshot
from core.secrets import get_secret


@dataclass(slots=True)
class PositionValuation:
    ticker: str
    name_ko: str | None
    account_type: AccountType
    quantity: float
    avg_buy_price_krw: float
    total_cost_krw: float
    realized_pnl_krw: float | None
    price: float | None
    price_currency: str | None
    price_as_of: datetime | None
    price_source: str | None
    fx_to_krw: float | None
    price_krw: float | None
    market_value_krw: float | None
    gain_loss_krw: float | None
    gain_loss_pct: float | None


@dataclass(slots=True)
class ValuationSummary:
    account_type: AccountType
    positions_count: int
    total_cost_krw: float
    market_value_krw: float
    gain_loss_krw: float
    gain_loss_pct: float | None


@dataclass(slots=True)
class ValuationHistoryEntry:
    valuation_date: date
    account_type: AccountType
    total_cost_krw: float
    market_value_krw: float
    gain_loss_krw: float
    gain_loss_pct: float | None


@dataclass(slots=True)
class SnapshotSaveResult:
    inserted: int
    updated: int


def calculate_position_valuations(
    session: Session,
    *,
    force_refresh: bool = False,
) -> tuple[list[PositionValuation], list[str]]:
    """Return per-position valuation data and error strings, fetching prices as needed."""

    positions = get_positions(session)
    valuations: list[PositionValuation] = []
    errors: list[str] = []
    price_cache: Dict[str, PriceQuote] = {}
    fx_cache: Dict[str, float] = {}
    today = date.today()
    logger = logging.getLogger(__name__)
    failed_tickers: set[str] = set()

    log_enabled = force_refresh

    def _emit_fetch_log(message: str) -> None:
        logger.info(message)
        if log_enabled:
            print(message, flush=True)

    def _resolve_workers(total: int) -> int:
        raw = get_secret("PRICE_FETCH_WORKERS")
        if raw:
            try:
                value = int(raw)
                return max(1, value)
            except ValueError:
                pass
        return min(8, max(1, total))

    def _fetch_quote_worker(
        ticker: str,
        *,
        force_refresh_worker: bool,
    ) -> tuple[str, PriceQuote | None, Exception | None]:
        start = time.perf_counter()
        try:
            with db_session() as worker_session:
                quote = get_price_quote_for_ticker(
                    worker_session,
                    ticker,
                    force_refresh=force_refresh_worker,
                )
            if log_enabled:
                elapsed = time.perf_counter() - start
                _emit_fetch_log(f"price_fetch ticker={ticker} elapsed={elapsed:.3f}s")
            return ticker, quote, None
        except Exception as exc:
            if log_enabled:
                elapsed = time.perf_counter() - start
                message = f"price_fetch_failed ticker={ticker} elapsed={elapsed:.3f}s error={exc}"
                logger.warning(message)
                print(message, flush=True)
            return ticker, None, exc

    unique_tickers = sorted({pos.ticker.upper() for pos in positions})
    if unique_tickers:
        workers = _resolve_workers(len(unique_tickers))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(
                    _fetch_quote_worker,
                    ticker,
                    force_refresh_worker=force_refresh,
                )
                for ticker in unique_tickers
            ]
            for future in as_completed(futures):
                ticker, quote, exc = future.result()
                if exc:
                    errors.append(f"{ticker}: {exc}")
                    failed_tickers.add(ticker)
                    continue
                if quote is not None:
                    price_cache[ticker] = quote

    for position in positions:
        ticker = position.ticker.upper()
        quote = price_cache.get(ticker)
        if quote is None:
            quote = None

        price_currency = None
        price_as_of = None
        price_source = None
        price_native = None
        fx_rate = None
        price_krw = None
        market_value_krw = None
        gain_loss_krw = None
        gain_loss_pct = None

        if quote:
            price_currency = (getattr(quote, "currency", None) or "KRW").upper()
            price_as_of = getattr(quote, "as_of", None)
            price_source = getattr(quote, "source", None)
            price_native = getattr(quote, "price", None)
            try:
                fx_rate = _get_fx_to_krw(price_currency, fx_cache, today)
                if fx_rate is None:
                    raise ValueError("환율 데이터를 찾을 수 없습니다.")
                if price_native is None:
                    raise ValueError("가격 데이터가 비어 있습니다.")
                price_krw = float(price_native) * fx_rate
                market_value_krw = price_krw * position.quantity
                gain_loss_krw = market_value_krw - position.total_cost_krw
                if position.total_cost_krw:
                    gain_loss_pct = gain_loss_krw / position.total_cost_krw * 100.0
            except Exception as exc:
                errors.append(f"{ticker}: {exc}")

        valuations.append(
            PositionValuation(
                ticker=position.ticker,
                name_ko=position.name_ko,
                account_type=position.account_type,
                quantity=position.quantity,
                avg_buy_price_krw=position.avg_buy_price_krw,
                total_cost_krw=position.total_cost_krw,
                realized_pnl_krw=position.realized_pnl_krw,
                price=price_native,
                price_currency=price_currency,
                price_as_of=price_as_of,
                price_source=price_source,
                fx_to_krw=fx_rate,
                price_krw=price_krw,
                market_value_krw=market_value_krw,
                gain_loss_krw=gain_loss_krw,
                gain_loss_pct=gain_loss_pct,
            )
        )

    valuations.sort(key=lambda v: (v.account_type.value, v.ticker))
    return valuations, errors


def summarize_valuations(
    valuations: Sequence[PositionValuation],
) -> dict[AccountType, ValuationSummary]:
    """Aggregate valuation list into per-account totals plus ALL."""

    summaries: dict[AccountType, ValuationSummary] = {}

    for valuation in valuations:
        if valuation.market_value_krw is None:
            continue
        summary = summaries.get(valuation.account_type)
        if summary is None:
            summary = ValuationSummary(
                account_type=valuation.account_type,
                positions_count=0,
                total_cost_krw=0.0,
                market_value_krw=0.0,
                gain_loss_krw=0.0,
                gain_loss_pct=None,
            )
            summaries[valuation.account_type] = summary
        summary.positions_count += 1
        summary.total_cost_krw += valuation.total_cost_krw
        summary.market_value_krw += valuation.market_value_krw

    for summary in summaries.values():
        summary.gain_loss_krw = summary.market_value_krw - summary.total_cost_krw
        summary.gain_loss_pct = (
            summary.gain_loss_krw / summary.total_cost_krw * 100.0
            if summary.total_cost_krw
            else None
        )

    overall = ValuationSummary(
        account_type=AccountType.ALL,
        positions_count=0,
        total_cost_krw=0.0,
        market_value_krw=0.0,
        gain_loss_krw=0.0,
        gain_loss_pct=None,
    )
    for summary in summaries.values():
        overall.positions_count += summary.positions_count
        overall.total_cost_krw += summary.total_cost_krw
        overall.market_value_krw += summary.market_value_krw
    if overall.positions_count:
        overall.gain_loss_krw = overall.market_value_krw - overall.total_cost_krw
        overall.gain_loss_pct = (
            overall.gain_loss_krw / overall.total_cost_krw * 100.0
            if overall.total_cost_krw
            else None
        )
    summaries[AccountType.ALL] = overall
    return summaries


def upsert_valuation_snapshots(
    session: Session,
    summaries: dict[AccountType, ValuationSummary],
    *,
    valuation_date: date | None = None,
) -> SnapshotSaveResult:
    """Persist aggregated valuation data into holding_valuation_snapshots."""

    as_of_date = valuation_date or date.today()
    inserted = 0
    updated = 0

    for account_type, summary in summaries.items():
        if summary.positions_count == 0:
            continue
        stmt = select(HoldingValuationSnapshot).where(
            HoldingValuationSnapshot.valuation_date == as_of_date,
            HoldingValuationSnapshot.account_type == account_type,
        )
        existing = session.execute(stmt).scalar_one_or_none()
        if existing:
            existing.total_cost_krw = summary.total_cost_krw
            existing.market_value_krw = summary.market_value_krw
            existing.gain_loss_krw = summary.gain_loss_krw
            existing.gain_loss_pct = summary.gain_loss_pct
            updated += 1
        else:
            session.add(
                HoldingValuationSnapshot(
                    valuation_date=as_of_date,
                    account_type=account_type,
                    total_cost_krw=summary.total_cost_krw,
                    market_value_krw=summary.market_value_krw,
                    gain_loss_krw=summary.gain_loss_krw,
                    gain_loss_pct=summary.gain_loss_pct,
                )
            )
            inserted += 1

    return SnapshotSaveResult(inserted=inserted, updated=updated)


def get_valuation_history(
    session: Session,
    account_type: AccountType,
    *,
    limit: int = 180,
) -> list[ValuationHistoryEntry]:
    stmt = (
        select(HoldingValuationSnapshot)
        .where(HoldingValuationSnapshot.account_type == account_type)
        .order_by(HoldingValuationSnapshot.valuation_date.desc())
        .limit(limit)
    )
    rows = list(reversed(session.execute(stmt).scalars().all()))
    return [
        ValuationHistoryEntry(
            valuation_date=row.valuation_date,
            account_type=row.account_type,
            total_cost_krw=row.total_cost_krw,
            market_value_krw=row.market_value_krw,
            gain_loss_krw=row.gain_loss_krw,
            gain_loss_pct=row.gain_loss_pct,
        )
        for row in rows
    ]


def _get_fx_to_krw(currency: str | None, cache: Dict[str, float], on_date: date) -> float | None:
    code = (currency or "KRW").upper()
    if code == "KRW":
        return 1.0
    if code in cache:
        return cache[code]
    rate = fetch_fx_rate_frankfurter(code, "KRW", on_date)
    if rate is not None:
        cache[code] = rate
    return rate
