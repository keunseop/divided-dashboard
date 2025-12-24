import streamlit as st

from core.db import db_session
from core.importer import read_and_normalize_csv, upsert_dividends

st.title("1) CSV Import")

sync_mode = st.checkbox("동기화 모드 (CSV에 없는 기존 excel 데이터는 archived 처리)", value=True)

uploaded = st.file_uploader("CSV 파일 업로드 (UTF-8 권장)", type=["csv"])

if uploaded is not None:
    try:
        df = read_and_normalize_csv(uploaded)
        st.success(f"CSV 로드 성공: {len(df):,} rows")
        st.dataframe(df.head(50), use_container_width=True)

        if st.button("Import 실행"):
            with db_session() as s:
                result = upsert_dividends(s, df, sync_mode=sync_mode)

            st.success("Import 완료")
            st.write(
                {
                    "inserted": result.inserted,
                    "updated": result.updated,
                    "archived_candidates": result.archived_candidates,
                }
            )
    except Exception as e:
        st.error(f"Import 실패: {e}")
