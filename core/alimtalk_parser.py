from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date
from typing import Sequence

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from core.cash_service import apply_cash_delta, get_latest_cash_snapshot
from core.models import AccountType, DividendEvent, DividendSource
from core.utils import normalize_ticker


@dataclass
class ParsedAlimtalkMessage:
    raw_text: str
    message_type: str  # domestic | overseas
    ticker_name: str
    ticker: str | None
    currency: str
    gross_dividend: float
    net_dividend: float | None
    tax: float | None
    account_ref: str | None
    pay_date_hint: tuple[int, int] | None


@dataclass
class AlimtalkImportPayload:
    row_id: str
    pay_date: date
    ticker: str
    currency: str
    fx_rate: float | None
    gross_dividend: float
    net_dividend: float | None
    tax: float | None
    krw_gross: float
    krw_net: float | None
    account_type: AccountType
    raw_text: str


@dataclass
class AlimtalkUpsertResult:
    inserted: int
    updated: int


def _clean_input(raw_text: str) -> str:
    cleaned = re.sub(r"<case\d+>\s*", "", raw_text or "", flags=re.IGNORECASE)
    return cleaned.strip()


def split_messages(raw_blob: str) -> list[str]:
    """Split pasted blob into individual alimtalk messages."""
    cleaned = _clean_input(raw_blob)
    if not cleaned:
        return []

    # Most messages start with [키움] or [키움증권]; split on blank lines that precede a new bracket.
    parts = re.split(r"\n{2,}(?=\[)", cleaned)
    if len(parts) == 1:
        return [cleaned]
    return [p.strip() for p in parts if p.strip()]


def parse_messages(raw_blob: str) -> list[ParsedAlimtalkMessage]:
    messages = split_messages(raw_blob)
    parsed: list[ParsedAlimtalkMessage] = []
    for chunk in messages:
        parsed.append(parse_message(chunk))
    return parsed


def parse_message(raw_text: str) -> ParsedAlimtalkMessage:
    text = _clean_input(raw_text)
    if not text:
        raise ValueError("알림톡 원문이 비어있습니다.")

    if "해외주식" in text or "▶종목코드" in text:
        return _parse_overseas(text)
    return _parse_domestic(text)


def _parse_domestic(text: str) -> ParsedAlimtalkMessage:
    mmdd = re.search(r"\[(?:키움)\]\s*(\d{1,2})/(\d{1,2})", text)
    pay_date_hint = None
    if mmdd:
        pay_date_hint = (int(mmdd.group(1)), int(mmdd.group(2)))

    name_match = re.search(r"▶종목명\s*[:：]\s*(.+)", text)
    if not name_match:
        raise ValueError("국내주식 알림톡에서 종목명을 찾을 수 없습니다.")
    ticker_name = name_match.group(1).strip()

    amounts = re.search(
        r"▶배당입금\s*[:：]\s*([\d,\.]+)\s*\(세전\)\s*/\s*([\d,\.]+)\s*\(세후\)",
        text,
    )
    if not amounts:
        raise ValueError("국내주식 알림톡에서 배당입금 값을 찾을 수 없습니다.")
    gross = _to_float(amounts.group(1))
    net = _to_float(amounts.group(2))
    tax = gross - net if (gross is not None and net is not None) else None

    account = _extract_account(text)

    return ParsedAlimtalkMessage(
        raw_text=text,
        message_type="domestic",
        ticker_name=ticker_name,
        ticker=None,
        currency="KRW",
        gross_dividend=gross,
        net_dividend=net,
        tax=tax,
        account_ref=account,
        pay_date_hint=pay_date_hint,
    )


def _parse_overseas(text: str) -> ParsedAlimtalkMessage:
    ticker_match = re.search(r"▶종목코드\s*[:：]\s*([A-Za-z0-9\.\-]+)", text)
    if not ticker_match:
        raise ValueError("해외주식 알림톡에서 종목코드를 찾을 수 없습니다.")
    ticker = normalize_ticker(ticker_match.group(1))

    name_match = re.search(r"▶종목명\s*[:：]\s*(.+)", text)
    ticker_name = name_match.group(1).strip() if name_match else ticker

    amounts = re.search(
        r"▶배당금액\s*[:：]\s*([\d,\.]+)\s*([A-Z]{3})\s*\(세전\)\s*/\s*([\d,\.]+)\s*([A-Z]{3})\s*\(세후\)",
        text,
    )
    if not amounts:
        raise ValueError("해외주식 알림톡에서 배당금액 라인을 찾을 수 없습니다.")
    gross = _to_float(amounts.group(1))
    net = _to_float(amounts.group(3))
    currency = amounts.group(2)

    tax = None
    tax_line = re.search(r"▶외국납부세액\s*[:：]\s*([\d,\.]+)\s*([A-Z]{3})", text)
    if tax_line:
        tax = _to_float(tax_line.group(1))
    elif gross is not None and net is not None:
        tax = round(gross - net, 6)

    account = _extract_account(text)

    return ParsedAlimtalkMessage(
        raw_text=text,
        message_type="overseas",
        ticker_name=ticker_name,
        ticker=ticker,
        currency=currency,
        gross_dividend=gross,
        net_dividend=net,
        tax=tax,
        account_ref=account,
        pay_date_hint=None,
    )


def _extract_account(text: str) -> str | None:
    account_match = re.search(r"▶계좌(?:번호)?\s*[:：]\s*([0-9\-\*\s]+)", text)
    if account_match:
        return account_match.group(1).strip()
    return None


def _to_float(value: str | None) -> float | None:
    if value is None:
        return None
    stripped = value.replace(",", "").strip()
    if stripped == "":
        return None
    return float(stripped)


def build_row_id(raw_text: str, pay_date: date, ticker: str) -> str:
    base = f"{raw_text.strip()}|{pay_date.isoformat()}|{ticker.upper()}"
    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]
    return f"alimtalk:{digest}"


def _cash_amount_krw(krw_net: float | None, krw_gross: float) -> float:
    return float(krw_net) if krw_net is not None else float(krw_gross)


def _resolve_cash_target_date(session: Session, account_type: AccountType, base_date: date) -> date:
    target_date = base_date
    latest_account_cash = get_latest_cash_snapshot(session, account_type=account_type)
    latest_all_cash = get_latest_cash_snapshot(session, account_type=AccountType.ALL)
    for latest_cash in (latest_account_cash, latest_all_cash):
        if latest_cash and latest_cash.snapshot_date > target_date:
            target_date = latest_cash.snapshot_date
    return target_date


def upsert_alimtalk_events(session: Session, rows: Sequence[AlimtalkImportPayload]) -> AlimtalkUpsertResult:
    if not rows:
        return AlimtalkUpsertResult(inserted=0, updated=0)

    existing = session.execute(
        select(DividendEvent)
        .where(DividendEvent.row_id.in_([row.row_id for row in rows]))
    ).scalars().all()
    existing_map = {row.row_id: row for row in existing}

    inserted = 0
    updated = 0

    for row in rows:
        cash_amount = _cash_amount_krw(row.krw_net, row.krw_gross)
        payload = dict(
            row_id=row.row_id,
            pay_date=row.pay_date,
            year=row.pay_date.year,
            month=row.pay_date.month,
            ticker=row.ticker,
            currency=row.currency,
            fx_rate=row.fx_rate,
            gross_dividend=row.gross_dividend,
            tax=row.tax,
            net_dividend=row.net_dividend,
            krw_gross=row.krw_gross,
            krw_net=row.krw_net,
            account_type=row.account_type,
            source=DividendSource.ALIMTALK.value,
            archived=False,
            raw_text=row.raw_text,
        )

        existing_row = existing_map.get(row.row_id)
        if existing_row:
            session.execute(
                update(DividendEvent)
                .where(DividendEvent.row_id == row.row_id)
                .values(**payload)
            )
            updated += 1
            previous_amount = _cash_amount_krw(existing_row.krw_net, existing_row.krw_gross)
            if (
                abs(previous_amount - cash_amount) > 1e-6
                or existing_row.pay_date != row.pay_date
                or existing_row.account_type != row.account_type
            ):
                if previous_amount > 0:
                    previous_target = _resolve_cash_target_date(
                        session,
                        account_type=existing_row.account_type,
                        base_date=existing_row.pay_date,
                    )
                    apply_cash_delta(
                        session,
                        account_type=existing_row.account_type,
                        snapshot_date=previous_target,
                        delta_krw=-previous_amount,
                        note=f"alimtalk dividend adjust {existing_row.ticker}",
                    )
                    apply_cash_delta(
                        session,
                        account_type=AccountType.ALL,
                        snapshot_date=previous_target,
                        delta_krw=-previous_amount,
                        note=f"alimtalk dividend adjust {existing_row.ticker}",
                    )
                if cash_amount > 0:
                    target_date = _resolve_cash_target_date(
                        session,
                        account_type=row.account_type,
                        base_date=row.pay_date,
                    )
                    apply_cash_delta(
                        session,
                        account_type=row.account_type,
                        snapshot_date=target_date,
                        delta_krw=cash_amount,
                        note=f"alimtalk dividend {row.ticker}",
                    )
                    apply_cash_delta(
                        session,
                        account_type=AccountType.ALL,
                        snapshot_date=target_date,
                        delta_krw=cash_amount,
                        note=f"alimtalk dividend {row.ticker}",
                    )
        else:
            session.add(DividendEvent(**payload))
            inserted += 1
            if cash_amount > 0:
                target_date = _resolve_cash_target_date(
                    session,
                    account_type=row.account_type,
                    base_date=row.pay_date,
                )
                apply_cash_delta(
                    session,
                    account_type=row.account_type,
                    snapshot_date=target_date,
                    delta_krw=cash_amount,
                    note=f"alimtalk dividend {row.ticker}",
                )
                apply_cash_delta(
                    session,
                    account_type=AccountType.ALL,
                    snapshot_date=target_date,
                    delta_krw=cash_amount,
                    note=f"alimtalk dividend {row.ticker}",
                )

    return AlimtalkUpsertResult(inserted=inserted, updated=updated)
