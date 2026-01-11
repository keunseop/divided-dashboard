import pandas as pd
import streamlit as st
from sqlalchemy import select

from core.admin_gate import require_admin
from core.db import db_session
from core.models import DividendEvent, TickerMaster
from core.ticker_importer import upsert_ticker_master

require_admin()

st.title("관리자: 미등록 티커 확인")
st.caption("배당 원장에는 존재하지만 Ticker Master에 없는 티커를 찾아 CSV로 내보내고 즉시 추가할 수 있습니다.")

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

st.write(f"미등재티커: **{len(missing):,}개**")

df = pd.DataFrame({"ticker": missing, "name_ko": [""] * len(missing)})
st.dataframe(df, use_container_width=True)

csv_bytes = df.to_csv(index=False).encode("utf-8-sig")
st.download_button(
    label="미등재티커 CSV 다운로드",
    data=csv_bytes,
    file_name="missing_tickers.csv",
    mime="text/csv",
)

st.divider()
if len(missing) > 0:
    if st.button("미등록티커만추가하기"):
        try:
            with db_session() as s:
                result = upsert_ticker_master(s, df)
            st.success(f"추가 완료: inserted={result.inserted}, updated={result.updated}")
        except Exception as e:
            st.error(f"추가 실패: {e}")
else:
    st.caption("미등록된 티커가 없습니다.")
