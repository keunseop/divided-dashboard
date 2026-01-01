from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from sqlalchemy import select

from core.models import AccountType, HoldingLot, HoldingPosition, PortfolioSnapshot, TradeSide
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
    "평균매입가(원)": "avg_buy_price_krw",
    "평균매입가원": "avg_buy_price_krw",
    "note": "note",
    "비고": "note",
    "source": "source",
}

SNAPSHOT_COLUMN_MAP = {
    "snapshotid": "external_id",
    "snapshot_id": "external_id",
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

LOT_COLUMN_MAP = {
    "거래일": "trade_date",
    "date": "trade_date",
    "trade_date": "trade_date",
    "체결일": "trade_date",
    "종목코드": "ticker",
    "티커": "ticker",
    "ticker": "ticker",
    "계좌": "account_type",
    "계좌구분": "account_type",
    "account": "account_type",
    "side": "side",
    "매수매도": "side",
    "매매구분": "side",
    "거래구분": "side",
    "수량": "quantity",
    "quantity": "quantity",
    "단가": "price",
    "가격": "price",
    "price": "price",
    "통화": "currency",
    "currency": "currency",
    "환율": "fx_rate",
    "fx": "fx_rate",
    "fx_rate": "fx_rate",
    "단가(krw)": "price_krw",
    "price_krw": "price_krw",
    "원화단가": "price_krw",
    "금액": "amount_krw",
    "금액(krw)": "amount_krw",
    "amount": "amount_krw",
    "note": "note",
    "비고": "note",
    "source": "source",
    "row_id": "external_id",
    "id": "external_id",
    "lot_id": "external_id",
}

SIDE_ALIASES = {
    "매수": TradeSide.BUY,
    "buy": TradeSide.BUY,
    "b": TradeSide.BUY,
    "long": TradeSide.BUY,
    "매도": TradeSide.SELL,
    "sell": TradeSide.SELL,
    "s": TradeSide.SELL,
    "short": TradeSide.SELL,
}


def _drop_blank_columns(df: pd.DataFrame) -> pd.DataFrame:
    stripped = {}
    drop_cols: list[str] = []
    for column in df.columns:
        normalized = column.strip()
        if not normalized or normalized.lower().startswith("unnamed"):
            drop_cols.append(column)
            continue
        key = normalized.lower()
        if key in stripped:
            drop_cols.append(column)
            continue
        stripped[key] = column
    if drop_cols:
        df = df.drop(columns=drop_cols)
    return df


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
        cleaned = (
            cleaned.replace(",", "")
            .replace("₩", "")
            .replace("KRW", "")
            .strip()
        )
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
    df = _drop_blank_columns(df)
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

    if "note" in df.columns:
        df["note"] = df["note"].fillna("").map(lambda s: s.strip() or None)
    else:
        df["note"] = None

    if "source" in df.columns:
        df["source"] = df["source"].fillna("").map(lambda s: s.strip() or "manual")
    else:
        df["source"] = "manual"

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
    df = _drop_blank_columns(df)
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
    if "external_id" in df.columns:
        df["external_id"] = df["external_id"].map(lambda v: (v or "").strip() or None)
    else:
        df["external_id"] = None

    if "note" in df.columns:
        df["note"] = df["note"].fillna("").map(lambda s: s.strip() or None)
    else:
        df["note"] = None

    if "source" in df.columns:
        df["source"] = df["source"].fillna("").map(lambda s: s.strip() or "excel")
    else:
        df["source"] = "excel"

    return df


def upsert_portfolio_snapshots(session, df: pd.DataFrame) -> ImportResult:
    inserted = 0
    updated = 0
    for row in df.to_dict("records"):
        external_id = row.get("external_id")
        stmt = select(PortfolioSnapshot)
        if external_id:
            stmt = stmt.where(PortfolioSnapshot.external_id == external_id)
        else:
            stmt = stmt.where(
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
            if external_id:
                existing.external_id = external_id
            updated += 1
        else:
            session.add(
                PortfolioSnapshot(
                    external_id=external_id,
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


def read_holding_lots_csv(uploaded_file) -> pd.DataFrame:
    df = pd.read_csv(uploaded_file, dtype=str).fillna("")
    df = _drop_blank_columns(df)
    df = _normalize_columns(df, LOT_COLUMN_MAP)

    required = ["trade_date", "ticker", "account_type", "quantity"]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"필수 컬럼이 누락되었습니다: {missing}")

    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce")
    if df["trade_date"].isna().any():
        bad = df[df["trade_date"].isna()][["trade_date", "ticker"]].head(5)
        raise ValueError(f"거래일을 날짜로 변환할 수 없습니다: {bad}")
    df["trade_date"] = df["trade_date"].dt.date

    df["ticker"] = df["ticker"].map(normalize_ticker)
    if (df["ticker"] == "").any():
        raise ValueError("티커가 비어 있는 행이 있습니다.")

    df["account_type"] = df["account_type"].map(lambda v: _normalize_account(v, default=AccountType.TAXABLE))
    df["quantity"] = df["quantity"].map(_to_float)
    if df["quantity"].isna().any():
        raise ValueError("수량을 숫자로 변환할 수 없는 행이 있습니다.")
    if (df["quantity"] <= 0).any():
        raise ValueError("수량은 0보다 커야 합니다.")

    if "side" not in df.columns:
        df["side"] = TradeSide.BUY.value
    df["side"] = df["side"].fillna("").map(lambda v: _normalize_side(v))

    if "currency" not in df.columns:
        df["currency"] = "KRW"
    df["currency"] = df["currency"].fillna("").map(lambda v: (v or "KRW").strip().upper() or "KRW")

    if "price" in df.columns:
        df["price"] = df["price"].map(_to_float)
    else:
        df["price"] = None

    if "fx_rate" not in df.columns:
        df["fx_rate"] = None
    df["fx_rate"] = df["fx_rate"].map(_to_float)
    df.loc[df["currency"] == "KRW", "fx_rate"] = df.loc[df["currency"] == "KRW", "fx_rate"].fillna(1.0)
    missing_fx = (df["currency"] != "KRW") & df["fx_rate"].isna()
    if missing_fx.any():
        raise ValueError("KRW 이외 통화 행에 환율(fx_rate)이 필요합니다.")

    if "price_krw" in df.columns:
        df["price_krw"] = df["price_krw"].map(_to_float)
    else:
        df["price_krw"] = None

    missing_price = df["price_krw"].isna() & df["price"].notna() & df["fx_rate"].notna()
    df.loc[missing_price, "price_krw"] = df.loc[missing_price, "price"] * df.loc[missing_price, "fx_rate"]

    if df["price_krw"].isna().any():
        raise ValueError("원화 단가(price_krw)를 계산할 수 없는 행이 있습니다. 단가/환율을 확인하세요.")

    if df["price"].isna().all():
        df["price"] = df["price_krw"]
    else:
        df["price"] = df["price"].fillna(df["price_krw"])

    if "amount_krw" in df.columns:
        df["amount_krw"] = df["amount_krw"].map(_to_float)
    else:
        df["amount_krw"] = None
    missing_amount = df["amount_krw"].isna()
    df.loc[missing_amount, "amount_krw"] = df.loc[missing_amount, "price_krw"] * df.loc[missing_amount, "quantity"]

    if "note" not in df.columns:
        df["note"] = None
    df["note"] = df["note"].fillna("").map(lambda s: s.strip() or None)

    if "source" not in df.columns:
        df["source"] = "excel"
    df["source"] = df["source"].fillna("").map(lambda s: s.strip() or "excel")

    if "external_id" not in df.columns:
        df["external_id"] = None
    df["external_id"] = df["external_id"].fillna("").map(lambda s: s.strip() or None)

    keep = [
        "external_id",
        "trade_date",
        "ticker",
        "account_type",
        "side",
        "quantity",
        "price",
        "currency",
        "fx_rate",
        "price_krw",
        "amount_krw",
        "note",
        "source",
    ]
    return df[keep].copy()


def _normalize_side(value) -> TradeSide:
    if isinstance(value, TradeSide):
        return value
    if value is None:
        return TradeSide.BUY
    normalized = str(value).strip()
    if not normalized:
        return TradeSide.BUY
    key = normalized.lower()
    if key in SIDE_ALIASES:
        return SIDE_ALIASES[key]
    upper = normalized.upper()
    if upper in (TradeSide.BUY.value, TradeSide.SELL.value):
        return TradeSide(upper)
    raise ValueError(f"side 값을 해석할 수 없습니다: {value}")


def upsert_holding_lots(session, df: pd.DataFrame) -> ImportResult:
    inserted = 0
    updated = 0

    for row in df.to_dict("records"):
        external_id = row.get("external_id")
        lot = None
        if external_id:
            stmt = select(HoldingLot).where(HoldingLot.external_id == external_id)
            lot = session.execute(stmt).scalar_one_or_none()

        fx_value = row.get("fx_rate")
        if fx_value is None or pd.isna(fx_value):
            fx_value = 1.0 if row["currency"] == "KRW" else None
        if fx_value is None:
            raise ValueError("환율 정보가 없는 행이 있습니다.")

        payload = dict(
            trade_date=row["trade_date"],
            ticker=row["ticker"],
            account_type=row["account_type"],
            side=row["side"],
            quantity=float(row["quantity"]),
            price=float(row["price"]),
            currency=row["currency"],
            fx_rate=float(fx_value),
            price_krw=float(row["price_krw"]),
            amount_krw=float(row["amount_krw"]),
            note=row.get("note"),
            source=row.get("source") or "excel",
        )

        if lot:
            for key, value in payload.items():
                setattr(lot, key, value)
            updated += 1
        else:
            session.add(
                HoldingLot(
                    external_id=external_id,
                    **payload,
                )
            )
            inserted += 1

    return ImportResult(inserted=inserted, updated=updated)
