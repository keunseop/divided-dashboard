from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import List, Sequence
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db import db_session
from core.dart_api import DartApiUnavailable
from core.dps_service import DEFAULT_REPRT_CODE, DpsSeriesItem, PARSER_VERSION, get_dps_series
from core.models import DividendDpsCache, PrefetchJob, PrefetchJobStatus
from core.utils import normalize_ticker


@dataclass
class PrefetchJobView:
    job_id: str
    status: str
    job_name: str | None
    tickers: list[str]
    revalidate_recent_years: int
    start_year: int
    end_year: int
    reprt_code: str
    force_refresh: bool
    cursor_index: int
    cursor_year: int
    processed_count: int
    success_count: int
    skip_count: int
    fail_count: int
    last_error: str | None
    created_at: datetime | None
    updated_at: datetime | None


def create_job(
    tickers: Sequence[str],
    start_year: int,
    end_year: int,
    reprt_code: str = DEFAULT_REPRT_CODE,
    force_refresh: bool = False,
    job_name: str | None = None,
    revalidate_recent_years: int = 0,
) -> str:
    normalized = _normalize_tickers(tickers)
    if not normalized:
        raise ValueError("작업 대상 ticker가 필요합니다.")

    start, end = sorted((int(start_year), int(end_year)))
    reprt = reprt_code or DEFAULT_REPRT_CODE
    recent_years = _normalize_recent_years(revalidate_recent_years)

    job_id = str(uuid4())
    with db_session() as session:
        payload = _encode_job_payload(normalized, recent_years)
        job = PrefetchJob(
            job_id=job_id,
            status=PrefetchJobStatus.PAUSED.value,
            job_name=job_name,
            tickers_json=payload,
            start_year=start,
            end_year=end,
            reprt_code=reprt,
            force_refresh=force_refresh,
            cursor_index=0,
            cursor_year=start,
            processed_count=0,
            success_count=0,
            skip_count=0,
            fail_count=0,
            last_error=None,
        )
        session.add(job)
        session.flush()
    return job_id


def load_job(job_id: str) -> PrefetchJobView | None:
    with db_session() as session:
        job = session.get(PrefetchJob, job_id)
        if not job:
            return None
        return _to_view(job)


def request_cancel(job_id: str) -> PrefetchJobView | None:
    with db_session() as session:
        job = session.get(PrefetchJob, job_id)
        if not job:
            return None
        if job.status not in (
            PrefetchJobStatus.DONE.value,
            PrefetchJobStatus.CANCELLED.value,
        ):
            job.status = PrefetchJobStatus.CANCELLED.value
        session.flush()
        return _to_view(job)


def resume_job(job_id: str) -> PrefetchJobView | None:
    with db_session() as session:
        job = session.get(PrefetchJob, job_id)
        if not job:
            return None
        if job.status in (
            PrefetchJobStatus.DONE.value,
            PrefetchJobStatus.RUNNING.value,
        ):
            return _to_view(job)
        if job.cursor_year < job.start_year or job.cursor_year > job.end_year:
            job.cursor_year = job.start_year
        job.status = PrefetchJobStatus.RUNNING.value
        session.flush()
        return _to_view(job)


def run_job_step(job_id: str, step_limit: int = 1) -> PrefetchJobView | None:
    if step_limit <= 0:
        step_limit = 1

    with db_session() as session:
        job = session.get(PrefetchJob, job_id)
        if not job:
            return None
        tickers, options = _decode_job_payload(job.tickers_json)
        recent_years = _extract_recent_years(options)
        if job.status not in (
            PrefetchJobStatus.RUNNING.value,
            PrefetchJobStatus.CANCELLED_REQUESTED.value,
        ):
            return _to_view_with_payload(job, tickers, recent_years)

        if not tickers:
            job.status = PrefetchJobStatus.DONE.value
            return _to_view_with_payload(job, tickers, recent_years)

        if job.cursor_year < job.start_year or job.cursor_year > job.end_year:
            job.cursor_year = job.start_year

        steps = 0
        while steps < step_limit:
            if job.status == PrefetchJobStatus.CANCELLED_REQUESTED.value:
                job.status = PrefetchJobStatus.CANCELLED.value
                break
            if job.cursor_index >= len(tickers):
                job.status = PrefetchJobStatus.DONE.value
                break

            ticker = tickers[job.cursor_index]
            current_year = job.cursor_year
            continue_run = _process_single_step(
                session,
                job,
                ticker,
                current_year,
                revalidate_recent_years=recent_years,
            )
            job.processed_count += 1
            steps += 1
            if not continue_run:
                break

            job.cursor_year += 1
            if job.cursor_year > job.end_year:
                job.cursor_year = job.start_year
                job.cursor_index += 1
                if job.cursor_index >= len(tickers):
                    job.status = PrefetchJobStatus.DONE.value
                    break

        session.flush()
        return _to_view_with_payload(job, tickers, recent_years)


def pause_job(job_id: str) -> PrefetchJobView | None:
    with db_session() as session:
        job = session.get(PrefetchJob, job_id)
        if not job:
            return None
        if job.status not in (
            PrefetchJobStatus.DONE.value,
            PrefetchJobStatus.CANCELLED.value,
        ):
            job.status = PrefetchJobStatus.PAUSED.value
        session.flush()
        return _to_view(job)


def list_recent_jobs(limit: int = 10) -> List[PrefetchJobView]:
    limited = max(1, limit)
    with db_session() as session:
        rows = (
            session.execute(
                select(PrefetchJob).order_by(PrefetchJob.created_at.desc()).limit(limited)
            )
            .scalars()
            .all()
        )
        views = [_to_view(job) for job in rows]
    return views


def _process_single_step(
    session: Session,
    job: PrefetchJob,
    ticker: str,
    year: int,
    *,
    revalidate_recent_years: int = 0,
) -> bool:
    reprt_code = job.reprt_code or DEFAULT_REPRT_CODE
    if not ticker:
        job.skip_count += 1
        return True

    force_this_step = job.force_refresh or _should_force_refresh(job, year, revalidate_recent_years)

    if not force_this_step and _has_cached_value(session, ticker, year, reprt_code):
        job.skip_count += 1
        return True

    try:
        items = get_dps_series(
            session,
            ticker,
            start_year=year,
            end_year=year,
            reprt_code=reprt_code,
            force_refresh=force_this_step,
        )
    except DartApiUnavailable as exc:
        message = str(exc)
        if _is_missing_corp_code_error(message):
            job.skip_count += 1
            job.last_error = message
            _mark_missing_step(session, ticker, year, reprt_code, message)
            return True
        job.fail_count += 1
        job.last_error = message
        job.status = PrefetchJobStatus.FAILED.value
        return False

    job.last_error = None
    if any(_matches_year(item, year) and item.dps_cash is not None for item in items):
        job.success_count += 1
    else:
        job.skip_count += 1
    return True


def _has_cached_value(session, ticker: str, year: int, reprt_code: str) -> bool:
    stmt = select(DividendDpsCache).where(
        DividendDpsCache.ticker == ticker,
        DividendDpsCache.fiscal_year == year,
        DividendDpsCache.reprt_code == reprt_code,
    )
    row = session.execute(stmt).scalar_one_or_none()
    return row is not None


def _matches_year(item: DpsSeriesItem, year: int) -> bool:
    return item.fiscal_year == year


def _normalize_tickers(values: Sequence[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        ticker = normalize_ticker(value)
        if not ticker or ticker in seen:
            continue
        normalized.append(ticker)
        seen.add(ticker)
    return normalized


def _encode_job_payload(tickers: list[str], recent_years: int) -> str:
    payload = {
        "tickers": tickers,
        "options": {"revalidate_recent_years": _normalize_recent_years(recent_years)},
    }
    return json.dumps(payload, ensure_ascii=False)


def _decode_job_payload(raw_payload: str | None) -> tuple[list[str], dict]:
    if not raw_payload:
        return [], {}
    try:
        data = json.loads(raw_payload)
    except Exception:
        return [], {}
    if isinstance(data, dict):
        tickers = data.get("tickers") or []
        options = data.get("options") or {}
    elif isinstance(data, list):
        tickers = data
        options = {}
    else:
        tickers = []
        options = {}
    cleaned: list[str] = []
    for value in tickers:
        ticker = normalize_ticker(value)
        if ticker:
            cleaned.append(ticker)
    return cleaned, options if isinstance(options, dict) else {}


def _extract_recent_years(options: dict | None) -> int:
    if not options:
        return 0
    return _normalize_recent_years(options.get("revalidate_recent_years", 0))


def _normalize_recent_years(value) -> int:
    try:
        number = int(value)
    except Exception:
        return 0
    return max(0, min(2, number))


def _should_force_refresh(job: PrefetchJob, year: int, revalidate_recent_years: int) -> bool:
    if revalidate_recent_years <= 0:
        return False
    threshold = max(job.start_year, job.end_year - revalidate_recent_years + 1)
    return year >= threshold


def _is_missing_corp_code_error(message: str) -> bool:
    if not message:
        return False
    return "고유번호" in message or "corp_code" in message.lower()


def _mark_missing_step(session: Session, ticker: str, year: int, reprt_code: str, message: str) -> None:
    stmt = select(DividendDpsCache).where(
        DividendDpsCache.ticker == ticker,
        DividendDpsCache.fiscal_year == year,
        DividendDpsCache.reprt_code == reprt_code,
    )
    cached = session.execute(stmt).scalar_one_or_none()
    payload = json.dumps({"status": "ERROR", "message": message}, ensure_ascii=False)
    if cached:
        if cached.dps_cash is not None:
            return
        cached.raw_payload = payload
        cached.parser_version = PARSER_VERSION
        return
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


def _to_view(job: PrefetchJob) -> PrefetchJobView:
    tickers, options = _decode_job_payload(job.tickers_json)
    recent_years = _extract_recent_years(options)
    return _build_view(job, tickers, recent_years)


def _to_view_with_payload(job: PrefetchJob, tickers: list[str], recent_years: int) -> PrefetchJobView:
    return _build_view(job, tickers, recent_years)


def _build_view(job: PrefetchJob, tickers: list[str], recent_years: int) -> PrefetchJobView:
    return PrefetchJobView(
        job_id=job.job_id,
        status=job.status,
        job_name=job.job_name,
        tickers=tickers,
        revalidate_recent_years=recent_years,
        start_year=job.start_year,
        end_year=job.end_year,
        reprt_code=job.reprt_code,
        force_refresh=job.force_refresh,
        cursor_index=job.cursor_index,
        cursor_year=job.cursor_year,
        processed_count=job.processed_count,
        success_count=job.success_count,
        skip_count=job.skip_count,
        fail_count=job.fail_count,
        last_error=job.last_error,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )
