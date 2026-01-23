from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st
from sqlalchemy import func, select

from core.db import db_session
from core.holdings_service import get_positions
from core.models import AccountType, DividendEvent, TickerMaster
from core.user_gate import require_user


def _format_number(value: float | None, digits: int = 0) -> str:
    if value is None or pd.isna(value):
        return ""
    return f"{value:,.{digits}f}"


def _load_monthly_dividends(
    *,
    tickers: list[str],
    account_type: AccountType | None,
) -> pd.DataFrame:
    if not tickers:
        return pd.DataFrame()

    with db_session() as session:
        stmt = (
            select(
                DividendEvent.ticker,
                TickerMaster.name_ko,
                DividendEvent.currency,
                DividendEvent.year,
                DividendEvent.month,
                func.sum(DividendEvent.gross_dividend).label("gross_dividend"),
                func.sum(DividendEvent.net_dividend).label("net_dividend"),
                func.sum(DividendEvent.krw_gross).label("krw_gross"),
                func.sum(DividendEvent.krw_net).label("krw_net"),
                func.count(DividendEvent.id).label("event_count"),
            )
            .join(TickerMaster, TickerMaster.ticker == DividendEvent.ticker, isouter=True)
            .where(DividendEvent.archived == False)
            .where(DividendEvent.ticker.in_(tickers))
            .group_by(
                DividendEvent.ticker,
                TickerMaster.name_ko,
                DividendEvent.currency,
                DividendEvent.year,
                DividendEvent.month,
            )
        )

        if account_type is not None:
            stmt = stmt.where(DividendEvent.account_type == account_type)

        rows = session.execute(stmt).all()

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(
        rows,
        columns=[
            "ticker",
            "name_ko",
            "currency",
            "year",
            "month",
            "gross_dividend",
            "net_dividend",
            "krw_gross",
            "krw_net",
            "event_count",
        ],
    )
    df["month_start"] = pd.to_datetime(
        df["year"].astype(str) + "-" + df["month"].astype(str).str.zfill(2) + "-01"
    )
    df["month_label"] = df["month_start"].dt.strftime("%Y-%m")
    df["display_amount"] = df["krw_gross"].fillna(df["krw_net"])
    df["display_currency"] = "KRW"
    return df


require_user()
st.title("보유 종목 배당 추이")
st.caption("현재 보유 중인 배당 종목의 로컬 DB 배당 히스토리를 월별로 정리해 보여줍니다.")

account_labels = {
    "전체": None,
    "일반": AccountType.TAXABLE,
    "ISA": AccountType.ISA,
}
account_label = st.selectbox("계좌 구분", options=list(account_labels.keys()), index=0)
account_filter = account_labels[account_label]

with db_session() as session:
    positions = get_positions(
        session,
        account_type=account_filter if account_filter is not None else None,
    )

if not positions:
    st.info("현재 보유 종목이 없습니다. 포트폴리오 관리에서 보유 종목을 먼저 등록해 주세요.")
    st.stop()

held_tickers = sorted({pos.ticker for pos in positions})
st.caption(f"보유 종목 {len(held_tickers)}개 기준으로 배당 내역을 조회합니다.")

monthly_df = _load_monthly_dividends(
    tickers=held_tickers,
    account_type=account_filter,
)

if monthly_df.empty:
    st.warning("보유 종목에 대한 배당 내역이 없습니다. 배당 내역 가져오기를 먼저 진행해 주세요.")
    st.stop()

if monthly_df["display_amount"].isna().all():
    st.warning("KRW로 환산된 배당 내역이 없습니다. 환율/원화 필드를 채운 뒤 다시 확인해 주세요.")
    st.stop()

missing_tickers = sorted(set(held_tickers) - set(monthly_df["ticker"].unique()))
if missing_tickers:
    st.info(f"배당 내역이 없는 보유 종목: {', '.join(missing_tickers)}")

st.subheader("월별 배당 내역")
latest_first = st.toggle("최신순 정렬", value=True)
sort_ascending = not latest_first
monthly_df = monthly_df.sort_values(
    by=["month_start", "ticker"],
    ascending=[sort_ascending, True],
)

display_df = monthly_df[
    [
        "month_label",
        "ticker",
        "name_ko",
        "display_currency",
        "gross_dividend",
        "net_dividend",
        "krw_gross",
        "krw_net",
        "event_count",
    ]
].copy()
display_df = display_df.rename(
    columns={
        "month_label": "월",
        "ticker": "티커",
        "name_ko": "종목명",
        "display_currency": "표시통화",
        "gross_dividend": "세전(원통화)",
        "net_dividend": "세후(원통화)",
        "krw_gross": "세전(KRW)",
        "krw_net": "세후(KRW)",
        "event_count": "건수",
    }
)
display_df["세전(원통화)"] = display_df["세전(원통화)"].apply(_format_number)
display_df["세후(원통화)"] = display_df["세후(원통화)"].apply(_format_number)
display_df["세전(KRW)"] = display_df["세전(KRW)"].apply(lambda v: _format_number(v, 0))
display_df["세후(KRW)"] = display_df["세후(KRW)"].apply(lambda v: _format_number(v, 0))

st.dataframe(display_df, use_container_width=True, hide_index=True)

st.subheader("연도별 월간 배당 매트릭스")
year_options = sorted(monthly_df["year"].unique(), reverse=True)
default_year = year_options[0] if year_options else None
selected_year = st.selectbox("조회 연도", options=year_options, index=0 if default_year else None)

year_df = monthly_df[monthly_df["year"] == selected_year].copy()
if year_df.empty:
    st.info("선택한 연도에 해당하는 배당 내역이 없습니다.")
    st.stop()

year_df["row_label"] = year_df["ticker"] + " " + year_df["name_ko"].fillna("")
matrix_df = (
    year_df.pivot_table(
        index="row_label",
        columns="month",
        values="display_amount",
        aggfunc="sum",
    )
    .reindex(columns=list(range(1, 13)))
    .fillna(0.0)
)

matrix_df.columns = [f"{month}월" for month in matrix_df.columns]
matrix_df = matrix_df.reset_index().rename(columns={"row_label": "종목"})

matrix_numeric = matrix_df.drop(columns=["종목"]).apply(pd.to_numeric, errors="coerce").fillna(0.0)
matrix_df["합계"] = matrix_numeric.sum(axis=1)
total_row = pd.DataFrame(
    [["합계"] + matrix_numeric.sum(axis=0).tolist() + [matrix_numeric.values.sum()]],
    columns=["종목"] + list(matrix_numeric.columns) + ["합계"],
)
matrix_df = pd.concat([matrix_df, total_row], ignore_index=True)

for col in matrix_df.columns:
    if col != "종목":
        matrix_df[col] = matrix_df[col].apply(lambda v: _format_number(v, 0) if v else "")

def _highlight_total_row(row: pd.Series) -> list[str]:
    if row.get("종목") == "합계":
        return ["font-weight: bold"] * len(row)
    return [""] * len(row)

styled_df = matrix_df.style.apply(_highlight_total_row, axis=1)
st.dataframe(styled_df, use_container_width=True, hide_index=True, height=620)
