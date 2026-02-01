import pandas as pd
import streamlit as st
from sqlalchemy import select

from core.admin_gate import require_admin
from core.db import db_session
from core.firestore_reader import is_firestore_enabled, list_ticker_master
from core.models import TickerMaster
from core.ticker_importer import read_ticker_master_csv, upsert_ticker_master

require_admin()

st.title("관리자: 종목 마스터 관리")
st.caption("Ticker Master 목록을 CSV로 일괄 갱신하거나 현재 등록 상태를 확인합니다.")

st.subheader("단건 등록")
st.caption("Firestore 모드에서 단건으로 티커를 추가합니다.")
with st.form("ticker_master_single_form"):
    ticker = st.text_input("티커", placeholder="예: 005930, AAPL").strip().upper()
    name_ko = st.text_input("종목명(한글)", placeholder="예: 삼성전자, 애플").strip()
    market = st.text_input("시장(선택)", placeholder="예: KR, US").strip().upper() or None
    currency = st.text_input("통화(선택)", placeholder="예: KRW, USD").strip().upper() or None
    submitted = st.form_submit_button("단건 추가")
if submitted:
    try:
        if not is_firestore_enabled():
            raise ValueError("Firestore 모드가 아니어서 단건 등록을 지원하지 않습니다.")
        if not ticker:
            raise ValueError("티커는 필수입니다.")
        if not name_ko:
            raise ValueError("종목명은 필수입니다.")
        df = pd.DataFrame(
            [
                {
                    "ticker": ticker,
                    "name_ko": name_ko,
                    "market": market,
                    "currency": currency,
                }
            ]
        )
        with db_session() as s:
            result = upsert_ticker_master(s, df)
        st.success("단건 추가 완료")
        st.write({"inserted": result.inserted, "updated": result.updated})
    except Exception as e:
        st.error(f"단건 추가 실패: {e}")

st.divider()
st.subheader("CSV 업로드")

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

if is_firestore_enabled():
    entries = list_ticker_master()
    data = [
        {
            "ticker": ticker,
            "name_ko": meta.get("name_ko"),
            "market": meta.get("market"),
            "currency": meta.get("currency"),
        }
        for ticker, meta in entries.items()
    ][:2000]
else:
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
