import pandas as pd
import streamlit as st
from sqlalchemy import select

from core.db import db_session
from core.models import DividendEvent, TickerMaster

st.title("5) Missing Tickers")

st.caption("DividendEvent에는 존재하지만 TickerMaster에 없는 ticker 목록입니다. 내려받아 name_ko만 채운 뒤 Ticker Master로 다시 Import하세요.")

with db_session() as s:
    ev_tickers = (
        s.execute(
            select(DividendEvent.ticker)
            .where(DividendEvent.archived == False)  # noqa: E712
            .distinct()
        )
        .scalars()
        .all()
    )

    master_tickers = s.execute(select(TickerMaster.ticker)).scalars().all()

ev_set = {t.strip().upper() for t in ev_tickers if t and str(t).strip()}
master_set = {t.strip().upper() for t in master_tickers if t and str(t).strip()}

missing = sorted(ev_set - master_set)

st.write(f"미등록 티커: **{len(missing):,}개**")

df = pd.DataFrame({"ticker": missing, "name_ko": [""] * len(missing)})
st.dataframe(df, use_container_width=True)

csv_bytes = df.to_csv(index=False).encode("utf-8-sig")
st.download_button(
    label="미등록 티커 CSV 다운로드",
    data=csv_bytes,
    file_name="missing_tickers.csv",
    mime="text/csv",
)
