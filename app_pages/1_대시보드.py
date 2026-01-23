import altair as alt
import streamlit as st
import pandas as pd
from sqlalchemy import select

from core.cash_service import (
    list_cash_snapshots,
)
from core.db import db_session
from core.models import DividendEvent, AccountType, TickerMaster
from core.ticker_resolver import resolve_missing_ticker_names
from core.user_gate import require_user
from core.utils import infer_market_from_ticker, normalize_market_code
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
    tickers = {row.ticker for row in rows if row.ticker}
    if tickers:
        resolve_missing_ticker_names(s, tickers)
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
c3.metric("YoY(참고)", f"{yoy:,.2f}%" if yoy is not None else "N/A")

st.divider()

yearly = df.groupby("year", as_index=False)["value"].sum().sort_values("year")
st.subheader("연도별 배당 추이")
yearly_chart = alt.Chart(yearly).mark_bar().encode(
    x=alt.X("year:O", title="연도", sort=None),
    y=alt.Y("value:Q", title="배당금", axis=alt.Axis(format=",.0f")),
    tooltip=[
        alt.Tooltip("year:O", title="연도"),
        alt.Tooltip("value:Q", title="배당금", format=",.0f"),
    ],
)
st.altair_chart(yearly_chart, use_container_width=True)

df["ym"] = df["payDate"].dt.to_period("M").astype(str)
monthly = df.groupby("ym", as_index=False)["value"].sum().sort_values("ym")
st.subheader("월별 배당 추이")
monthly_chart = alt.Chart(monthly).mark_line(point=True).encode(
    x=alt.X("ym:O", title="월", sort=None),
    y=alt.Y("value:Q", title="배당금", axis=alt.Axis(format=",.0f")),
    tooltip=[
        alt.Tooltip("ym:O", title="월"),
        alt.Tooltip("value:Q", title="배당금", format=",.0f"),
    ],
)
st.altair_chart(monthly_chart, use_container_width=True)

st.subheader("종목 TOP 10")
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
    .head(10)
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

top_pie = top[["ticker", "name_ko", "value"]].copy()
top_pie["label"] = top_pie["name_ko"] + " (" + top_pie["ticker"] + ")"
top_total = top_source["value"].sum()
top_pie_total = top_pie["value"].sum()
others_value = max(top_total - top_pie_total, 0)
if others_value > 0:
    top_pie = pd.concat(
        [
            top_pie,
            pd.DataFrame(
                [
                    {
                        "ticker": "OTHERS",
                        "name_ko": "기타",
                        "value": others_value,
                        "label": "기타",
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
if top_pie.empty or top_total <= 0:
    st.info("표시할 배당 데이터가 없습니다.")
else:
    top_pie["pct"] = top_pie["value"] / top_total
    top_pie_chart = alt.Chart(top_pie).mark_arc(innerRadius=40, thetaOffset=-1.5708).encode(
        theta=alt.Theta("value:Q", stack=True, sort="descending"),
        color=alt.Color("label:N", title=""),
        order=alt.Order("value:Q", sort="descending"),
        tooltip=[
            alt.Tooltip("label:N", title="종목"),
            alt.Tooltip("value:Q", title="배당금", format=",.0f"),
            alt.Tooltip("pct:Q", title="비중", format=".1%"),
        ],
    )
    st.altair_chart(top_pie_chart, use_container_width=True)

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
    delta_display = (
        f"{summary.gain_loss_pct:,.2f}%" if summary.gain_loss_pct is not None else "N/A"
    )
else:
    st.info("표시할 포지션이 없거나 가격 정보를 가져올 수 없습니다.")

cash_cols = st.columns([3, 1])
with cash_cols[0]:
    if latest_cash_snapshot:
        cash_value = latest_cash_snapshot.cash_krw
        if summary and summary.positions_count > 0:
            total_asset_value = summary.market_value_krw + cash_value
        else:
            total_asset_value = None
            st.info("평가 데이터가 없어 총자산 계산에 현금만 표시됩니다.")
    else:
        st.warning("현금 스냅샷이 없습니다. 현금을 입력해 총자산을 함께 추적하세요.")
        cash_value = None
        total_asset_value = None
with cash_cols[1]:
    st.caption("현금 입력/입출금은 포트폴리오 관리에서 진행해 주세요.")

if summary and summary.positions_count > 0:
    metrics_table = pd.DataFrame(
        [
            {
                "총 투자원금": summary.total_cost_krw,
                "현재 평가액": summary.market_value_krw,
                "평가손익": summary.gain_loss_krw,
                "수익률": summary.gain_loss_pct,
                "현금": cash_value,
                "총 자산": total_asset_value,
            }
        ]
    )

    def _gain_style_value(value):
        if pd.isna(value):
            return ""
        if value > 0:
            return "color: #d90429; font-weight: 600;"
        if value < 0:
            return "color: #0057d9; font-weight: 600;"
        return ""

    metrics_styled = (
        metrics_table.style.format(
            {
                "총 투자원금": "{:,.0f}원",
                "현재 평가액": "{:,.0f}원",
                "평가손익": "{:,.0f}원",
                "수익률": "{:,.2f}%",
                "현금": "{:,.0f}원",
                "총 자산": "{:,.0f}원",
            },
            na_rep="N/A",
        )
        .applymap(_gain_style_value, subset=["평가손익", "수익률"])
        .hide(axis="index")
    )
    st.dataframe(metrics_styled, use_container_width=True)

asset_pie_data = []
cash_value = 0.0
if latest_cash_snapshot:
    cash_value = latest_cash_snapshot.cash_krw
if summary and summary.positions_count > 0:
    display_valuations = [
        val for val in valuations if selected_account is None or val.account_type == selected_account
    ]
    market_rows = [
        {
            "label": f"{val.ticker} ({val.name_ko})" if val.name_ko else val.ticker,
            "value": val.market_value_krw,
        }
        for val in display_valuations
        if val.market_value_krw is not None and val.market_value_krw > 0
    ]
    if market_rows or cash_value > 0:
        asset_pie_data = market_rows + ([{"label": "현금", "value": cash_value}] if cash_value > 0 else [])
        asset_total = sum(item["value"] for item in asset_pie_data)
        if asset_total > 0:
            asset_df = pd.DataFrame(asset_pie_data)
            asset_df["pct"] = asset_df["value"] / asset_total
            legend_title = f"보유 종목 ({len(market_rows)}종)"
            asset_chart = alt.Chart(asset_df).mark_arc(innerRadius=40, thetaOffset=-1.5708).encode(
                theta=alt.Theta("value:Q", stack=True, sort="descending"),
                color=alt.Color(
                    "label:N",
                    title=legend_title,
                    legend=alt.Legend(columns=2, orient="right"),
                ),
                order=alt.Order("value:Q", sort="descending"),
                tooltip=[
                    alt.Tooltip("label:N", title="자산"),
                    alt.Tooltip("value:Q", title="금액", format=",.0f"),
                    alt.Tooltip("pct:Q", title="비중", format=".1%"),
                ],
            ).properties(height=420, width=520)
            st.altair_chart(asset_chart, use_container_width=True)
        else:
            st.info("총자산이 0원이어서 비율 차트를 표시할 수 없습니다.")

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
    st.subheader("국내/해외 주식 비중")
    ticker_markets: dict[str, str | None] = {}
    tickers = {val.ticker for val in display_valuations if val.ticker}
    if tickers:
        with db_session() as session:
            rows = session.execute(
                select(TickerMaster.ticker, TickerMaster.market).where(
                    TickerMaster.ticker.in_(tickers)
                )
            ).all()
            ticker_markets = {row.ticker: row.market for row in rows}

    market_groups = []
    total_value = 0.0
    for val in display_valuations:
        if val.market_value_krw is None or val.market_value_krw <= 0:
            continue
        declared_market = ticker_markets.get(val.ticker)
        market_code = infer_market_from_ticker(val.ticker, normalize_market_code(declared_market))
        group = "국내" if market_code == "KR" else "해외"
        market_groups.append((group, val.ticker, val.market_value_krw))
        total_value += val.market_value_krw

    if market_groups and total_value > 0:
        group_df = pd.DataFrame(market_groups, columns=["구분", "티커", "평가액"])
        summary_df = (
            group_df.groupby("구분", as_index=False)
            .agg(종목수=("티커", "nunique"), 평가액=("평가액", "sum"))
        )
        summary_df["비중"] = summary_df["평가액"] / total_value

        pie = alt.Chart(summary_df).mark_arc(innerRadius=40, thetaOffset=-1.5708).encode(
            theta=alt.Theta("평가액:Q", stack=True, sort="descending"),
            color=alt.Color("구분:N", title="구분"),
            order=alt.Order("평가액:Q", sort="descending"),
            tooltip=[
                alt.Tooltip("구분:N", title="구분"),
                alt.Tooltip("평가액:Q", title="평가액", format=",.0f"),
                alt.Tooltip("비중:Q", title="비중", format=".1%"),
                alt.Tooltip("종목수:Q", title="종목 수"),
            ],
        ).properties(height=360)
        st.altair_chart(pie, use_container_width=True)

        summary_df["평가액"] = summary_df["평가액"].map(lambda v: f"{v:,.0f}원")
        summary_df["비중"] = summary_df["비중"].map(lambda v: f"{v:.1%}")
        st.dataframe(summary_df, use_container_width=True, hide_index=True)
    else:
        st.info("국내/해외 비중을 계산할 평가 데이터가 없습니다.")

if display_valuations:
    df = pd.DataFrame(
        [
            {
                "종목": f"{val.ticker} ({val.name_ko})" if val.name_ko else val.ticker,
                "계좌": val.account_type.value,
                "수량": val.quantity,
                "평균단가(KRW)": val.avg_buy_price_krw,
                "총투자원금(KRW)": val.total_cost_krw,
                "실현손익(KRW)": val.realized_pnl_krw,
                "현재가": val.price,
                "통화": val.price_currency,
                "현재가(KRW)": val.price_krw,
                "평가액(KRW)": val.market_value_krw,
                "평가손익(KRW)": val.gain_loss_krw,
                "평가손익%": val.gain_loss_pct,
                "가격기준시각": val.price_as_of,
                "소스": val.price_source,
            }
            for val in display_valuations
        ]
    )
    df = df.sort_values(by="평가손익%", ascending=False, na_position="last")

    def _gain_style(value):
        if pd.isna(value):
            return ""
        if value > 0:
            return "color: #d90429;"
        if value < 0:
            return "color: #0057d9;"
        return ""

    formatters = {
        "수량": "{:,.0f}",
        "평균단가(KRW)": "{:,.0f}",
        "총투자원금(KRW)": "{:,.0f}",
        "실현손익(KRW)": "{:,.0f}",
        "현재가": "{:,.0f}",
        "현재가(KRW)": "{:,.0f}",
        "평가액(KRW)": "{:,.0f}",
        "평가손익(KRW)": "{:,.0f}",
        "평가손익%": "{:,.2f}%",
    }
    styled = (
        df.style.format(formatters, na_rep="-")
        .applymap(_gain_style, subset=["평가손익(KRW)", "평가손익%"])
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

st.subheader("총 자산 추이")
history_label = "전체" if history_account == AccountType.ALL else history_account.value
history_df = pd.DataFrame(
    [
        {
            "valuation_date": entry.valuation_date,
            "market_value_krw": entry.market_value_krw,
        }
        for entry in history_entries
    ]
) if history_entries else pd.DataFrame(columns=["valuation_date", "market_value_krw"])
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
    merged["market_value_krw"] = merged["market_value_krw"].ffill().fillna(0.0)
    merged["asset_market_with_cash"] = merged["market_value_krw"] + merged["cash_krw"]
    st.caption(f"{history_label} 계좌 기준 총 자산 추이 (최근 {len(merged)}포인트)")
    history_chart = alt.Chart(merged).mark_line().encode(
        x=alt.X("valuation_date:T", title="날짜"),
        y=alt.Y("asset_market_with_cash:Q", title="총 자산", axis=alt.Axis(format=",.0f")),
        tooltip=[
            alt.Tooltip("valuation_date:T", title="날짜"),
            alt.Tooltip("asset_market_with_cash:Q", title="총 자산", format=",.0f"),
        ],
    )
    st.altair_chart(history_chart, use_container_width=True)
else:
    st.info(f"{history_label} 계좌에 저장된 평가 또는 현금 기록이 없습니다.")
