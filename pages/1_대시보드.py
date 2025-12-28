import streamlit as st
import pandas as pd
from sqlalchemy import select

from core.db import db_session
from core.models import DividendEvent, AccountType, TickerMaster
from core.valuation_service import (
    calculate_position_valuations,
    get_valuation_history,
    summarize_valuations,
    upsert_valuation_snapshots,
)

st.title("대시보드")
st.caption("배당 현황, 계좌별 지표, 포트폴리오 평가 추이를 한눈에 확인합니다.")

filter_col, account_col = st.columns([3, 1.5])
with filter_col:
    metric = st.selectbox(
        "기준",
        ["KRW 세전(krwGross)", "KRW 세후(krwNet)"],
        key="dashboard_metric",
    )

account_options = ["ALL"] + [acct.value for acct in AccountType if acct != AccountType.ALL]
with account_col:
    account_filter = st.selectbox(
        "계좌",
        account_options,
        key="dashboard_account",
        help="필요 시 계좌 유형별로 배당 현황을 제한할 수 있습니다.",
    )

col = "krw_gross" if metric.startswith("KRW 세전") else "krw_net"

with db_session() as s:
    q = (
        select(
            DividendEvent.pay_date,
            DividendEvent.year,
            DividendEvent.month,
            DividendEvent.ticker,
            getattr(DividendEvent, col).label("value"),
        ).where(DividendEvent.archived == False)
    )  # noqa: E712

    if account_filter != "ALL":
        q = q.where(DividendEvent.account_type == AccountType(account_filter))

    rows = s.execute(q).all()
    ticker_name_map = dict(
        s.execute(select(TickerMaster.ticker, TickerMaster.name_ko)).all()
    )

if not rows:
    st.info("데이터가 없습니다. 먼저 CSV Import를 해주세요.")
    st.stop()


def fmt_krw(x):
    return "N/A" if x is None else f"{x:,.0f}원"


df = pd.DataFrame(rows, columns=["payDate", "year", "month", "ticker", "value"])
df = df.dropna(subset=["value"])
df["payDate"] = pd.to_datetime(df["payDate"])

this_year = pd.Timestamp.today().year
ytd = df[df["year"] == this_year]["value"].sum()
prev_year = df[df["year"] == this_year - 1]["value"].sum()
yoy = (ytd / prev_year - 1) * 100 if prev_year > 0 else None

c1, c2, c3 = st.columns(3)
c1.metric("올해 누적", fmt_krw(ytd))
c2.metric("작년 총액", fmt_krw(prev_year))
c3.metric("YoY(참고)", f"{yoy:,.1f}%" if yoy is not None else "N/A")

st.divider()

yearly = df.groupby("year", as_index=False)["value"].sum().sort_values("year")
st.subheader("연도별 배당 추이")
st.bar_chart(yearly, x="year", y="value")

df["ym"] = df["payDate"].dt.to_period("M").astype(str)
monthly = df.groupby("ym", as_index=False)["value"].sum().sort_values("ym")
st.subheader("월별 배당 추이")
st.line_chart(monthly, x="ym", y="value")

top = (
    df.groupby("ticker", as_index=False)["value"]
    .sum()
    .sort_values("value", ascending=False)
    .head(15)
)
top["name_ko"] = top["ticker"].map(lambda t: ticker_name_map.get(t, "미등록"))
st.subheader("종목 TOP 15")
top_display = top[["ticker", "name_ko", "value"]].copy()
top_display["value"] = top_display["value"].map(lambda v: f"{v:,.0f}원")
st.dataframe(top_display, use_container_width=True)

st.divider()
st.subheader("보유 포지션 현재가 및 평가손익")
st.caption("계좌 필터가 적용됩니다. 가격은 KR 종목 스냅샷/price_cache 또는 yfinance를 사용하며 6시간 캐시를 활용합니다.")
force_price_refresh = st.checkbox(
    "가격 강제 재조회",
    value=False,
    help="체크하면 price_cache를 무시하고 외부 데이터 소스를 다시 호출합니다.",
)

with st.spinner("보유 종목의 현재가를 계산하는 중입니다..."):
    with db_session() as session:
        valuations, valuation_errors = calculate_position_valuations(
            session,
            force_refresh=force_price_refresh,
        )
        history_account = AccountType.ALL if account_filter == "ALL" else AccountType(account_filter)
        history_entries = get_valuation_history(session, history_account, limit=180)

summaries = summarize_valuations(valuations)
selected_account = None if account_filter == "ALL" else AccountType(account_filter)
summary_key = AccountType.ALL if selected_account is None else selected_account
summary = summaries.get(summary_key)

if summary and summary.positions_count > 0:
    metric_cols = st.columns(3)
    metric_cols[0].metric("총 투자원금", f"{summary.total_cost_krw:,.0f}원")
    metric_cols[1].metric("현재 평가액", f"{summary.market_value_krw:,.0f}원")
    delta_display = (
        f"{summary.gain_loss_pct:,.2f}%" if summary.gain_loss_pct is not None else "N/A"
    )
    metric_cols[2].metric(
        "평가손익",
        f"{summary.gain_loss_krw:,.0f}원",
        delta=delta_display,
    )
else:
    st.info("표시할 포지션이 없거나 가격 정보를 가져올 수 없습니다.")

missing_prices = [
    f"{val.ticker} ({val.account_type.value})"
    for val in valuations
    if val.market_value_krw is None
]
if missing_prices:
    st.warning(
        "가격 데이터가 없어 평가에서 제외된 종목: "
        + ", ".join(missing_prices[:10])
        + ("..." if len(missing_prices) > 10 else ""),
    )
if valuation_errors:
    st.error("가격 계산 중 오류: " + "; ".join(valuation_errors))

display_valuations = [
    val for val in valuations if selected_account is None or val.account_type == selected_account
]

if display_valuations:
    df = pd.DataFrame(
        [
            {
                "Symbol": f"{val.ticker} ({val.name_ko})" if val.name_ko else val.ticker,
                "Account": val.account_type.value,
                "Quantity": val.quantity,
                "Avg Buy Price (KRW)": val.avg_buy_price_krw,
                "Total Cost (KRW)": val.total_cost_krw,
                "Price": val.price,
                "Currency": val.price_currency,
                "Price (KRW)": val.price_krw,
                "Market Value (KRW)": val.market_value_krw,
                "Gain/Loss (KRW)": val.gain_loss_krw,
                "Gain/Loss %": val.gain_loss_pct,
                "Price As Of": val.price_as_of,
                "Source": val.price_source,
            }
            for val in display_valuations
        ]
    )

    def _gain_style(value):
        if pd.isna(value):
            return ""
        if value > 0:
            return "color: #d90429;"
        if value < 0:
            return "color: #0057d9;"
        return ""

    formatters = {
        "Quantity": "{:,.4f}",
        "Avg Buy Price (KRW)": "{:,.0f}",
        "Total Cost (KRW)": "{:,.0f}",
        "Price": "{:,.2f}",
        "Price (KRW)": "{:,.0f}",
        "Market Value (KRW)": "{:,.0f}",
        "Gain/Loss (KRW)": "{:,.0f}",
        "Gain/Loss %": "{:,.2f}%",
    }
    styled = (
        df.style.format(formatters, na_rep="-")
        .applymap(_gain_style, subset=["Gain/Loss %"])
        .hide(axis="index")
    )
    st.dataframe(styled, use_container_width=True)
else:
    st.info("선택한 계좌에 표시할 포지션이 없습니다.")

summary_all = summaries.get(AccountType.ALL)
if summary_all and summary_all.positions_count > 0:
    if st.button("오늘 평가액 기록 저장", help="현재 계산된 평가액 합계를 holding_valuation_snapshots 테이블에 저장합니다."):
        with db_session() as session:
            result = upsert_valuation_snapshots(session, summaries)
        st.success(f"평가액 저장 완료 (inserted {result.inserted}, updated {result.updated})")

st.subheader("평가액 추이")
history_label = "전체" if history_account == AccountType.ALL else history_account.value
if history_entries:
    history_df = pd.DataFrame(
        [
            {
                "valuation_date": entry.valuation_date,
                "market_value_krw": entry.market_value_krw,
                "total_cost_krw": entry.total_cost_krw,
                "gain_loss_krw": entry.gain_loss_krw,
            }
            for entry in history_entries
        ]
    )
    st.caption(f"{history_label} 계좌 기준 최근 {len(history_entries)}건")
    st.line_chart(
        history_df,
        x="valuation_date",
        y=["market_value_krw", "total_cost_krw"],
    )
else:
    st.info(f"{history_label} 계좌에 저장된 평가 기록이 없습니다. '오늘 평가액 기록 저장' 버튼을 사용해 주세요.")
