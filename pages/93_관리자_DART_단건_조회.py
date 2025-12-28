from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from sqlalchemy import select

from core.admin_gate import require_admin
from core.dart_api import DartApiUnavailable, DartDividendFetcher
from core.db import db_session
from core.models import DividendCache
from core.ui_autocomplete import render_ticker_autocomplete
fetcher = DartDividendFetcher()
CACHE_KEY = "dart_single_cache"
STATE_KEY = "dart_single_state"


def _cache_bucket() -> dict:
    return st.session_state.setdefault(CACHE_KEY, {})


def _get_cached_records(cache_key: str):
    return _cache_bucket().get(cache_key)


def _set_cached_records(cache_key: str, records):
    _cache_bucket()[cache_key] = records
require_admin()

st.title("관리자: DART 단건 조회")
st.caption("보유 종목을 한 건씩 조회하여 최근 배당 공시를 확인하고 수동으로 저장합니다.")
history_years = st.slider(
    "조회 연도 범위 (최근 N년)",
    min_value=1,
    max_value=15,
    value=5,
    help="최근 N년 동안의 공시만 조회합니다.",
)
force_refresh = st.checkbox("강제 재조회", value=False, help="이미 조회했던 종목이라도 DART API를 다시 호출합니다.")

selected_candidate = render_ticker_autocomplete(
    label="자동완성 (국내 종목)",
    key="dart_single_autocomplete",
    help_text="국내 종목명을 입력하고 목록에서 선택해 주세요.",
    limit=25,
    show_input=True,
)

state = st.session_state.setdefault(STATE_KEY, {})
existing_result = state.get("result")

selected_ticker = selected_candidate.ticker if selected_candidate else None
input_snapshot = {
    "selected_ticker": selected_ticker,
    "history_years": history_years,
}

fetch_clicked = st.button("조회", use_container_width=True)

result = existing_result
if fetch_clicked:
    if not selected_candidate:
        st.warning("자동완성에서 종목을 선택해 주세요.")
        st.stop()
    target_ticker = selected_candidate.ticker
    target_name = selected_candidate.name_ko

    current_year = date.today().year
    start_year = max(current_year - history_years + 1, 2000)
    cache_key = f"{target_ticker}|{start_year}|{current_year}"
    from_cache = False
    records = None

    if not force_refresh:
        cached = _get_cached_records(cache_key)
        if cached:
            records = cached
            from_cache = True

    if records is None:
        try:
            records = fetcher.fetch_dividend_records(
                target_ticker,
                start_year=start_year,
                end_year=current_year,
            )
            _set_cached_records(cache_key, records)
        except DartApiUnavailable as exc:
            st.error(f"DART 조회에 실패했습니다: {exc}")
            st.stop()
        except Exception as exc:
            st.error(f"예상치 못한 오류가 발생했습니다: {exc}")
            st.stop()

    if not records:
        st.warning("조회된 배당 공시가 없습니다.")
        st.stop()

    result = {
        "target_ticker": target_ticker,
        "target_name": target_name,
        "start_year": start_year,
        "current_year": current_year,
        "records": records,
        "from_cache": from_cache,
        "input_snapshot": input_snapshot,
    }
    state["result"] = result

if not result:
    st.info("자동완성에서 종목을 선택한 뒤 '조회' 버튼을 눌러 주세요.")
    st.stop()

previous_snapshot = result.get("input_snapshot")
if previous_snapshot and previous_snapshot != input_snapshot:
    st.warning("입력값이 변경되었습니다. '조회' 버튼을 눌러 결과를 갱신해 주세요.")

target_ticker = result["target_ticker"]
target_name = result["target_name"]
start_year = result["start_year"]
current_year = result["current_year"]
records = result["records"]
from_cache = result["from_cache"]

st.info(f"{target_name} ({target_ticker}) - {start_year}년 이후 공시를 조회합니다.")

if from_cache:
    st.success("저장된 최근 결과를 불러왔습니다. 강제 재조회를 체크하면 새로 조회합니다.")

records_df = pd.DataFrame(
    [
        {
            "year": record.year,
            "event_date": record.event_date,
            "amount": record.amount,
            "currency": record.currency,
            "cash_yield_pct": record.cash_yield_pct,
            "payout_ratio_pct": record.payout_ratio_pct,
            "frequency_hint": record.frequency_hint,
        }
        for record in sorted(records, key=lambda r: r.event_date, reverse=True)
    ]
)

st.subheader("조회 결과")
latest = records_df.iloc[0]
col_a, col_b, col_c = st.columns(3)
col_a.metric("연간 주당 배당금", f"{latest['amount']:,.0f} KRW")
col_b.metric(
    "현금배당수익률",
    f"{latest['cash_yield_pct']:.2f}%" if pd.notna(latest["cash_yield_pct"]) else "N/A",
)
payout_display = (
    f"{latest['payout_ratio_pct']:.2f}%"
    if pd.notna(latest["payout_ratio_pct"])
    else "N/A"
)
col_c.metric(
    "현금배당성향",
    payout_display,
    help="연결 기준 순이익 대비 현금배당 비율입니다.",
)

if isinstance(latest.get("frequency_hint"), str):
    st.info(f"배당 주기 추정: {latest['frequency_hint']}")

display_df = records_df.copy()
display_df["annual_dividend"] = display_df["amount"].map(lambda v: f"{v:,.0f} KRW")
display_df["cash_yield_pct"] = display_df["cash_yield_pct"].map(
    lambda v: f"{v:.2f}%" if pd.notna(v) else "-"
)
display_df["payout_ratio_pct"] = display_df["payout_ratio_pct"].map(
    lambda v: f"{v:.2f}%" if pd.notna(v) else "-"
)
display_df = display_df.rename(
    columns={
        "year": "연도",
        "event_date": "기준일",
        "annual_dividend": "연간 주당 배당금",
        "cash_yield_pct": "현금배당수익률",
        "payout_ratio_pct": "현금배당성향",
        "frequency_hint": "배당 주기",
    }
)
st.dataframe(
    display_df[
        [
            "연도",
            "기준일",
            "연간 주당 배당금",
            "현금배당수익률",
            "현금배당성향",
            "배당 주기",
        ]
    ],
    hide_index=True,
    use_container_width=True,
)


def _persist_records(ticker: str, entries):
    inserted = 0
    updated = 0
    with db_session() as session:
        for entry in entries:
            existing = session.execute(
                select(DividendCache).where(
                    DividendCache.ticker == ticker,
                    DividendCache.event_date == entry.event_date,
                )
            ).scalar_one_or_none()

            if existing:
                existing.amount = entry.amount
                existing.currency = entry.currency
                existing.source = "dart-manual"
                updated += 1
            else:
                session.add(
                    DividendCache(
                        ticker=ticker,
                        event_date=entry.event_date,
                        amount=entry.amount,
                        currency=entry.currency,
                        source="dart-manual",
                    )
                )
                inserted += 1

    return inserted, updated


if st.button("배당 정보 저장", type="primary"):
    inserted, updated = _persist_records(target_ticker, records)
    st.success(f"저장 완료: 신규 {inserted}건, 갱신 {updated}건")
