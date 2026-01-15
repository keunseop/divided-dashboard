from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import altair as alt
import pandas as pd
import streamlit as st
from sqlalchemy import select

from core.analytics import (
    compute_annual_dividends,
    compute_growth_metrics,
    compute_trailing_dividend_yield,
)
from core.db import db_session
from core.market_service import (
    get_dividend_history_for_ticker,
    get_price_quote_for_ticker,
)
from core.models import DividendEvent, TickerMaster
from core.user_gate import require_user
from core.ui_autocomplete import render_ticker_autocomplete
from core.utils import infer_market_from_ticker, normalize_ticker


require_user()
st.title("보유 종목 배당 추이")
st.caption(
    "보유(또는 관심) 종목을 직접 선택하여 최근 배당 추이와 성장 지표를 확인합니다. "
    "선택한 종목만 조회하므로 과도한 API 호출 없이 필요한 종목을 빠르게 살펴볼 수 있습니다."
)

SESSION_STATE_KEY = "held_trend_state"


@dataclass(frozen=True)
class HeldTicker:
    ticker: str
    name: str
    market: str | None
    has_events: bool

    @property
    def label(self) -> str:
        suffix = " ★" if self.has_events else ""
        return f"{self.name} ({self.ticker}){suffix}"


def load_ticker_candidates() -> dict[str, HeldTicker]:
    with db_session() as session:
        master_rows = session.execute(
            select(TickerMaster.ticker, TickerMaster.name_ko, TickerMaster.market)
        ).all()
        held_rows = session.execute(
            select(DividendEvent.ticker)
            .where(DividendEvent.archived == False)
            .distinct()
        ).scalars().all()

    held_set = {normalize_ticker(ticker) for ticker in held_rows if normalize_ticker(ticker)}
    candidates: dict[str, HeldTicker] = {}
    for raw_ticker, name_ko, market in master_rows:
        ticker = normalize_ticker(raw_ticker)
        if not ticker:
            continue
        candidates[ticker] = HeldTicker(
            ticker=ticker,
            name=name_ko or ticker,
            market=market,
            has_events=ticker in held_set,
        )

    return candidates


def default_selection(candidates: dict[str, HeldTicker], max_items: int = 5) -> list[str]:
    held = [ticker for ticker, info in candidates.items() if info.has_events]
    ordered = held or list(candidates.keys())
    return ordered[:max_items]


def build_trend_rows(
    tickers: list[str],
    *,
    candidate_lookup: dict[str, HeldTicker],
    history_years: int,
    min_years: int,
):
    today = date.today()
    start_year = max(today.year - history_years, 2000)
    start_date = date(start_year, 1, 1)

    summary_rows = []
    errors = []
    not_supported = []

    with db_session() as session:
        for ticker in tickers:
            info = candidate_lookup.get(ticker) or HeldTicker(
                ticker=ticker,
                name=ticker,
                market=None,
                has_events=False,
            )

            market = infer_market_from_ticker(ticker, info.market)

            try:
                price_quote = get_price_quote_for_ticker(session, ticker, market=market)
                dividend_history = get_dividend_history_for_ticker(
                    session,
                    ticker,
                    market=market,
                    start_date=start_date,
                )
            except NotImplementedError:
                not_supported.append(ticker)
                continue
            except Exception as exc:
                errors.append(f"{ticker}: {exc}")
                continue

            if not dividend_history:
                errors.append(f"{ticker}: 배당 데이터가 없습니다.")
                continue

            annual = compute_annual_dividends(dividend_history)
            if annual.empty or len(annual) < min_years:
                errors.append(f"{ticker}: 배당 이력이 {min_years}년 미만입니다.")
                continue

            metrics = compute_growth_metrics(annual)
            trailing = compute_trailing_dividend_yield(dividend_history, price_quote)
            last_year = int(annual["year"].max())
            yoy_last = metrics["yoy"].get(last_year)

            summary_rows.append(
                {
                    "ticker": ticker,
                    "name": info.name,
                    "market": market,
                    "price": price_quote.price,
                    "price_currency": price_quote.currency,
                    "price_time": price_quote.as_of,
                    "trailing_yield": trailing["trailing_yield"],
                    "trailing_dividend": trailing["trailing_dividend"],
                    "yoy_last": yoy_last,
                    "cagr_3y": metrics["cagr_3y"],
                    "cagr_5y": metrics["cagr_5y"],
                    "trend": metrics["trend"],
                    "annual_df": annual,
                    "yoy_series": metrics["yoy"],
                }
            )

    return summary_rows, errors, not_supported


candidates = load_ticker_candidates()
if not candidates:
    st.info("Ticker Master에 등록된 종목이 없습니다. 먼저 Ticker Master 페이지에서 종목을 등록해 주세요.")
    st.stop()

label_map = {ticker: info.label for ticker, info in candidates.items()}
reverse_label = {label: ticker for ticker, label in label_map.items()}

state = st.session_state.setdefault(
    SESSION_STATE_KEY,
    {
        "selected": default_selection(candidates),
        "results": None,
        "filters": None,
    },
)

st.subheader("종목 선택")
selected_labels_default = [label_map.get(ticker, ticker) for ticker in state["selected"]]
selected_labels = st.multiselect(
    "분석할 종목",
    options=list(label_map.values()),
    default=selected_labels_default,
    help="보유 종목(★) 또는 관심 종목을 선택하세요. 최대 20개를 권장합니다.",
)
selected_tickers = [reverse_label[label] for label in selected_labels]
state["selected"] = selected_tickers

add_col1, add_col2 = st.columns([4, 1])
with add_col1:
    candidate_to_add = render_ticker_autocomplete(
        label="추가할 종목 검색",
        key="held_trend_add",
        help_text="자동완성에서 선택한 종목을 목록에 추가합니다.",
        limit=20,
    )
with add_col2:
    if st.button("목록에 추가", use_container_width=True, disabled=candidate_to_add is None):
        if candidate_to_add.ticker not in state["selected"]:
            state["selected"].append(candidate_to_add.ticker)
            st.success(f"{candidate_to_add.display} 추가됨")
        else:
            st.info("이미 선택된 종목입니다.")

st.divider()

history_years = st.slider(
    "최근 N년 데이터 조회",
    min_value=3,
    max_value=15,
    value=8,
    help="최근 몇 년간의 배당 데이터를 수집할지 선택합니다.",
)
min_years = st.slider(
    "최소 배당 연도 수",
    min_value=1,
    max_value=history_years,
    value=3,
    help="배당 이력이 부족한 종목은 제외합니다.",
)

fetch_clicked = st.button("배당 추이 조회", use_container_width=True)
current_filters = {
    "history_years": history_years,
    "min_years": min_years,
    "selected": tuple(state["selected"]),
}

if fetch_clicked:
    if not state["selected"]:
        st.warning("최소 한 개 이상의 종목을 선택해 주세요.")
    else:
        with st.spinner("선택된 종목의 배당 데이터를 조회 중입니다..."):
            summary_rows, errors, not_supported = build_trend_rows(
                state["selected"],
                candidate_lookup=candidates,
                history_years=history_years,
                min_years=min_years,
            )
        state["results"] = {
            "summary_rows": summary_rows,
            "errors": errors,
            "not_supported": not_supported,
        }
        state["filters"] = current_filters

results = state.get("results")
if not results:
    st.info("종목을 선택하고 '배당 추이 조회' 버튼을 눌러주세요.")
    st.stop()

if state.get("filters") != current_filters:
    st.warning("필터가 변경되었습니다. '배당 추이 조회' 버튼을 눌러 결과를 갱신하세요.")

summary_rows = results["summary_rows"]
errors = results["errors"]
not_supported = results["not_supported"]

if not summary_rows:
    st.warning("조건에 맞는 결과가 없습니다. 선택 종목이나 필터를 조정한 후 재조회하세요.")
    if not_supported:
        st.info("일부 종목은 데이터 공급자에서 지원되지 않았습니다.")
    for msg in errors:
        st.error(msg)
    st.stop()

display_df = pd.DataFrame(
    [
        {
            "Ticker": row["ticker"],
            "Name": row["name"],
            "Market": row["market"],
            "Price": f"{row['price']:,.0f} {row['price_currency']}",
            "Trailing Yield": f"{row['trailing_yield']:.2%}" if row["trailing_yield"] is not None else "N/A",
            "YoY (Last Year)": f"{row['yoy_last']:.2%}" if row["yoy_last"] is not None else "N/A",
            "3y CAGR": f"{row['cagr_3y']:.2%}" if row["cagr_3y"] is not None else "N/A",
            "5y CAGR": f"{row['cagr_5y']:.2%}" if row["cagr_5y"] is not None else "N/A",
            "Trend": row["trend"],
        }
        for row in summary_rows
    ]
)

st.subheader("요약 테이블")
st.caption("★ 표시는 Dividend Events(보유 이력)가 있는 종목입니다.")
st.dataframe(display_df, use_container_width=True, hide_index=True)

st.subheader("상세 차트")
for row in summary_rows:
    with st.expander(f"{row['ticker']} - {row['name']} ({row['trend']})", expanded=False):
        trailing_yield_text = (
            f"{row['trailing_yield']:.2%}" if row["trailing_yield"] is not None else "N/A"
        )
        st.write(
            f"가격 기준일: {row['price_time']:%Y-%m-%d %H:%M} | "
            f"Trailing Dividend: {row['trailing_dividend']:,.0f} {row['price_currency']} | "
            f"Trailing Yield: {trailing_yield_text}"
        )
        annual_chart = alt.Chart(row["annual_df"]).mark_bar().encode(
            x=alt.X("year:O", title="연도", sort=None),
            y=alt.Y("annual_dividend:Q", title="연간 배당", axis=alt.Axis(format=",.0f")),
            tooltip=[
                alt.Tooltip("year:O", title="연도"),
                alt.Tooltip("annual_dividend:Q", title="연간 배당", format=",.0f"),
            ],
        )
        st.altair_chart(annual_chart, use_container_width=True)

if errors:
    st.warning("일부 종목은 오류로 제외되었습니다:")
    for msg in errors:
        st.text(f"- {msg}")

if not_supported:
    st.info("일부 종목은 데이터 공급자에서 지원되지 않았습니다.")
