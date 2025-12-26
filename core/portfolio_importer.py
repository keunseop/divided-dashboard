from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from sqlalchemy import select

from core.models import AccountType, HoldingPosition, PortfolioSnapshot
from core.utils import normalize_ticker


@dataclass
class ImportResult:
    inserted: int
    updated: int


ACCOUNT_ALIASES = {
    "일반": AccountType.TAXABLE,
    "taxable": AccountType.TAXABLE,
    "t": AccountType.TAXABLE,
    "isa": AccountType.ISA,
    "아이사": AccountType.ISA,
    "연금": AccountType.ISA,
    "all": AccountType.ALL,
    "전체": AccountType.ALL,
}


POSITIONS_COLUMN_MAP = {
    "ticker": "ticker",
    "종목코드": "ticker",
    "티커": "ticker",
    "account": "account_type",
    "accounttype": "account_type",
    "계좌": "account_type",
    "계좌구분": "account_type",
    "quantity": "quantity",
    "수량": "quantity",
    "avg_buy_price_krw": "avg_buy_price_krw",
    "평균매입가": "avg_buy_price_krw",
    "평균매입가원": "avg_buy_price_krw",
    "note": "note",
    "비고": "note",
    "source": "source",
}

SNAPSHOT_COLUMN_MAP = {
    "snapshotid": "external_id",
    "기준일": "snapshot_date",
    "snapshotdate": "snapshot_date",
    "date": "snapshot_date",
    "계좌구분": "account_type",
    "계좌": "account_type",
    "누적원금": "contributed_krw",
    "누적납입": "contributed_krw",
    "contributed": "contributed_krw",
    "현금": "cash_krw",
    "cash": "cash_krw",
    "평가금액": "valuation_krw",
    "valuation": "valuation_krw",
    "비고": "note",
    "note": "note",
    "source": "source",
}


def _normalize_columns(df: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame:
    renamed = {}
    for column in df.columns:
        key = column.strip().lower()
        renamed[column] = mapping.get(key, column)
    return df.rename(columns=renamed)


def _to_float(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned == "" or cleaned == "-":
            return None
        cleaned = cleaned.replace(",", "")
        try:
            return float(cleaned)
        except ValueError:
            return None
    try:
        return float(value)
    except Exception:
        return None


def _normalize_account(value: str | None, *, default: AccountType) -> AccountType:
    if not value:
        return default
    key = value.strip().upper()
    if key in (AccountType.TAXABLE.value, AccountType.ISA.value, AccountType.ALL.value):
        return AccountType(key)
    alias = ACCOUNT_ALIASES.get(value.strip().lower())
    if alias:
        return alias
    raise ValueError(f"계좌 구분 값을 해석할 수 없습니다: {value}")


def read_holding_positions_csv(uploaded_file) -> pd.DataFrame:
    df = pd.read_csv(uploaded_file, dtype=str).fillna("")
    df = _normalize_columns(df, POSITIONS_COLUMN_MAP)

    required = ["ticker", "account_type", "quantity", "avg_buy_price_krw"]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"필수 컬럼이 누락되었습니다: {missing}")

    df["ticker"] = df["ticker"].map(normalize_ticker)
    if (df["ticker"] == "").any():
        raise ValueError("티커가 비어 있는 행이 있습니다.")

    df["account_type"] = df["account_type"].map(lambda v: _normalize_account(v, default=AccountType.TAXABLE))
    df["quantity"] = df["quantity"].map(_to_float)
    df["avg_buy_price_krw"] = df["avg_buy_price_krw"].map(_to_float)
    if df["quantity"].isna().any():
        raise ValueError("수량을 숫자로 변환할 수 없는 행이 있습니다.")
    if df["avg_buy_price_krw"].isna().any():
        raise ValueError("평균 매입가(원)를 숫자로 변환할 수 없는 행이 있습니다.")

    df["note"] = df.get("note", "").fillna("").map(lambda s: s.strip() or None)
    df["source"] = df.get("source", "").fillna("").map(lambda s: s.strip() or "manual")

    return df


def upsert_holding_positions(session, df: pd.DataFrame) -> ImportResult:
    inserted = 0
    updated = 0
    for row in df.to_dict("records"):
        ticker = row["ticker"]
        account = row["account_type"]
        stmt = select(HoldingPosition).where(
            HoldingPosition.ticker == ticker,
            HoldingPosition.account_type == account,
        )
        existing = session.execute(stmt).scalar_one_or_none()
        quantity = row["quantity"]
        avg_price = row["avg_buy_price_krw"]
        total_cost = quantity * avg_price
        if existing:
            existing.quantity = quantity
            existing.avg_buy_price_krw = avg_price
            existing.total_cost_krw = total_cost
            existing.note = row.get("note")
            existing.source = row.get("source") or existing.source
            updated += 1
        else:
            session.add(
                HoldingPosition(
                    ticker=ticker,
                    account_type=account,
                    quantity=quantity,
                    avg_buy_price_krw=avg_price,
                    total_cost_krw=total_cost,
                    note=row.get("note"),
                    source=row.get("source") or "manual",
                )
            )
            inserted += 1
    return ImportResult(inserted=inserted, updated=updated)


def read_portfolio_snapshots_csv(uploaded_file) -> pd.DataFrame:
    df = pd.read_csv(uploaded_file, dtype=str).fillna("")
    df = _normalize_columns(df, SNAPSHOT_COLUMN_MAP)
    required = ["snapshot_date", "account_type"]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"필수 컬럼이 누락되었습니다: {missing}")

    df["snapshot_date"] = pd.to_datetime(df["snapshot_date"], errors="coerce").dt.date
    if df["snapshot_date"].isna().any():
        raise ValueError("기준일을 날짜로 변환할 수 없는 행이 있습니다.")

    df["account_type"] = df["account_type"].map(lambda v: _normalize_account(v, default=AccountType.ALL))
    for column in ["contributed_krw", "cash_krw", "valuation_krw"]:
        if column in df.columns:
            df[column] = df[column].map(_to_float)
        else:
            df[column] = None
    df["note"] = df.get("note", "").fillna("").map(lambda s: s.strip() or None)
    df["source"] = df.get("source", "").fillna("").map(lambda s: s.strip() or "excel")

    return df


def upsert_portfolio_snapshots(session, df: pd.DataFrame) -> ImportResult:
    inserted = 0
    updated = 0
    for row in df.to_dict("records"):
        stmt = select(PortfolioSnapshot).where(
            PortfolioSnapshot.snapshot_date == row["snapshot_date"],
            PortfolioSnapshot.account_type == row["account_type"],
        )
        existing = session.execute(stmt).scalar_one_or_none()
        if existing:
            existing.contributed_krw = row.get("contributed_krw")
            existing.cash_krw = row.get("cash_krw")
            existing.valuation_krw = row.get("valuation_krw")
            existing.note = row.get("note")
            existing.source = row.get("source") or existing.source
            updated += 1
        else:
            session.add(
                PortfolioSnapshot(
                    snapshot_date=row["snapshot_date"],
                    account_type=row["account_type"],
                    contributed_krw=row.get("contributed_krw"),
                    cash_krw=row.get("cash_krw"),
                    valuation_krw=row.get("valuation_krw"),
                    note=row.get("note"),
                    source=row.get("source") or "excel",
                )
            )
            inserted += 1
    return ImportResult(inserted=inserted, updated=updated)
