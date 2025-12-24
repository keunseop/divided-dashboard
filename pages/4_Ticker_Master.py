import streamlit as st
from sqlalchemy import select

from core.db import db_session
from core.models import TickerMaster
from core.ticker_importer import read_ticker_master_csv, upsert_ticker_master

st.title("4) Ticker Master")

uploaded = st.file_uploader("ticker_master.csv 업로드 (ticker,name_ko)", type=["csv"])

if uploaded is not None:
    try:
        df = read_ticker_master_csv(uploaded)
        st.success(f"로드 성공: {len(df):,} rows")
        st.dataframe(df.head(50), use_container_width=True)

        if st.button("Ticker Master Import 실행"):
            with db_session() as s:
                result = upsert_ticker_master(s, df)

            st.success("Import 완료")
            st.write({"inserted": result.inserted, "updated": result.updated})
    except Exception as e:
        st.error(f"Import 실패: {e}")

st.divider()
st.subheader("현재 등록된 Ticker Master (상위 2000개)")

with db_session() as s:
    rows = s.execute(select(TickerMaster).limit(2000)).scalars().all()
    data = [{"ticker": r.ticker, "name_ko": r.name_ko} for r in rows]

st.dataframe(data, use_container_width=True)
