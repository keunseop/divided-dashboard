import pandas as pd
import streamlit as st

from core.db import db_session
from core.holdings_service import apply_buy, get_positions
from core.models import AccountType
from core.portfolio_importer import (
    read_holding_positions_csv,
    read_portfolio_snapshots_csv,
    upsert_holding_positions,
    upsert_portfolio_snapshots,
)
from core.ui_autocomplete import render_ticker_autocomplete
from core.utils import normalize_ticker

st.title("10) Portfolio Imports")
st.caption("보유 종목 LOT과 월별 스냅샷 CSV를 업로드하여 포트폴리오 데이터를 관리합니다.")

st.header("현재 보유 포지션 업로드")
st.write(
    """
`holding_positions.csv` 예시 헤더:
`종목코드,계좌구분,수량,평균매입가(원),비고`

- 평균 매입가는 원화 기준으로 입력해 주세요.
- 최초 업로드 시 현재 보유 수량과 평균 매입가를 그대로 넣으면 됩니다.
"""
)

positions_file = st.file_uploader(
    "holding_positions.csv 업로드",
    type=["csv"],
    key="positions_uploader",
)

if positions_file is not None:
    try:
        pos_df = read_holding_positions_csv(positions_file)
        st.success(f"포지션 CSV 로드 성공: {len(pos_df):,} rows")
        st.dataframe(pos_df.head(100), use_container_width=True)

        if st.button("Holding Position Import 실행"):
            with db_session() as session:
                result = upsert_holding_positions(session, pos_df)
            st.success("Holding Position Import 완료")
            st.write({"inserted": result.inserted, "updated": result.updated})
    except Exception as exc:
        st.error(f"Holding Position Import 실패: {exc}")

st.divider()

st.header("Portfolio Snapshots (월별 현황)")
st.write(
    """
`portfolio_snapshots.csv` 예시 헤더:
`snapshotId,기준일,계좌구분,누적원금,현금,평가금액,비고`
"""
)

snapshots_file = st.file_uploader(
    "portfolio_snapshots.csv 업로드",
    type=["csv"],
    key="snapshots_uploader",
)

if snapshots_file is not None:
    try:
        snapshots_df = read_portfolio_snapshots_csv(snapshots_file)
        st.success(f"Snapshot CSV 로드 성공: {len(snapshots_df):,} rows")
        st.dataframe(snapshots_df.head(100), use_container_width=True)

        if st.button("Snapshot Import 실행"):
            with db_session() as session:
                result = upsert_portfolio_snapshots(session, snapshots_df)
            st.success("Snapshot Import 완료")
            st.write({"inserted": result.inserted, "updated": result.updated})
    except Exception as exc:
        st.error(f"Snapshot Import 실패: {exc}")

st.divider()
st.header("추가 매수 기록")
st.write("향후 매수 시 아래 폼으로 수량과 매입가를 입력하면 포지션이 자동 갱신됩니다.")

buy_manual_ticker = st.text_input("티커 입력", placeholder="예: 005930", key="manual_buy_input")
buy_candidate = render_ticker_autocomplete(
    query=buy_manual_ticker,
    label="티커 자동완성",
    key="manual_buy_autocomplete",
    help_text="Ticker Master에 등록된 종목을 선택하세요.",
    limit=30,
    show_input=False,
)
with st.form("manual_buy_form"):
    buy_account = st.selectbox(
        "계좌",
        options=[acct.value for acct in AccountType if acct != AccountType.ALL],
    )
    buy_quantity = st.number_input("매수 수량", min_value=0.0, step=1.0)
    buy_price = st.number_input("매수 단가 (KRW)", min_value=0.0, step=100.0)
    buy_note = st.text_input("메모", value="")
    submitted_buy = st.form_submit_button("매수 반영")

if submitted_buy:
    try:
        if buy_candidate:
            buy_ticker = buy_candidate.ticker
        else:
            buy_ticker = normalize_ticker(buy_manual_ticker)
        if not buy_ticker:
            raise ValueError("자동완성에서 종목을 선택하거나 직접 입력해 주세요.")
        if buy_quantity <= 0 or buy_price <= 0:
            raise ValueError("수량과 단가는 0보다 커야 합니다.")
        with db_session() as session:
            apply_buy(
                session,
                ticker=buy_ticker,
                account_type=AccountType(buy_account),
                buy_quantity=buy_quantity,
                buy_price_krw=buy_price,
                note=buy_note or None,
                source="manual",
            )
        st.success("매수 내용이 저장되었습니다.")
    except Exception as exc:
        st.error(f"매수 반영 실패: {exc}")

st.divider()
st.header("현재 포지션 미리보기")
account_filter = st.selectbox(
    "계좌 필터",
    options=["ALL"] + [acct.value for acct in AccountType if acct != AccountType.ALL],
    help="계좌별로 잔여 수량과 평균 단가를 확인합니다.",
)

with db_session() as session:
    account = None if account_filter == "ALL" else AccountType(account_filter)
    positions = get_positions(session, account_type=account)

if not positions:
    st.info("등록된 포지션이 없습니다. CSV 업로드 또는 매수 입력으로 추가해 주세요.")
else:
    df = pd.DataFrame(
        [
            {
                "Ticker": pos.ticker,
                "Account": pos.account_type.value,
                "Quantity": f"{pos.quantity:,.4f}",
                "Avg Buy Price (KRW)": f"{pos.avg_buy_price_krw:,.2f}",
                "Cost Basis (KRW)": f"{pos.total_cost_krw:,.0f}",
            }
            for pos in positions
        ]
    )
    st.dataframe(df, use_container_width=True, hide_index=True)
