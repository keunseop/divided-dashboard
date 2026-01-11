import streamlit as st
import pandas as pd
from sqlalchemy import select

from core.cash_service import (
    list_cash_snapshots,
    upsert_cash_snapshot,
)
from core.db import db_session
from core.models import DividendEvent, AccountType, TickerMaster
from core.user_gate import require_user
from core.valuation_service import (
    calculate_position_valuations,
    get_valuation_history,
    summarize_valuations,
    upsert_valuation_snapshots,
)


require_user()
st.title("대시보드")
st.caption("배당 현황, 계좌별 지표, 포트폴리오 평가 추이를 한눈에 확인합니다.")

filter_col, account_col = st.columns([3, 1.5])
with filter_col:
    metric = st.selectbox(
        "기준",
        ["KRW 세전(krwGross)", "KRW 세후(krwNet)"],
        key="dashboard_metric",
    )

account_options = ["ALL"] + [acct.value for acct in AccountType if acct != AccountType.ALL]
with account_col:
    account_filter = st.selectbox(
        "계좌",
        account_options,
        key="dashboard_account",
        help="필요 시 계좌 유형별로 배당 현황을 제한할 수 있습니다.",
    )

col = "krw_gross" if metric.startswith("KRW 세전") else "krw_net"

with db_session() as s:
    q = (
        select(
            DividendEvent.pay_date,
            DividendEvent.year,
            DividendEvent.month,
            DividendEvent.ticker,
            getattr(DividendEvent, col).label("value"),
        ).where(DividendEvent.archived == False)
    )  # noqa: E712

    if account_filter != "ALL":
        q = q.where(DividendEvent.account_type == AccountType(account_filter))

    rows = s.execute(q).all()
    ticker_name_map = dict(
        s.execute(select(TickerMaster.ticker, TickerMaster.name_ko)).all()
    )

if not rows:
    st.info("데이터가 없습니다. 먼저 CSV Import를 해주세요.")
    st.stop()


def fmt_krw(x):
    return "N/A" if x is None else f"{x:,.0f}원"


df = pd.DataFrame(rows, columns=["payDate", "year", "month", "ticker", "value"])
df = df.dropna(subset=["value"])
df["payDate"] = pd.to_datetime(df["payDate"])

this_year = pd.Timestamp.today().year
ytd = df[df["year"] == this_year]["value"].sum()
prev_year = df[df["year"] == this_year - 1]["value"].sum()
yoy = (ytd / prev_year - 1) * 100 if prev_year > 0 else None

c1, c2, c3 = st.columns(3)
c1.metric("올해 누적", fmt_krw(ytd))
c2.metric("작년 총액", fmt_krw(prev_year))
c3.metric("YoY(참고)", f"{yoy:,.1f}%" if yoy is not None else "N/A")

st.divider()

yearly = df.groupby("year", as_index=False)["value"].sum().sort_values("year")
st.subheader("연도별 배당 추이")
st.bar_chart(yearly, x="year", y="value")

df["ym"] = df["payDate"].dt.to_period("M").astype(str)
monthly = df.groupby("ym", as_index=False)["value"].sum().sort_values("ym")
st.subheader("월별 배당 추이")
st.line_chart(monthly, x="ym", y="value")

st.subheader("종목 TOP 15")
top_col1, top_col2 = st.columns([2, 1])
years_available = sorted(df["year"].dropna().unique().tolist())
year_options = ["전체"] + [str(int(y)) for y in years_available]
with top_col1:
    selected_year_label = st.selectbox(
        "연도 선택",
        options=year_options,
        help="특정 연도를 선택하면 해당 연도의 Top 15만 집계합니다.",
    )
selected_year = None if selected_year_label == "전체" else int(selected_year_label)
with top_col2:
    show_yearly_summary = st.checkbox("연도별 요약 보기", value=False)

top_source = df if selected_year is None else df[df["year"] == selected_year]

top = (
    top_source.groupby("ticker", as_index=False)["value"]
    .sum()
    .sort_values("value", ascending=False)
    .head(15)
)
top["name_ko"] = top["ticker"].map(lambda t: ticker_name_map.get(t, "미등록"))

if selected_year is not None:
    prev_year = selected_year - 1
    prev_map = (
        df[df["year"] == prev_year]
        .groupby("ticker", as_index=False)["value"]
        .sum()
        .set_index("ticker")["value"]
        .to_dict()
    )

    def _calc_yoy(row):
        prev_val = prev_map.get(row["ticker"])
        if not prev_val:
            return None
        if prev_val == 0:
            return None
        return row["value"] / prev_val - 1

    top["yoy"] = top.apply(_calc_yoy, axis=1)
else:
    top["yoy"] = None

top_display = top[["ticker", "name_ko", "value", "yoy"]].copy()
top_display["value"] = top_display["value"].map(lambda v: f"{v:,.0f}원")
if selected_year is not None:
    top_display["yoy"] = top_display["yoy"].map(lambda v: f"{v*100:,.1f}%" if v is not None else "N/A")
else:
    top_display = top_display.drop(columns=["yoy"])
st.dataframe(top_display, use_container_width=True)

if show_yearly_summary:
    yearly_rows = []
    for year in sorted(years_available):
        yearly_df = (
            df[df["year"] == year]
            .groupby("ticker", as_index=False)["value"]
            .sum()
            .sort_values("value", ascending=False)
            .head(15)
        )
        for rank, row in enumerate(yearly_df.itertuples(index=False), start=1):
            yearly_rows.append(
                {
                    "Year": int(year),
                    "Rank": rank,
                    "Ticker": row.ticker,
                    "Name": ticker_name_map.get(row.ticker, "미등록"),
                    "Value (KRW)": row.value,
                }
            )
    if yearly_rows:
        summary_df = pd.DataFrame(yearly_rows)
        summary_df["Value (KRW)"] = summary_df["Value (KRW)"].map(lambda v: f"{v:,.0f}원")
        st.dataframe(
            summary_df,
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("연도별 요약을 표시할 데이터가 없습니다.")

st.divider()
st.subheader("보유 포지션 현재가 및 평가손익")
st.caption("계좌 필터가 적용됩니다. 가격은 KR 종목 스냅샷/price_cache 또는 yfinance를 사용하며 6시간 캐시를 활용합니다.")
force_price_refresh = st.checkbox(
    "가격 강제 재조회",
    value=False,
    help="체크하면 price_cache를 무시하고 외부 데이터 소스를 다시 호출합니다.",
)

cash_snapshots = []
latest_cash_snapshot = None
with st.spinner("보유 종목의 현재가를 계산하는 중입니다..."):
    with db_session() as session:
        valuations, valuation_errors = calculate_position_valuations(
            session,
            force_refresh=force_price_refresh,
        )
        history_account = AccountType.ALL if account_filter == "ALL" else AccountType(account_filter)
        history_entries = get_valuation_history(session, history_account, limit=180)
        cash_snapshots = list_cash_snapshots(session, account_type=history_account, limit=365)
        latest_cash_snapshot = cash_snapshots[-1] if cash_snapshots else None

summaries = summarize_valuations(valuations)
selected_account = None if account_filter == "ALL" else AccountType(account_filter)
summary_key = AccountType.ALL if selected_account is None else selected_account
summary = summaries.get(summary_key)

if summary and summary.positions_count > 0:
    metric_cols = st.columns(3)
    metric_cols[0].metric("총 투자원금", f"{summary.total_cost_krw:,.0f}원")
    metric_cols[1].metric("현재 평가액", f"{summary.market_value_krw:,.0f}원")
    delta_display = (
        f"{summary.gain_loss_pct:,.2f}%" if summary.gain_loss_pct is not None else "N/A"
    )
    metric_cols[2].metric(
        "평가손익",
        f"{summary.gain_loss_krw:,.0f}원",
        delta=delta_display,
    )
else:
    st.info("표시할 포지션이 없거나 가격 정보를 가져올 수 없습니다.")

cash_cols = st.columns([2, 1])
with cash_cols[0]:
    if latest_cash_snapshot:
        cash_value = latest_cash_snapshot.cash_krw
        metric_row = st.columns(3)
        metric_row[0].metric("현금 (KRW)", f"{cash_value:,.0f}원")
        if summary and summary.positions_count > 0:
            metric_row[1].metric("총자산 (원가+현금)", f"{(summary.total_cost_krw + cash_value):,.0f}원")
            metric_row[2].metric("총자산 (평가+현금)", f"{(summary.market_value_krw + cash_value):,.0f}원")
        else:
            metric_row[1].metric("총자산 (원가+현금)", "데이터 없음")
            metric_row[2].metric("총자산 (평가+현금)", "데이터 없음")
            st.info("평가 데이터가 없어 총자산 계산에 현금만 표시됩니다.")
    else:
        st.warning("현금 스냅샷이 없습니다. 현금을 입력해 총자산을 함께 추적하세요.")
with cash_cols[1]:
    st.write("현금 입력/업데이트")
    default_cash_value = latest_cash_snapshot.cash_krw if latest_cash_snapshot else 0.0
    with st.form("cash_snapshot_form"):
        cash_date = st.date_input("기준일", value=pd.Timestamp.today().date())
        cash_amount = st.number_input(
            "현금 (KRW)",
            min_value=0.0,
            value=float(default_cash_value),
            step=100000.0,
        )
        cash_note = st.text_input("메모", value="")
        submitted_cash = st.form_submit_button("저장")
    if submitted_cash:
        try:
            with db_session() as session:
                upsert_cash_snapshot(
                    session,
                    snapshot_date=cash_date,
                    account_type=history_account,
                    cash_krw=cash_amount,
                    note=cash_note or None,
                )
            st.success("현금 스냅샷이 저장되었습니다.")
        except Exception as exc:
            st.error(f"현금 저장 실패: {exc}")

missing_prices = [
    f"{val.ticker} ({val.account_type.value})"
    for val in valuations
    if val.market_value_krw is None
]
if missing_prices:
    st.warning(
        "가격 데이터가 없어 평가에서 제외된 종목: "
        + ", ".join(missing_prices[:10])
        + ("..." if len(missing_prices) > 10 else ""),
    )
if valuation_errors:
    st.error("가격 계산 중 오류: " + "; ".join(valuation_errors))

display_valuations = [
    val for val in valuations if selected_account is None or val.account_type == selected_account
]

if display_valuations:
    df = pd.DataFrame(
        [
            {
                "Symbol": f"{val.ticker} ({val.name_ko})" if val.name_ko else val.ticker,
                "Account": val.account_type.value,
                "Quantity": val.quantity,
                "Avg Buy Price (KRW)": val.avg_buy_price_krw,
                "Total Cost (KRW)": val.total_cost_krw,
                "Realized PnL (KRW)": val.realized_pnl_krw,
                "Price": val.price,
                "Currency": val.price_currency,
                "Price (KRW)": val.price_krw,
                "Market Value (KRW)": val.market_value_krw,
                "Gain/Loss (KRW)": val.gain_loss_krw,
                "Gain/Loss %": val.gain_loss_pct,
                "Price As Of": val.price_as_of,
                "Source": val.price_source,
            }
            for val in display_valuations
        ]
    )

    def _gain_style(value):
        if pd.isna(value):
            return ""
        if value > 0:
            return "color: #d90429;"
        if value < 0:
            return "color: #0057d9;"
        return ""

    formatters = {
        "Quantity": "{:,.4f}",
        "Avg Buy Price (KRW)": "{:,.0f}",
        "Total Cost (KRW)": "{:,.0f}",
        "Realized PnL (KRW)": "{:,.0f}",
        "Price": "{:,.2f}",
        "Price (KRW)": "{:,.0f}",
        "Market Value (KRW)": "{:,.0f}",
        "Gain/Loss (KRW)": "{:,.0f}",
        "Gain/Loss %": "{:,.2f}%",
    }
    styled = (
        df.style.format(formatters, na_rep="-")
        .applymap(_gain_style, subset=["Gain/Loss %"])
        .hide(axis="index")
    )
    st.dataframe(styled, use_container_width=True)
else:
    st.info("선택한 계좌에 표시할 포지션이 없습니다.")

summary_all = summaries.get(AccountType.ALL)
if summary_all and summary_all.positions_count > 0:
    if st.button("오늘 평가액 기록 저장", help="현재 계산된 평가액 합계를 holding_valuation_snapshots 테이블에 저장합니다."):
        with db_session() as session:
            result = upsert_valuation_snapshots(session, summaries)
        st.success(f"평가액 저장 완료 (inserted {result.inserted}, updated {result.updated})")

st.subheader("평가액/현금 추이")
history_label = "전체" if history_account == AccountType.ALL else history_account.value
history_df = pd.DataFrame(
    [
        {
            "valuation_date": entry.valuation_date,
            "market_value_krw": entry.market_value_krw,
            "total_cost_krw": entry.total_cost_krw,
            "gain_loss_krw": entry.gain_loss_krw,
        }
        for entry in history_entries
    ]
) if history_entries else pd.DataFrame(columns=["valuation_date", "market_value_krw", "total_cost_krw", "gain_loss_krw"])
cash_history_df = pd.DataFrame(
    [
        {
            "valuation_date": snapshot.snapshot_date,
            "cash_krw": snapshot.cash_krw,
        }
        for snapshot in cash_snapshots
    ]
) if cash_snapshots else pd.DataFrame(columns=["valuation_date", "cash_krw"])

if not history_df.empty or not cash_history_df.empty:
    merged = pd.merge(history_df, cash_history_df, on="valuation_date", how="outer").sort_values("valuation_date")
    merged["cash_krw"] = merged["cash_krw"].ffill().fillna(0.0)
    merged["total_cost_krw"] = merged["total_cost_krw"].ffill().fillna(0.0)
    merged["market_value_krw"] = merged["market_value_krw"].ffill().fillna(0.0)
    merged["asset_cost_with_cash"] = merged["total_cost_krw"] + merged["cash_krw"]
    merged["asset_market_with_cash"] = merged["market_value_krw"] + merged["cash_krw"]
    st.caption(f"{history_label} 계좌 기준 평가/현금 추이 (최근 {len(merged)}포인트)")
    st.line_chart(
        merged,
        x="valuation_date",
        y=["total_cost_krw", "market_value_krw", "cash_krw", "asset_market_with_cash"],
    )
else:
    st.info(f"{history_label} 계좌에 저장된 평가 또는 현금 기록이 없습니다.")
