import pandas as pd
import streamlit as st
from datetime import date
from sqlalchemy import select

from core.alimtalk_parser import (
    AlimtalkImportPayload,
    parse_messages,
    build_row_id,
    upsert_alimtalk_events,
)
from core.db import db_session
from core.fx import fetch_fx_rate_frankfurter
from core.models import AccountType, TickerMaster
from core.utils import normalize_ticker

ACCOUNT_OPTIONS = [acct.value for acct in AccountType if acct != AccountType.ALL]

st.title("알림톡 파서")

st.markdown(
    """
알림톡 원문을 붙여넣고 `파싱` 버튼을 누르면 자동으로 금액/통화 정보를 추출합니다.

- 국내 알림톡은 월/일 정보만 있으므로 **기본 연도**를 지정해 주세요.
- 해외 알림톡은 날짜 자체가 없으므로 **기본 지급일**을 반드시 확인/수정하세요.
- 환율은 수동 입력이 기본이며, 필요 시 `환율 자동 조회` 버튼으로 [exchangerate.host](https://exchangerate.host/) 기준 환율을 불러옵니다.
"""
)

if "alimtalk_rows" not in st.session_state:
    st.session_state["alimtalk_rows"] = []


def _force_rerun():
    rerun_fn = getattr(st, "rerun", None) or getattr(st, "experimental_rerun", None)
    if rerun_fn:
        rerun_fn()


def _load_name_to_ticker_map(names: set[str]) -> dict[str, str]:
    if not names:
        return {}
    with db_session() as s:
        rows = s.execute(
            select(TickerMaster.name_ko, TickerMaster.ticker).where(TickerMaster.name_ko.in_(names))
        ).all()
    return {name: ticker for name, ticker in rows}


def _safe_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, str) and value.strip() == "":
        return None
    if hasattr(pd, "isna") and pd.isna(value):
        return None
    try:
        return pd.to_datetime(value).date()
    except Exception:
        return None


def _to_float(value):
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if value == "":
            return None
    if hasattr(pd, "isna") and pd.isna(value):
        return None
    try:
        return float(value)
    except Exception:
        return None


with st.form("alimtalk_parse_form"):
    raw_input = st.text_area("알림톡 원문 (여러 건은 빈 줄로 구분 가능)", height=260)
    default_year = st.number_input("기본 연도", min_value=2000, max_value=2100, value=date.today().year, step=1)
    fallback_date = st.date_input("기본 지급일 (해외/미기재용)", value=date.today())
    default_acct = st.selectbox(
        "기본 계좌 구분",
        options=ACCOUNT_OPTIONS,
        index=0,
        help="필요 시 아래 테이블에서 개별 수정 가능합니다.",
    )
    submitted = st.form_submit_button("파싱")

if submitted:
    if not raw_input.strip():
        st.warning("알림톡 원문을 입력해 주세요.")
    else:
        try:
            parsed_messages = parse_messages(raw_input)
        except Exception as exc:
            st.error(f"파싱에 실패했습니다: {exc}")
        else:
            if not parsed_messages:
                st.warning("파싱할 메시지가 없습니다.")
            else:
                unresolved_names = {msg.ticker_name for msg in parsed_messages if msg.ticker is None}
                name_to_ticker = _load_name_to_ticker_map(unresolved_names)
                rows = []
                for msg in parsed_messages:
                    if msg.pay_date_hint:
                        month, day = msg.pay_date_hint
                        try:
                            pay_date = date(int(default_year), month, day)
                        except ValueError:
                            pay_date = fallback_date
                    else:
                        pay_date = fallback_date

                    ticker_value = msg.ticker or name_to_ticker.get(msg.ticker_name, "")

                    row = {
                        "messageType": msg.message_type,
                        "rawText": msg.raw_text,
                        "accountRef": msg.account_ref or "",
                        "tickerName": msg.ticker_name,
                        "ticker": ticker_value,
                        "currency": msg.currency,
                        "grossDividend": msg.gross_dividend,
                        "netDividend": msg.net_dividend,
                        "tax": msg.tax,
                        "accountType": default_acct,
                        "payDate": pay_date,
                        "fxRate": 1.0 if msg.currency.upper() == "KRW" else None,
                        "krwGross": msg.gross_dividend if msg.currency.upper() == "KRW" else None,
                        "krwNet": msg.net_dividend if (msg.currency.upper() == "KRW" and msg.net_dividend is not None) else None,
                    }
                    rows.append(row)

                st.session_state["alimtalk_rows"] = rows
                st.success(f"{len(rows)}건 파싱 완료. 아래에서 값 확인 후 Import 하세요.")


rows = st.session_state.get("alimtalk_rows", [])

if rows:
    df = pd.DataFrame(rows)
    edited = st.data_editor(
        df,
        num_rows="dynamic",
        use_container_width=True,
        key="alimtalk_editor",
        column_config={
            "messageType": st.column_config.TextColumn("구분", disabled=True, width="small"),
            "accountRef": st.column_config.TextColumn("알림톡 계좌", disabled=True),
            "tickerName": st.column_config.TextColumn("알림톡 종목명", disabled=True),
            "rawText": st.column_config.TextColumn("원문", disabled=True, width="large"),
            "ticker": st.column_config.TextColumn("Ticker (필수)"),
            "currency": st.column_config.TextColumn("통화"),
            "grossDividend": st.column_config.NumberColumn("세전 배당", format="%.4f"),
            "netDividend": st.column_config.NumberColumn("세후 배당", format="%.4f"),
            "tax": st.column_config.NumberColumn("원통화 세금", format="%.4f"),
            "accountType": st.column_config.SelectboxColumn(
                "계좌 구분",
                options=ACCOUNT_OPTIONS,
            ),
            "payDate": st.column_config.DateColumn("지급일"),
            "fxRate": st.column_config.NumberColumn("환율", format="%.4f"),
            "krwGross": st.column_config.NumberColumn("KRW 세전", format="%.2f"),
            "krwNet": st.column_config.NumberColumn("KRW 세후", format="%.2f"),
        },
        hide_index=True,
    )
    st.session_state["alimtalk_rows"] = edited.to_dict("records")

    st.caption("필요 시 Ticker/지급일/환율/원화 금액을 직접 수정할 수 있습니다.")

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("환율 자동 조회", use_container_width=True):
            updated_rows = st.session_state["alimtalk_rows"]
            errors = []
            updated = False
            for idx, row in enumerate(updated_rows):
                currency = (row.get("currency") or "").upper()
                if currency in ("", "KRW"):
                    continue
                pay_date = _safe_date(row.get("payDate"))
                if not pay_date:
                    errors.append(f"{idx + 1}행: 지급일 누락")
                    continue
                rate = fetch_fx_rate_frankfurter(currency, "KRW", pay_date)
                if rate is None:
                    errors.append(f"{idx + 1}행: {currency} 환율 조회 실패")
                    continue
                row["fxRate"] = rate
                if row.get("grossDividend") not in (None, ""):
                    row["krwGross"] = round(row["grossDividend"] * rate, 2)
                if row.get("netDividend") not in (None, ""):
                    row["krwNet"] = round(row["netDividend"] * rate, 2)
                updated = True
            st.session_state["alimtalk_rows"] = updated_rows
            if updated:
                st.success("환율 업데이트 완료")
                _force_rerun()
            elif errors:
                st.error(" / ".join(errors))
                st.info("네트워크 접근 제한 시 아래 수동 환율 입력 도우미를 사용해 주세요.")
            else:
                st.info("변경된 환율이 없습니다.")

    with col2:
        if st.button("KRW 환산 재계산", use_container_width=True):
            updated_rows = st.session_state["alimtalk_rows"]
            for row in updated_rows:
                rate = _to_float(row.get("fxRate"))
                if rate in (None, 0):
                    continue
                if row.get("grossDividend") not in (None, ""):
                    row["krwGross"] = round(row["grossDividend"] * rate, 2)
                if row.get("netDividend") not in (None, ""):
                    row["krwNet"] = round(row["netDividend"] * rate, 2)
            st.session_state["alimtalk_rows"] = updated_rows
            st.success("원화 금액을 재계산했습니다.")

    with col3:
        if st.button("현재 목록 비우기", use_container_width=True):
            st.session_state["alimtalk_rows"] = []
            _force_rerun()

    currencies = sorted(
        {
            (row.get("currency") or "").upper()
            for row in st.session_state["alimtalk_rows"]
            if (row.get("currency") or "").upper() not in ("", "KRW")
        }
    )
    if currencies:
        with st.expander("수동 환율 입력 도우미", expanded=False):
            c1, c2 = st.columns(2)
            selected_currency = c1.selectbox(
                "통화 선택",
                options=currencies,
                key="manual_fx_currency",
            )
            manual_rate = c2.number_input(
                "환율 (통화 -> KRW)",
                min_value=0.0,
                format="%.4f",
                key="manual_fx_rate",
            )
            apply_manual = st.button("선택 통화 환율 적용", use_container_width=True)
            if apply_manual:
                if manual_rate <= 0:
                    st.warning("0보다 큰 환율 값을 입력해 주세요.")
                else:
                    updated_rows = st.session_state["alimtalk_rows"]
                    for row in updated_rows:
                        currency = (row.get("currency") or "").upper()
                        if currency != selected_currency:
                            continue
                        row["fxRate"] = manual_rate
                        if row.get("grossDividend") not in (None, ""):
                            row["krwGross"] = round(float(row["grossDividend"]) * manual_rate, 2)
                        if row.get("netDividend") not in (None, ""):
                            row["krwNet"] = round(float(row["netDividend"]) * manual_rate, 2)
                    st.session_state["alimtalk_rows"] = updated_rows
                    st.success(f"{selected_currency} 환율을 적용했습니다.")
                    _force_rerun()

    def _build_payloads(data_rows: list[dict]) -> list[AlimtalkImportPayload]:
        payloads: list[AlimtalkImportPayload] = []
        for idx, row in enumerate(data_rows, start=1):
            pay_date = _safe_date(row.get("payDate"))
            if not pay_date:
                raise ValueError(f"{idx}행: 지급일(payDate)를 입력해 주세요.")

            ticker = normalize_ticker(row.get("ticker"))
            if not ticker:
                raise ValueError(f"{idx}행: Ticker를 입력해 주세요.")

            gross = _to_float(row.get("grossDividend"))
            krw_gross = _to_float(row.get("krwGross"))
            if gross is None:
                raise ValueError(f"{idx}행: 세전 배당 금액이 필요합니다.")
            if krw_gross is None:
                raise ValueError(f"{idx}행: KRW 세전 금액이 필요합니다.")

            fx_rate = _to_float(row.get("fxRate"))
            currency = (row.get("currency") or "KRW").upper()
            if currency != "KRW" and (fx_rate is None or fx_rate == 0):
                raise ValueError(f"{idx}행: 해외 통화 환율을 입력해 주세요.")

            net = _to_float(row.get("netDividend"))
            krw_net = _to_float(row.get("krwNet"))
            tax = _to_float(row.get("tax"))
            account_type_value = row.get("accountType")
            try:
                account_type = AccountType(account_type_value)
            except Exception as exc:
                raise ValueError(f"{idx}행: 계좌 구분 값이 올바르지 않습니다.") from exc

            payloads.append(
                AlimtalkImportPayload(
                    row_id=build_row_id(row.get("rawText", ""), pay_date, ticker),
                    pay_date=pay_date,
                    ticker=ticker,
                    currency=currency,
                    fx_rate=fx_rate if currency != "KRW" else 1.0,
                    gross_dividend=gross,
                    net_dividend=net,
                    tax=tax,
                    krw_gross=krw_gross,
                    krw_net=krw_net,
                    account_type=account_type,
                    raw_text=row.get("rawText", ""),
                )
            )
        return payloads

    if st.button("Import to DividendEvent", type="primary", use_container_width=True):
        data_rows = st.session_state.get("alimtalk_rows", [])
        if not data_rows:
            st.warning("Import할 데이터가 없습니다.")
        else:
            try:
                payloads = _build_payloads(data_rows)
            except ValueError as exc:
                st.error(str(exc))
            else:
                with db_session() as s:
                    result = upsert_alimtalk_events(s, payloads)
                st.success(f"Import 완료 - inserted: {result.inserted}, updated: {result.updated}")
                st.session_state["alimtalk_rows"] = []
                _force_rerun()
else:
    st.info("먼저 알림톡 원문을 입력하고 파싱 버튼을 눌러 주세요.")
