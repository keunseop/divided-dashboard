from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from sqlalchemy import select

from core.models import TickerMaster
from core.utils import normalize_ticker


@dataclass
class TickerImportResult:
    inserted: int
    updated: int


def read_ticker_master_csv(uploaded_file) -> pd.DataFrame:
    df = pd.read_csv(uploaded_file, dtype=str)
    required = ["ticker", "name_ko"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"ticker_master.csv에 필요한 컬럼이 없습니다: {missing}")

    df["ticker"] = df["ticker"].map(normalize_ticker)
    df["name_ko"] = df["name_ko"].astype(str).str.strip()

    optional_cols = ["market", "currency"]
    for col in optional_cols:
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str).str.strip()

    if "currency" in df.columns:
        df["currency"] = df["currency"].str.upper()

    for col in optional_cols:
        if col in df.columns:
            df[col] = df[col].replace("", None)

    if (df["ticker"] == "").any():
        raise ValueError("ticker 컬럼이 비어있는 행이 있습니다.")
    if (df["name_ko"] == "").any():
        raise ValueError("name_ko 컬럼이 비어있는 행이 있습니다.")
    return df


def upsert_ticker_master(session, df: pd.DataFrame) -> TickerImportResult:
    inserted = 0
    updated = 0

    existing = session.execute(select(TickerMaster.ticker)).scalars().all()
    existing_set = set(existing)

    for _, row in df.iterrows():
        t = row["ticker"]
        n = row["name_ko"]
        market = row.get("market")
        currency = row.get("currency")
        if t in existing_set:
            obj = session.get(TickerMaster, t)
            if (
                obj.name_ko != n
                or obj.market != market
                or obj.currency != currency
            ):
                obj.name_ko = n
                obj.market = market
                obj.currency = currency
                updated += 1
        else:
            session.add(
                TickerMaster(
                    ticker=t,
                    name_ko=n,
                    market=market,
                    currency=currency,
                )
            )
            inserted += 1

    return TickerImportResult(inserted=inserted, updated=updated)
