import streamlit as st
from sqlalchemy import select, desc

from core.db import db_session
from core.models import DividendEvent, AccountType, TickerMaster

st.title("2) Dividends Table")

show_archived = st.checkbox("archived 포함", value=False)
account_filter = st.selectbox("계좌", ["ALL", AccountType.TAXABLE.value, AccountType.ISA.value])

def fmt_money(x):
    return "" if x is None else f"{x:,.0f}"

with db_session() as s:
    q = (
        select(DividendEvent, TickerMaster.name_ko)
        .join(TickerMaster, TickerMaster.ticker == DividendEvent.ticker, isouter=True)
        .order_by(desc(DividendEvent.pay_date))
        .limit(2000)
    )

    if not show_archived:
        q = q.where(DividendEvent.archived == False)  # noqa: E712

    if account_filter != "ALL":
        q = q.where(DividendEvent.account_type == AccountType(account_filter))

    rows = s.execute(q).all()

    data = []
    for ev, name_ko in rows:
        data.append({
            "rowId": ev.row_id,
            "payDate": ev.pay_date,
            "ticker": ev.ticker,
            "name": name_ko or "(미등록)",
            "currency": ev.currency,
            "grossDividend(표시)": fmt_money(ev.gross_dividend),
            "krwGross(표시)": (fmt_money(ev.krw_gross) + "원") if ev.krw_gross is not None else "",
            "tax": ev.tax,
            "netDividend": ev.net_dividend,
            "accountType": ev.account_type.value,
            "archived": ev.archived,
        })

st.dataframe(data, use_container_width=True)

st.divider()
st.subheader("rowId로 archived 토글(간단한 수정 기능)")

row_id = st.text_input("rowId")
if st.button("archived 토글") and row_id:
    from sqlalchemy import select
    with db_session() as s:
        obj = s.execute(select(DividendEvent).where(DividendEvent.row_id == row_id)).scalar_one_or_none()
        if obj is None:
            st.error("해당 rowId를 찾지 못했습니다.")
        else:
            obj.archived = not obj.archived
            st.success(f"{row_id}: archived={obj.archived}")
