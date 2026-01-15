from __future__ import annotations

import re
from datetime import datetime

import streamlit as st
from sqlalchemy import select

from core.admin_gate import require_admin
from core.db import db_session
from core.models import DividendEvent, PrefetchJobStatus, TickerMaster
from core.prefetch_runner import (
    create_job,
    list_recent_jobs,
    load_job,
    pause_job,
    request_cancel,
    resume_job,
    run_job_step,
)
from core.utils import normalize_ticker

ACTIVE_JOB_KEY = "prefetch_active_job_id"
RUN_MODE_KEY = "prefetch_run_mode"
STEP_LIMIT_KEY = "prefetch_step_limit"
STEP_SLIDER_KEY = "prefetch_step_slider"

require_admin()

st.title("관리자: DART 배당 미리채우기")
st.caption("여러 종목/연도 범위를 한 번에 Prefetch하여 DPS 캐시를 미리 채우고 관리합니다.")


def _trigger_rerun():
    rerun_fn = getattr(st, "rerun", None) or getattr(st, "experimental_rerun", None)
    if rerun_fn:
        rerun_fn()


def _parse_ticker_blob(blob: str) -> list[str]:
    if not blob:
        return []
    tokens = re.split(r"[,\s]+", blob.strip())
    results: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        ticker = normalize_ticker(token)
        if not ticker or ticker in seen:
            continue
        results.append(ticker)
        seen.add(ticker)
    return results


@st.cache_data(ttl=300)
def _load_ticker_master_options() -> dict[str, str]:
    with db_session() as session:
        rows = (
            session.execute(
                select(TickerMaster.ticker, TickerMaster.name_ko).order_by(TickerMaster.name_ko)
            )
            .all()
        )
    return {ticker: f"{ticker} — {name or ''}".strip(" —") for ticker, name in rows}


@st.cache_data(ttl=300)
def _load_dividend_event_tickers() -> list[str]:
    with db_session() as session:
        rows = session.execute(select(DividendEvent.ticker).distinct().order_by(DividendEvent.ticker)).scalars().all()
    return rows


def _get_active_job():
    job_id = st.session_state.get(ACTIVE_JOB_KEY)
    if not job_id:
        return None
    job = load_job(job_id)
    if job is None:
        st.session_state.pop(ACTIVE_JOB_KEY, None)
    return job


if RUN_MODE_KEY not in st.session_state:
    st.session_state[RUN_MODE_KEY] = False
if STEP_LIMIT_KEY not in st.session_state:
    st.session_state[STEP_LIMIT_KEY] = 10
if STEP_SLIDER_KEY not in st.session_state:
    st.session_state[STEP_SLIDER_KEY] = st.session_state[STEP_LIMIT_KEY]

active_job = _get_active_job()
run_mode = st.session_state.get(RUN_MODE_KEY, False)

if active_job and run_mode:
    if active_job.status in (
        PrefetchJobStatus.RUNNING.value,
        PrefetchJobStatus.CANCELLED_REQUESTED.value,
    ):
        step_limit = st.session_state.get(STEP_LIMIT_KEY, 10)
        run_job_step(active_job.job_id, step_limit=step_limit)
        _trigger_rerun()
    else:
        st.session_state[RUN_MODE_KEY] = False
        active_job = _get_active_job()


st.subheader("최근 Prefetch 작업")
recent_jobs = list_recent_jobs(limit=10)
if not recent_jobs:
    st.info("저장된 Prefetch 작업이 없습니다. 아래에서 첫 작업을 생성해 주세요.")
else:
    for job in recent_jobs:
        total_steps = len(job.tickers) * max(1, job.end_year - job.start_year + 1)
        progress = job.processed_count / total_steps if total_steps else 0.0
        cols = st.columns([4, 2, 2, 2, 1])
        job_label = job.job_name or job.job_id
        created_at: datetime | None = job.created_at
        created_display = created_at.strftime("%Y-%m-%d %H:%M") if created_at else "-"
        with cols[0]:
            st.write(f"**{job_label}**")
            st.caption(f"{job.status} · {created_display}")
        with cols[1]:
            st.write(f"{job.start_year}~{job.end_year}")
            revalidate_hint = (
                f"최근 {job.revalidate_recent_years}년 재검증" if job.revalidate_recent_years else "캐시 우선"
            )
            st.caption(f"{len(job.tickers)} tickers · {revalidate_hint}")
        with cols[2]:
            st.progress(progress, text=f"{progress*100:,.0f}% 완료")
        with cols[3]:
            st.caption(
                f"성공 {job.success_count} · 스킵 {job.skip_count} · 실패 {job.fail_count}"
            )
        with cols[4]:
            btn_label = "재개" if job.status != PrefetchJobStatus.RUNNING.value else "보기"
            if st.button(btn_label, key=f"resume_recent_{job.job_id}"):
                st.session_state[ACTIVE_JOB_KEY] = job.job_id
                st.session_state[RUN_MODE_KEY] = False
                _trigger_rerun()

st.divider()

st.subheader("새 Prefetch 작업 생성")
master_options = _load_ticker_master_options()
dividend_tickers = _load_dividend_event_tickers()

with st.form("prefetch_job_form"):
    manual_blob = st.text_area(
        "직접 입력 (개행·콤마·공백으로 구분)",
        height=120,
        placeholder="AAPL, MSFT\n005930\n삼성전자 등",
    )
    col_master, col_events = st.columns(2)
    master_selection = col_master.multiselect(
        "Ticker Master에서 선택",
        options=list(master_options.keys()),
        format_func=lambda ticker: master_options.get(ticker, ticker),
    )
    event_selection = col_events.multiselect(
        "dividend_events 등장 티커",
        options=dividend_tickers,
    )
    col_year_a, col_year_b = st.columns(2)
    start_year = col_year_a.number_input("시작 연도", min_value=2000, max_value=2100, value=datetime.today().year - 5)
    end_year = col_year_b.number_input("종료 연도", min_value=2000, max_value=2100, value=datetime.today().year)
    reprt_code = col_year_a.text_input("DART reprt_code", value="11011")
    force_refresh = col_year_b.checkbox("Force Refresh", value=False, help="이미 캐시된 연도라도 다시 조회합니다.")
    revalidate_recent = st.slider(
        "최근 연도 재검증",
        min_value=0,
        max_value=2,
        value=0,
        help="0이면 캐시 우선, 1~2로 설정하면 Force Refresh 없이도 해당 구간을 항상 재조회합니다.",
    )
    job_name = st.text_input("작업 이름 (선택)", placeholder="예: KR 대형주 2015-2024")
    submit = st.form_submit_button("작업 생성", use_container_width=True)

    if submit:
        manual_tickers = _parse_ticker_blob(manual_blob)
        combined: list[str] = []
        seen: set[str] = set()
        for source in (manual_tickers, master_selection, event_selection):
            for ticker in source:
                normalized = normalize_ticker(ticker)
                if not normalized or normalized in seen:
                    continue
                combined.append(normalized)
                seen.add(normalized)
        if not combined:
            st.warning("최소 1개 이상의 티커를 입력하거나 선택해 주세요.")
        else:
            clean_name = job_name.strip() if job_name and job_name.strip() else None
            try:
                job_id = create_job(
                    combined,
                    int(start_year),
                    int(end_year),
                    reprt_code=reprt_code or "11011",
                    force_refresh=force_refresh,
                    job_name=clean_name,
                    revalidate_recent_years=revalidate_recent,
                )
            except Exception as exc:
                st.error(f"작업 생성에 실패했습니다: {exc}")
            else:
                st.success(f"작업이 생성되었습니다. Job ID: {job_id}")
                st.session_state[ACTIVE_JOB_KEY] = job_id
                st.session_state[RUN_MODE_KEY] = False

st.divider()

st.subheader("진행 중 작업")
active_job = _get_active_job()
if not active_job:
    st.info("현재 활성화된 작업이 없습니다. 상단의 최근 목록에서 선택하거나 새 작업을 생성해 주세요.")
else:
    total_steps = len(active_job.tickers) * max(1, active_job.end_year - active_job.start_year + 1)
    progress = active_job.processed_count / total_steps if total_steps else 0.0
    st.progress(progress, text=f"{progress*100:,.0f}% 진행")

    st.write(f"상태: **{active_job.status}** · Job ID: `{active_job.job_id}`")
    policy_text = (
        f"최근 {active_job.revalidate_recent_years}년 재검증" if active_job.revalidate_recent_years else "캐시 우선"
    )
    st.caption(
        f"기간 {active_job.start_year}~{active_job.end_year} · 대상 티커 {len(active_job.tickers)}개 · Force Refresh: {active_job.force_refresh} · {policy_text}"
    )

    current_ticker = (
        active_job.tickers[active_job.cursor_index]
        if 0 <= active_job.cursor_index < len(active_job.tickers)
        else "-"
    )
    st.write(f"현재 처리 대상: `{current_ticker}` / 연도 {active_job.cursor_year}")

    metric_cols = st.columns(4)
    metric_cols[0].metric("처리됨", f"{active_job.processed_count:,}", help="총 처리된 step 수")
    metric_cols[1].metric("성공", f"{active_job.success_count:,}")
    metric_cols[2].metric("스킵", f"{active_job.skip_count:,}")
    metric_cols[3].metric("실패", f"{active_job.fail_count:,}")

    step_value = st.slider(
        "한 번에 처리할 Step 수",
        min_value=1,
        max_value=50,
        value=st.session_state[STEP_SLIDER_KEY],
        key=STEP_SLIDER_KEY,
        help="자동 실행 중 한 번의 rerun에서 처리할 (ticker,year) step 수",
    )
    st.session_state[STEP_LIMIT_KEY] = step_value

    if active_job.last_error:
        st.error(f"최근 오류: {active_job.last_error}")

    action_cols = st.columns(4)
    continue_disabled = active_job.status in (
            PrefetchJobStatus.DONE.value,
            PrefetchJobStatus.CANCELLED.value,
            PrefetchJobStatus.FAILED.value,
        )
    if action_cols[0].button("계속 실행 ▶", disabled=continue_disabled):
        resumed = resume_job(active_job.job_id)
        if resumed:
            st.session_state[ACTIVE_JOB_KEY] = resumed.job_id
            st.session_state[RUN_MODE_KEY] = True
            _trigger_rerun()

    pause_disabled = active_job.status != PrefetchJobStatus.RUNNING.value
    if action_cols[1].button("일시 중지 ⏸", disabled=pause_disabled):
        paused = pause_job(active_job.job_id)
        if paused:
            st.session_state[ACTIVE_JOB_KEY] = paused.job_id
            st.session_state[RUN_MODE_KEY] = False
            _trigger_rerun()

    cancel_disabled = active_job.status in (
        PrefetchJobStatus.CANCELLED.value,
        PrefetchJobStatus.DONE.value,
    )
    if action_cols[2].button("취소 ⛔", disabled=cancel_disabled):
        cancelled = request_cancel(active_job.job_id)
        if cancelled:
            st.session_state[ACTIVE_JOB_KEY] = cancelled.job_id
            st.session_state[RUN_MODE_KEY] = False
            _trigger_rerun()

    if action_cols[3].button("작업 초기화 🔄"):
        st.session_state[RUN_MODE_KEY] = False
        st.session_state.pop(ACTIVE_JOB_KEY, None)
        _trigger_rerun()
