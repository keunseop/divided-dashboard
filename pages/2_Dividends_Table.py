import streamlit as st
from sqlalchemy import select, desc

from core.db import db_session
from core.models import DividendEvent, AccountType

st.title("2) Dividends Table")

show_archived = st.checkbox("archived 포함", value=False)
account_filter = st.selectbox("계좌", ["ALL", AccountType.TAXABLE.value, AccountType.ISA.value])

with db_session() as s:
    q = select(DividendEvent).order_by(desc(DividendEvent.pay_date)).limit(2000)

    if not show_archived:
        q = q.where(DividendEvent.archived == False)  # noqa: E712

    if account_filter != "ALL":
        q = q.where(DividendEvent.account_type == AccountType(account_filter))

    rows = s.execute(q).scalars().all()

    data = [{
        "rowId": r.row_id,
        "payDate": r.pay_date,
        "year": r.year,
        "month": r.month,
        "ticker": r.ticker,
        "currency": r.currency,
        "fxRate": r.fx_rate,
        "grossDividend": r.gross_dividend,
        "tax": r.tax,
        "netDividend": r.net_dividend,
        "krwGross": r.krw_gross,
        "krwNet": r.krw_net,
        "accountType": r.account_type.value,
        "archived": r.archived,
        "source": r.source,
    } for r in rows]

st.dataframe(data, use_container_width=True)

st.divider()
st.subheader("rowId로 archived 토글(간단한 수정 기능)")

row_id = st.text_input("rowId")
if st.button("archived 토글") and row_id:
    with db_session() as s:
        obj = s.execute(select(DividendEvent).where(DividendEvent.row_id == row_id)).scalar_one_or_none()
        if obj is None:
            st.error("해당 rowId를 찾지 못했습니다.")
        else:
            obj.archived = not obj.archived
            st.success(f"{row_id}: archived={obj.archived}")
