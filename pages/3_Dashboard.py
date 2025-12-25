import streamlit as st
import pandas as pd
from sqlalchemy import select

from core.db import db_session
from core.models import DividendEvent, AccountType, TickerMaster

st.title("3) Dashboard")

filter_col, account_col = st.columns([3, 1.5])
with filter_col:
    metric = st.selectbox(
        "기준",
        ["KRW 세전(krwGross)", "KRW 세후(krwNet)"],
        key="dashboard_metric",
    )

account_options = ["ALL"] + [acct.value for acct in AccountType]
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
