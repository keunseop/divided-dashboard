import streamlit as st
from sqlalchemy import desc, select

from core.db import db_session
from core.importer import read_and_normalize_csv, upsert_dividends
from core.models import DividendEvent, TickerMaster
from core.user_gate import require_user

require_user()


st.title("배당 내역 가져오기")
st.caption("Excel에서 내려받은 CSV를 업로드하여 배당 원장과 동기화합니다.")

st.subheader("최근 배당 내역")

def fmt_money(x):
    return "" if x is None else f"{x:,.0f}"

with db_session() as s:
    rows = s.execute(
        select(DividendEvent, TickerMaster.name_ko)
        .join(TickerMaster, TickerMaster.ticker == DividendEvent.ticker, isouter=True)
        .where(DividendEvent.archived == False)  # noqa: E712
        .order_by(desc(DividendEvent.pay_date))
        .limit(50)
    ).all()

recent_data = [
    {
        "지급일": ev.pay_date,
        "종목명": f"{name_ko or '(미등록)'} ({ev.ticker})",
        "통화": ev.currency,
        "원화세전": fmt_money(ev.krw_gross),
    }
    for ev, name_ko in rows
]

if recent_data:
    st.dataframe(recent_data, use_container_width=True, hide_index=True)
else:
    st.info("표시할 배당 내역이 없습니다.")

st.divider()
st.subheader("CSV 업로드")

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
