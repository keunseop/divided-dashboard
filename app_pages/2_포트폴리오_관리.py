import pandas as pd
import streamlit as st
from sqlalchemy import select

from core.db import db_session
from core.holdings_service import get_positions, list_trades, record_trade
from core.fx import fetch_fx_rate_frankfurter
from core.models import AccountType, HoldingLot, HoldingPosition, TickerMaster, TradeSide
from core.portfolio_importer import (
    read_holding_lots_csv,
    read_holding_positions_csv,
    read_portfolio_snapshots_csv,
    upsert_holding_lots,
    upsert_holding_positions,
    upsert_portfolio_snapshots,
)
from core.ui_autocomplete import render_ticker_autocomplete
from core.utils import normalize_ticker
st.title("포트폴리오 관리")
st.caption("보유 종목 Snapshot/Lot CSV 업로드, 수동 거래 입력, 기본 포지션 수정까지 한 곳에서 처리합니다.")


def _render_csv_importers():
    st.subheader("거래(LOT) CSV 업로드")
    st.write(
        """
`holding_lots.csv` 예시 헤더:
`거래일,종목코드,계좌구분,side,수량,단가,통화,환율,단가(KRW),금액(krw),비고`

- `side`에는 BUY/SELL 또는 매수/매도를 입력할 수 있습니다. (미입력 시 BUY로 처리)
- 통화가 KRW가 아니면 `환율`을 채워주세요.
- 기존 BUY-only 파일도 그대로 업로드할 수 있습니다.
"""
    )

    lots_file = st.file_uploader(
        "holding_lots.csv 업로드",
        type=["csv"],
        key="lots_uploader",
    )

    if lots_file is not None:
        try:
            lots_df = read_holding_lots_csv(lots_file)
            st.success(f"Lot CSV 로드 성공: {len(lots_df):,} rows")
            st.dataframe(lots_df.head(200), use_container_width=True)

            if st.button("Holding Lot Import 실행"):
                with db_session() as session:
                    result = upsert_holding_lots(session, lots_df)
                st.success("Holding Lot Import 완료")
                st.write({"inserted": result.inserted, "updated": result.updated})
        except Exception as exc:
            st.error(f"Holding Lot Import 실패: {exc}")

    st.divider()

    st.subheader("현재 보유 포지션 업로드")
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

    st.subheader("포트폴리오 스냅샷 (월별 현황)")
    st.write(
        """
`portfolio_snapshots.csv` 예시 헤더:
`snapshotId,기준일,계좌구분,누적원금,현금,평가금액,비고`

- `snapshotId`는 선택 사항이지만, 동일 스냅샷을 다시 업로드할 때 고유 키로 사용됩니다.
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

with db_session() as session:
    has_any_positions = session.execute(select(HoldingPosition.id).limit(1)).first() is not None
    has_any_lots = session.execute(select(HoldingLot.id).limit(1)).first() is not None

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
                "Symbol": f"{pos.ticker} ({pos.name_ko})" if pos.name_ko else pos.ticker,
                "Account": pos.account_type.value,
                "Quantity": pos.quantity,
                "Avg Buy Price (KRW)": pos.avg_buy_price_krw,
                "Cost Basis (KRW)": pos.total_cost_krw,
                "Realized PnL (KRW)": pos.realized_pnl_krw,
            }
            for pos in positions
        ]
    )
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Symbol": st.column_config.TextColumn("종목"),
            "Account": st.column_config.TextColumn("계좌"),
            "Quantity": st.column_config.NumberColumn("수량", format="%.4f"),
            "Avg Buy Price (KRW)": st.column_config.NumberColumn("평균 매입가 (KRW)", format="%.2f"),
            "Cost Basis (KRW)": st.column_config.NumberColumn("Cost Basis (KRW)", format="%.0f"),
            "Realized PnL (KRW)": st.column_config.NumberColumn("실현손익 (KRW)", format="%.0f"),
        },
    )

st.divider()
st.header("거래 내역 미리보기")
trade_filter_col1, trade_filter_col2, trade_filter_col3 = st.columns([2, 1.5, 1])
with trade_filter_col1:
    trade_filter_ticker = st.text_input("티커 필터", value="")
with trade_filter_col2:
    trade_filter_account = st.selectbox(
        "계좌 필터",
        options=["ALL"] + [acct.value for acct in AccountType if acct != AccountType.ALL],
        key="trade_account_filter",
    )
with trade_filter_col3:
    trade_limit = st.number_input("표시 건수", min_value=50, max_value=1000, value=200, step=50)

with db_session() as session:
    account_arg = None if trade_filter_account == "ALL" else AccountType(trade_filter_account)
    trades = list_trades(
        session,
        account_type=account_arg,
        ticker=trade_filter_ticker or None,
        limit=int(trade_limit),
    )

if not trades:
    st.info("표시할 거래가 없습니다.")
else:
    trade_df = pd.DataFrame(
        [
            {
                "Date": lot.trade_date,
                "Ticker": lot.ticker,
                "Account": lot.account_type.value,
                "Side": lot.side.value,
                "Quantity": lot.quantity,
                "Price": lot.price,
                "Currency": lot.currency,
                "FX": lot.fx_rate,
                "Price (KRW)": lot.price_krw,
                "Amount (KRW)": lot.amount_krw,
                "Note": lot.note or "",
                "Source": lot.source,
            }
            for lot in trades
        ]
    )
    st.dataframe(
        trade_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Quantity": st.column_config.NumberColumn("수량", format="%.4f"),
            "Price": st.column_config.NumberColumn("단가", format="%.2f"),
            "Price (KRW)": st.column_config.NumberColumn("단가 (KRW)", format="%.0f"),
            "Amount (KRW)": st.column_config.NumberColumn("금액 (KRW)", format="%.0f"),
        },
    )

st.divider()
st.header("수동 거래 입력 (BUY/SELL)")
st.write("급한 거래는 아래 폼에서 직접 입력해 주세요. 외화 거래는 환율을 함께 입력하면 KRW 환산 금액이 자동 계산됩니다.")

manual_ticker = st.text_input("티커 입력", placeholder="예: 005930", key="manual_trade_input")
manual_candidate = render_ticker_autocomplete(
    query=manual_ticker,
    label="티커 자동완성",
    key="manual_trade_autocomplete",
    help_text="Ticker Master에 등록된 종목을 선택하세요.",
    limit=30,
    show_input=False,
)

trade_account = st.selectbox(
    "계좌",
    options=[acct.value for acct in AccountType if acct != AccountType.ALL],
    key="manual_trade_account",
)
trade_side = st.selectbox(
    "매매 구분",
    options=[TradeSide.BUY.value, TradeSide.SELL.value],
    format_func=lambda v: "매수" if v == TradeSide.BUY.value else "매도",
    key="manual_trade_side",
)
trade_date = st.date_input("거래일", key="manual_trade_date")
trade_quantity = st.number_input("수량", min_value=0.0, step=1.0, key="manual_trade_quantity")
trade_currency = st.selectbox("통화", options=["KRW", "USD"], index=0, key="manual_trade_currency")
trade_price = st.number_input("단가 (통화 기준)", min_value=0.0, step=10.0, key="manual_trade_price")
fx_key = "manual_trade_fx_value"
auto_fx_error = None
auto_fx_info = None
current_fx = st.session_state.get(fx_key, 1.0)
if trade_currency == "KRW":
    if current_fx != 1.0:
        st.session_state[fx_key] = 1.0
else:
    try:
        fetched = fetch_fx_rate_frankfurter(trade_currency, "KRW", trade_date)
        if fetched:
            rate = round(float(fetched), 4)
            st.session_state[fx_key] = rate
            auto_fx_info = f"{trade_currency} 환율 자동 입력: {rate:.4f}"
        else:
            st.session_state[fx_key] = 0.0
            auto_fx_error = f"{trade_currency} 환율을 가져오지 못했습니다. 값을 직접 입력해 주세요."
    except Exception as exc:
        st.session_state[fx_key] = 0.0
        auto_fx_error = f"{trade_currency} 환율 자동 조회 실패: {exc}"

trade_fx = st.number_input(
    "환율 (KRW/통화)",
    min_value=0.0,
    step=0.01,
    key=fx_key,
    help="통화가 KRW면 자동으로 1.0이 설정됩니다.",
)
if auto_fx_info:
    st.info(auto_fx_info)
if auto_fx_error:
    st.warning(auto_fx_error)
trade_note = st.text_input("메모", value="", key="manual_trade_note")
submitted_trade = st.button("거래 저장", key="manual_trade_submit")

if submitted_trade:
    try:
        if manual_candidate:
            trade_ticker = manual_candidate.ticker
        else:
            trade_ticker = normalize_ticker(manual_ticker)
        if not trade_ticker:
            raise ValueError("자동완성에서 종목을 선택하거나 직접 입력해 주세요.")
        if trade_quantity <= 0 or trade_price <= 0:
            raise ValueError("수량과 단가는 0보다 커야 합니다.")
        trade_currency_norm = trade_currency or "KRW"
        trade_fx_value = trade_fx or 0.0
        if trade_currency_norm != "KRW":
            if trade_fx_value <= 0:
                raise ValueError("외화 거래는 환율(양수)을 입력해 주세요.")
        else:
            trade_fx_value = 1.0
        side_enum = TradeSide(trade_side)
        with db_session() as session:
            if side_enum == TradeSide.SELL:
                positions = get_positions(session, account_type=AccountType(trade_account), tickers=[trade_ticker])
                qty_available = positions[0].quantity if positions else 0.0
                if qty_available < trade_quantity - 1e-8:
                    raise ValueError(f"보유 수량({qty_available:,.4f})보다 많은 매도를 입력했습니다.")
            record_trade(
                session,
                trade_date=trade_date,
                ticker=trade_ticker,
                account_type=AccountType(trade_account),
                side=side_enum,
                quantity=trade_quantity,
                price=trade_price,
                currency=trade_currency_norm,
                fx_rate=trade_fx_value if trade_currency_norm != "KRW" else 1.0,
                note=trade_note or None,
                source="manual",
            )
        st.success("거래가 저장되었습니다.")
    except Exception as exc:
        st.error(f"거래 저장 실패: {exc}")

st.divider()
st.header("보유 포지션 기본값 수정")
st.write(
    "초기 CSV 업로드 때 입력한 수량/평균 매입가가 잘못되었다면 여기에서 바로 수정할 수 있습니다. "
    "이 값은 이후 추가 매수/매도 거래 전에 가지고 있던 기준 수량으로 사용되며, 아래 수동 거래 내역은 그대로 유지됩니다."
)

with db_session() as session:
    base_positions = (
        session.execute(
            select(HoldingPosition, TickerMaster.name_ko)
            .join(
                TickerMaster,
                TickerMaster.ticker == HoldingPosition.ticker,
                isouter=True,
            )
            .order_by(HoldingPosition.account_type, HoldingPosition.ticker)
        ).all()
    )

if not base_positions:
    st.info("수정할 기본 포지션이 없습니다. 먼저 CSV를 업로드하거나 거래를 입력해 포지션을 만들어 주세요.")
else:
    position_options = [
        {
            "key": f"{pos.account_type.value}:{pos.ticker}",
            "label": f"[{pos.account_type.value}] {pos.ticker}"
            + (f" ({name})" if name else ""),
            "account": pos.account_type,
            "ticker": pos.ticker,
            "quantity": float(pos.quantity),
            "avg": float(pos.avg_buy_price_krw),
            "note": pos.note or "",
        }
        for pos, name in base_positions
    ]
    selected_idx = st.selectbox(
        "수정할 기본 포지션 선택",
        options=list(range(len(position_options))),
        format_func=lambda idx: position_options[idx]["label"],
    )
    selected = position_options[selected_idx]
    if st.session_state.get("_position_edit_choice") != selected["key"]:
        st.session_state["_position_edit_choice"] = selected["key"]
        st.session_state["position_edit_qty"] = selected["quantity"]
        st.session_state["position_edit_avg"] = selected["avg"]
        st.session_state["position_edit_note"] = selected["note"]

    edit_qty = st.number_input(
        "기본 수량",
        min_value=0.0,
        step=1.0,
        format="%.4f",
        key="position_edit_qty",
    )
    edit_avg = st.number_input(
        "기본 평균 매입가 (KRW)",
        min_value=0.0,
        step=10.0,
        format="%.4f",
        key="position_edit_avg",
    )
    edit_note = st.text_input("비고(선택)", key="position_edit_note")
    st.caption("수정된 수량과 평균 단가는 해당 계좌/티커의 초기 기준치로 저장됩니다.")

    if st.button("기본 포지션 업데이트", use_container_width=True):
        try:
            with db_session() as session:
                position = session.execute(
                    select(HoldingPosition).where(
                        HoldingPosition.ticker == selected["ticker"],
                        HoldingPosition.account_type == selected["account"],
                    )
                ).scalar_one_or_none()
                if not position:
                    raise ValueError("선택한 포지션을 다시 불러올 수 없습니다.")
                position.quantity = edit_qty
                position.avg_buy_price_krw = edit_avg
                position.total_cost_krw = edit_qty * edit_avg
                position.note = edit_note or None
            st.success("기본 포지션을 업데이트했습니다. 아래 미리보기에서 확인해 주세요.")
        except Exception as exc:
            st.error(f"포지션 업데이트 실패: {exc}")

st.divider()
if not (has_any_positions or has_any_lots):
    st.info("보유 데이터가 없어 CSV 기반 초기 업로드가 필요합니다.")
    _render_csv_importers()
else:
    with st.expander("CSV 업로드 (초기 세팅/재업로드 시 펼치세요)", expanded=False):
        st.caption("이미 거래/포지션이 있다면 중복 입력에 주의해 주세요.")
        _render_csv_importers()
