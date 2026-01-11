import streamlit as st
from sqlalchemy import select

from core.admin_gate import require_admin
from core.db import db_session
from core.models import TickerMaster
from core.ticker_importer import read_ticker_master_csv, upsert_ticker_master

require_admin()

st.title("관리자: 종목 마스터 관리")
st.caption("Ticker Master 목록을 CSV로 일괄 갱신하거나 현재 등록 상태를 확인합니다.")

uploaded = st.file_uploader(
    "ticker_master.csv 업로드 (필수: ticker,name_ko | 선택: market,currency)",
    type=["csv"],
)

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
    data = [
        {
            "ticker": r.ticker,
            "name_ko": r.name_ko,
            "market": r.market,
            "currency": r.currency,
        }
        for r in rows
    ]

st.dataframe(data, use_container_width=True)
