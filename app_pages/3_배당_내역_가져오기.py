import streamlit as st

from core.db import db_session
from core.dividend_reader import list_dividend_events
from core.importer import read_and_normalize_csv, upsert_dividends
from core.ticker_reader import get_ticker_meta_map
from core.user_gate import require_user

require_user()


st.title("배당 내역 가져오기")
st.caption("Excel에서 내려받은 CSV를 업로드하여 배당 원장과 동기화합니다.")

st.subheader("최근 배당 내역")

def fmt_money(x):
    return "" if x is None else f"{x:,.0f}"

with db_session() as s:
    rows = list_dividend_events(s, archived=False, limit=50, order_desc=True)
    tickers = {row.get("ticker") for row in rows if row.get("ticker")}
    meta_map = get_ticker_meta_map(s, tickers=list(tickers))

recent_data = []
for row in rows:
    ticker = row.get("ticker")
    name_ko = meta_map.get(ticker, {}).get("name_ko")
    recent_data.append(
        {
            "지급일": row.get("pay_date"),
            "종목명": f"{name_ko or '(미등록)'} ({ticker})",
            "통화": row.get("currency"),
            "원화세전": fmt_money(row.get("krw_gross")),
        }
    )

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
