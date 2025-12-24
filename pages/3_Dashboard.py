import streamlit as st
import pandas as pd
from sqlalchemy import select

from core.db import db_session
from core.models import DividendEvent, AccountType

st.title("3) Dashboard")

metric = st.selectbox("기준", ["KRW 세전(krwGross)", "KRW 세후(krwNet)"])
account_filter = st.selectbox("계좌", ["ALL", AccountType.TAXABLE.value, AccountType.ISA.value])

col = "krw_gross" if metric.startswith("KRW 세전") else "krw_net"

with db_session() as s:
    q = select(
        DividendEvent.pay_date,
        DividendEvent.year,
        DividendEvent.month,
        DividendEvent.ticker,
        getattr(DividendEvent, col).label("value"),
    ).where(DividendEvent.archived == False)  # noqa: E712

    if account_filter != "ALL":
        q = q.where(DividendEvent.account_type == AccountType(account_filter))

    rows = s.execute(q).all()

if not rows:
    st.info("데이터가 없습니다. 먼저 CSV Import를 해주세요.")
    st.stop()

df = pd.DataFrame(rows, columns=["payDate", "year", "month", "ticker", "value"])
df = df.dropna(subset=["value"])
df["payDate"] = pd.to_datetime(df["payDate"])

this_year = pd.Timestamp.today().year
ytd = df[df["year"] == this_year]["value"].sum()
prev_year = df[df["year"] == this_year - 1]["value"].sum()
yoy = (ytd / prev_year - 1) * 100 if prev_year > 0 else None

c1, c2, c3 = st.columns(3)
c1.metric("올해 누적", f"{ytd:,.0f}")
c2.metric("작년 총액", f"{prev_year:,.0f}")
c3.metric("YoY(참고)", f"{yoy:,.1f}%" if yoy is not None else "N/A")

st.divider()

yearly = df.groupby("year", as_index=False)["value"].sum().sort_values("year")
st.subheader("연도별 배당 추이")
st.bar_chart(yearly, x="year", y="value")

df["ym"] = df["payDate"].dt.to_period("M").astype(str)
monthly = df.groupby("ym", as_index=False)["value"].sum().sort_values("ym")
st.subheader("월별 배당 추이")
st.line_chart(monthly, x="ym", y="value")

top = df.groupby("ticker", as_index=False)["value"].sum().sort_values("value", ascending=False).head(15)
st.subheader("종목 TOP 15")
st.dataframe(top, use_container_width=True)
