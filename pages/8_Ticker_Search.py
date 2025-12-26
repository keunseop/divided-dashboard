import pandas as pd
import streamlit as st
from datetime import date

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
from core.ui_autocomplete import render_ticker_autocomplete
from core.utils import infer_market_from_ticker, normalize_ticker

st.title("8) Ticker Search")

st.caption(
    "티커를 직접 조회하여 최신 배당/가격 데이터를 확인합니다. "
    "미국 종목은 yfinance를 사용하며, 한국 종목은 DART/로컬 데이터를 사용합니다."
)

selected_candidate = render_ticker_autocomplete(
    label="자동완성 (국내 종목)",
    key="ticker_search_autocomplete",
    help_text="국내 종목명을 입력하면 아래 드롭다운에서 바로 선택할 수 있습니다. 해외 종목은 직접 입력을 사용하세요.",
    limit=20,
)

manual_ticker = st.text_input(
    "직접 티커 입력 (선택)",
    value="",
    placeholder="예: MMM",
    help="해외 종목 등 자동완성 대상이 아닐 경우 직접 입력하세요.",
)

market_option = st.selectbox(
    "시장",
    options=["AUTO", "US", "KR"],
    help="AUTO 선택 시 티커 형태로 시장을 추론합니다.",
)
history_years = st.slider(
    "불러올 연도",
    min_value=3,
    max_value=15,
    value=8,
    help="최근 N년 치 배당 데이터만 조회합니다.",
)

if st.button("Fetch") is False:
    st.stop()

manual_normalized = normalize_ticker(manual_ticker)
if selected_candidate:
    ticker = normalize_ticker(selected_candidate.ticker)
elif manual_normalized:
    ticker = manual_normalized
else:
    st.warning("자동완성에서 종목을 선택하거나 직접 티커를 입력해 주세요.")
    st.stop()
market = None if market_option == "AUTO" else market_option
market = infer_market_from_ticker(ticker, market)

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
        )
    except NotImplementedError as exc:
        st.error(str(exc))
        st.stop()
    except Exception as exc:
        st.error(f"데이터 조회 중 오류가 발생했습니다: {exc}")
        st.stop()

if not dividend_history:
    st.warning("배당 데이터가 없습니다. ETF/신규상장 종목일 수 있습니다.")
    st.stop()

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

st.subheader("연간 배당 추이")
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

st.subheader("배당 원본 데이터 (최근 20건)")
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
