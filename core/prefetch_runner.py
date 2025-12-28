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
) -> str:
    normalized = _normalize_tickers(tickers)
    if not normalized:
        raise ValueError("작업 대상 ticker가 필요합니다.")

    start, end = sorted((int(start_year), int(end_year)))
    reprt = reprt_code or DEFAULT_REPRT_CODE

    job_id = str(uuid4())
    with db_session() as session:
        job = PrefetchJob(
            job_id=job_id,
            status=PrefetchJobStatus.PAUSED.value,
            job_name=job_name,
            tickers_json=json.dumps(normalized, ensure_ascii=False),
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
        if job.status not in (
            PrefetchJobStatus.RUNNING.value,
            PrefetchJobStatus.CANCELLED_REQUESTED.value,
        ):
            return _to_view(job)

        tickers = json.loads(job.tickers_json or "[]")
        if not tickers:
            job.status = PrefetchJobStatus.DONE.value
            return _to_view(job)

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
            continue_run = _process_single_step(session, job, ticker, current_year)
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
        return _to_view(job)


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


def _process_single_step(session: Session, job: PrefetchJob, ticker: str, year: int) -> bool:
    reprt_code = job.reprt_code or DEFAULT_REPRT_CODE
    if not ticker:
        job.skip_count += 1
        return True

    if not job.force_refresh and _has_cached_value(session, ticker, year, reprt_code):
        job.skip_count += 1
        return True

    try:
        items = get_dps_series(
            session,
            ticker,
            start_year=year,
            end_year=year,
            reprt_code=reprt_code,
            force_refresh=job.force_refresh,
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
    tickers = json.loads(job.tickers_json or "[]")
    return PrefetchJobView(
        job_id=job.job_id,
        status=job.status,
        job_name=job.job_name,
        tickers=tickers,
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
