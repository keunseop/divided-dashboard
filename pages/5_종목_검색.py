import pandas as pd
import streamlit as st
from datetime import date
from dateutil.relativedelta import relativedelta
from sqlalchemy import select

from core.kis.domestic_quotes import fetch_domestic_price_history
from core.kis.overseas_quotes import fetch_overseas_price_history

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
from core.models import DividendCache, DividendEvent, TickerMaster
from core.ui_autocomplete import render_ticker_autocomplete
from core.utils import infer_market_from_ticker, normalize_ticker


st.title("종목 검색")

st.caption("티커로 직접 조회하여 최신 배당/가격 내역을 확인합니다.")

@st.cache_data(ttl=300)
def _load_owned_tickers() -> dict[str, str]:
    with db_session() as session:
        rows = (
            session.execute(
                select(DividendEvent.ticker, TickerMaster.name_ko)
                .join(TickerMaster, TickerMaster.ticker == DividendEvent.ticker, isouter=True)
                .where(DividendEvent.archived == False)  # noqa: E712
                .order_by(DividendEvent.ticker)
            )
            .all()
        )
    result: dict[str, str] = {}
    for ticker, name in rows:
        if ticker in result:
            continue
        display = f"{ticker} ({name})" if name else ticker
        result[ticker] = display
    return result


def _persist_dividend_cache(ticker: str, entries):
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
                existing.source = entry.source or existing.source
                updated += 1
            else:
                session.add(
                    DividendCache(
                        ticker=ticker,
                        event_date=entry.event_date,
                        amount=entry.amount,
                        currency=entry.currency,
                        source=entry.source or "manual",
                    )
                )
                inserted += 1
    return inserted, updated


@st.cache_data(ttl=60 * 60 * 6)
def _fetch_price_history_kr(ticker: str, start: date, end: date) -> pd.DataFrame:
    try:
        df = fetch_domestic_price_history(ticker, start=start, end=end)
    except Exception:
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date")
    return df


def _render_price_chart_kr(ticker: str) -> None:
    end = date.today()
    start = end - relativedelta(years=5)
    df = _fetch_price_history_kr(ticker, start, end)
    if df.empty:
        st.warning("시계열 가격 데이터를 불러오지 못했습니다. 잠시 후 다시 시도해주세요.")
        return

    freq = st.radio("가격 차트 주기", ["일간", "주간"], horizontal=True, index=1)
    display_df = df.copy()
    if freq == "주간":
        display_df = (
            display_df.set_index("date")
            .resample("W-FRI")
            .agg({"close": "last"})
            .dropna()
            .reset_index()
        )

    st.subheader("최근 5년 가격 추이")
    st.line_chart(display_df.set_index("date")["close"])

@st.cache_data(ttl=60 * 60 * 6)
def _fetch_price_history_overseas(market: str, ticker: str, start: date, end: date) -> pd.DataFrame:
    try:
        df = fetch_overseas_price_history(market, ticker, start=start, end=end)
    except Exception:
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date")
    return df


def _render_price_chart_overseas(market: str, ticker: str) -> None:
    end = date.today()
    start = end - relativedelta(years=5)
    df = _fetch_price_history_overseas(market, ticker, start, end)
    if df.empty:
        st.warning("시계열 가격 데이터를 불러오지 못했습니다. 잠시 후 다시 시도해주세요.")
        return

    freq = st.radio("가격 차트 주기", ["일간", "주간"], horizontal=True, index=1)
    display_df = df.copy()
    if freq == "주간":
        display_df = (
            display_df.set_index("date")
            .resample("W-FRI")
            .agg({"close": "last"})
            .dropna()
            .reset_index()
        )

    st.subheader("최근 5년 가격 추이")
    st.line_chart(display_df.set_index("date")["close"])

owned_map = _load_owned_tickers()
owned_options = [""] + list(owned_map.keys())
selected_owned = st.selectbox(
    "보유 종목 티커 선택",
    options=owned_options,
    format_func=lambda value: "선택 안 함" if value == "" else owned_map.get(value, value),
)

manual_ticker = st.text_input(
    "티커 입력",
    value="",
    placeholder="예: MMM 또는 005930",
    help="국내/해외 종목을 직접 검색하려면 티커를 입력해주세요.",
)

selected_candidate = render_ticker_autocomplete(
    query=manual_ticker,
    label="수동 검색 (국내 종목)",
    key="ticker_search_autocomplete",
    help_text="국내 종목명을 입력하면 추천 목록이 표시됩니다.",
    limit=20,
    show_input=False,
)

market_option = st.selectbox(
    "시장",
    options=["AUTO", "US", "KR"],
    help="AUTO 선택 시 티커 형식으로 시장을 추정합니다.",
)
history_years = st.slider(
    "조회 연도 수",
    min_value=3,
    max_value=15,
    value=8,
    help="최대 N년까지의 배당 기록을 조회합니다.",
)
force_refresh = st.checkbox(
    "강제 재조회",
    value=False,
    help="체크하면 DART/해외 API를 다시 호출하여 캐시를 무시합니다.",
)

if st.button("조회") is False:
    st.stop()

manual_normalized = normalize_ticker(manual_ticker)
if selected_owned:
    ticker = selected_owned
elif selected_candidate:
    ticker = normalize_ticker(selected_candidate.ticker)
elif manual_normalized:
    ticker = manual_normalized
else:
    st.warning("자동완성에서 종목을 선택하거나 티커를 직접 입력해주세요.")
    st.stop()

is_kr_numeric = ticker.isdigit() and len(ticker) == 6

market = None if market_option == "AUTO" else market_option
market = infer_market_from_ticker(ticker, market)

if is_kr_numeric:
    _render_price_chart_kr(ticker)
else:
    _render_price_chart_overseas(market, ticker)

start_year = max(date.today().year - history_years, 2000)
start_date = date(start_year, 1, 1)

with db_session() as session:
    try:
        price_quote = get_price_quote_for_ticker(session, ticker, market=market)
        dividend_history = get_dividend_history_for_ticker(
            session,
            ticker,
            market=market,
            start_date=start_date,
            force_refresh=force_refresh,
        )
    except NotImplementedError as exc:
        st.error(str(exc))
        st.stop()
    except Exception as exc:
        st.error(f"데이터 조회 과정에서 오류가 발생했습니다: {exc}")
        st.stop()

if not dividend_history:
    st.warning("배당 데이터가 없습니다. ETF/채권형 종목일 수 있습니다.")
    st.stop()

sources = {point.source for point in dividend_history}
if "dart" in sources:
    st.info("DART에서 가져온 최신 배당 데이터입니다. 필요 시 아래 동기화 버튼으로 DB에 반영해주세요.")
else:
    st.caption("캐시된 데이터를 사용했습니다.")

annual = compute_annual_dividends(dividend_history)
metrics = compute_growth_metrics(annual)
trailing = compute_trailing_dividend_yield(dividend_history, price_quote)

st.subheader(f"{ticker} 요약")
col1, col2, col3 = st.columns(3)
col1.metric("현재가", f"{price_quote.price:,.2f} {price_quote.currency}", help=f"as of {price_quote.as_of:%Y-%m-%d %H:%M}")
trailing_yield = trailing["trailing_yield"]
col2.metric(
    "Trailing Yield",
    f"{trailing_yield:.2%}" if trailing_yield is not None else "N/A",
    help=f"Trailing dividend: {trailing['trailing_dividend']:.4f} {price_quote.currency}",
)
trend = metrics["trend"]
col3.metric("Trend", trend)

st.subheader("연도별 배당 추이")
st.bar_chart(annual, x="year", y="annual_dividend")

yoy_series = [
    {"year": year, "yoy": value}
    for year, value in metrics["yoy"].items()
    if value is not None
]

growth_df = pd.DataFrame(
    {
        "3y CAGR": [f"{metrics['cagr_3y']:.2%}" if metrics["cagr_3y"] is not None else "N/A"],
        "5y CAGR": [f"{metrics['cagr_5y']:.2%}" if metrics["cagr_5y"] is not None else "N/A"],
        "Trend": [trend],
    }
)
st.subheader("성장 지표")
st.dataframe(growth_df, hide_index=True)

if yoy_series:
    st.subheader("연도별 YoY")
    yoy_df = pd.DataFrame(yoy_series)
    yoy_df["yoy_pct"] = yoy_df["yoy"].map(lambda v: f"{v:.2%}")
    st.dataframe(yoy_df[["year", "yoy_pct"]], hide_index=True, use_container_width=True)

st.subheader("배당 이벤트 상세 (최근 20건)")
history_df = pd.DataFrame(
    [
        {
            "date": point.event_date,
            "amount": point.amount,
            "currency": point.currency,
            "source": point.source,
        }
        for point in dividend_history[-20:]
    ]
)
st.dataframe(history_df, hide_index=True, use_container_width=True)

if st.button("배당 데이터 DB 반영", type="primary"):
    inserted, updated = _persist_dividend_cache(ticker, dividend_history)
    st.success(f"동기화 완료: 신규 {inserted}건, 갱신 {updated}건")







