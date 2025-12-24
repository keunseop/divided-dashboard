from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd
from sqlalchemy import select, update

from core.models import AccountType, DividendEvent


# ✅ 네 CSV 헤더(한글) -> 내부 표준명 매핑
HEADER_MAP = {
    "rowId": "rowId",
    "날짜": "payDate",
    "년도": "year",
    "월": "month",
    "종목코드": "ticker",

    # 원통화(세전) 배당금: USD가 올 수 있음
    "배당금": "grossDividend",

    # 통화/환율
    "통화": "currency",
    "환율": "fxRate",

    # ✅ "세전배당금" = 원화환산(세전) 핵심값
    "세전배당금": "krwGross",

    # (선택) 알림톡 기반 데이터에서 채워질 수 있음
    "세후배당금": "netDividend",
    "세금": "tax",

    # 계좌구분: 일반/ISA
    "계좌구분": "accountType",

    # 종목명은 표준화 위해 ticker_master에서만 보여주는 걸 추천
    # "종목명": "name",
}

# 내부 표준 기준: 최소 필요 컬럼
REQUIRED = ["rowId", "payDate", "year", "month", "ticker", "grossDividend", "krwGross", "accountType"]


def _to_number(x):
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    s = str(x).strip()
    if s == "" or s == "-" or s.lower() == "nan":
        return None
    s = s.replace(",", "")
    s = re.sub(r"[^0-9\.\-]", "", s)
    if s in ("", "-", ".", "-.", ".-"):
        return None
    return float(s)


def _normalize_account_type(v: str) -> str:
    if v is None:
        return None
    s = str(v).strip()
    if s == "":
        return None
    if s == "일반":
        return AccountType.TAXABLE.value
    if s.upper() == "ISA":
        return AccountType.ISA.value
    if s.upper() in (AccountType.TAXABLE.value, AccountType.ISA.value):
        return s.upper()
    raise ValueError(f"계좌구분 값이 올바르지 않습니다: {v} (일반/ISA 또는 TAXABLE/ISA)")


def read_and_normalize_csv(uploaded_file) -> pd.DataFrame:
    df_raw = pd.read_csv(uploaded_file, dtype=str)

    # 한글 헤더 -> 표준명으로 rename
    rename_map = {c: HEADER_MAP[c] for c in df_raw.columns if c in HEADER_MAP}
    df = df_raw.rename(columns=rename_map)

    # 필요한 컬럼 존재 체크
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"CSV에 필요한 컬럼이 없습니다: {missing} (현재: {list(df_raw.columns)})")

    # 날짜 파싱: "2020. 4. 9" 형태
    df["payDate"] = df["payDate"].astype(str).str.strip().str.replace(r"\s+", " ", regex=True)
    dt = pd.to_datetime(df["payDate"], format="%Y. %m. %d", errors="coerce")
    # 혹시 포맷이 살짝 다르면 fallback
    dt2 = pd.to_datetime(df["payDate"], errors="coerce")
    df["payDate"] = dt.fillna(dt2)
    if df["payDate"].isna().any():
        bad = df[df["payDate"].isna()][["rowId", "payDate"]].head(5)
        raise ValueError(f"날짜 파싱 실패가 있습니다. 예시:\n{bad}")
    df["payDate"] = df["payDate"].dt.date

    # 정수
    df["year"] = df["year"].astype(int)
    df["month"] = df["month"].astype(int)

    # 숫자들
    for col in ["fxRate", "grossDividend", "krwGross", "tax", "netDividend"]:
        if col in df.columns:
            df[col] = df[col].map(_to_number)

    # 통화 기본값
    df["currency"] = df["currency"].fillna("KRW").astype(str).str.upper()

    # 계좌구분 정규화
    df["accountType"] = df["accountType"].map(_normalize_account_type)
    if df["accountType"].isna().any():
        raise ValueError("계좌구분(accountType)에 빈 값이 있습니다.")

    # 필수값 검증
    df["rowId"] = df["rowId"].astype(str).str.strip()
    df["ticker"] = df["ticker"].astype(str).str.strip()

    if df["grossDividend"].isna().any():
        raise ValueError("배당금(grossDividend)에 빈 값이 있습니다.")
    if df["krwGross"].isna().any():
        raise ValueError("세전배당금(krwGross, 원화환산 세전)에 빈 값이 있습니다.")
    if (df["ticker"] == "").any():
        raise ValueError("종목코드(ticker)가 비어있는 행이 있습니다.")

    # krwNet은 아직 CSV에 없으니 None으로 유지
    df["krwNet"] = None

    # 최종 표준 컬럼만 반환
    keep = [
        "rowId", "payDate", "year", "month",
        "ticker", "currency", "fxRate",
        "grossDividend", "tax", "netDividend",
        "krwGross", "krwNet",
        "accountType",
    ]
    for k in keep:
        if k not in df.columns:
            df[k] = None

    return df[keep].copy()


@dataclass
class ImportResult:
    inserted: int
    updated: int
    archived_candidates: int


def upsert_dividends(session, df: pd.DataFrame, sync_mode: bool = True) -> ImportResult:
    existing = session.execute(
        select(DividendEvent.row_id, DividendEvent.id, DividendEvent.archived, DividendEvent.source)
    ).all()
    existing_map = {r[0]: {"id": r[1], "archived": r[2], "source": r[3]} for r in existing}

    inserted = 0
    updated_count = 0

    incoming_row_ids = set(df["rowId"].tolist())

    for _, row in df.iterrows():
        row_id = row["rowId"]
        payload = dict(
            row_id=row_id,
            pay_date=row["payDate"],
            year=int(row["year"]),
            month=int(row["month"]),
            ticker=row["ticker"],
            currency=row["currency"],
            fx_rate=row["fxRate"],
            gross_dividend=float(row["grossDividend"]),   # 원통화 세전
            tax=row["tax"],                               # 원통화
            net_dividend=row["netDividend"],              # 원통화
            krw_gross=float(row["krwGross"]),             # ✅ 원화환산 세전(핵심)
            krw_net=row["krwNet"],                        # 아직 없음
            account_type=AccountType(row["accountType"]),
            source="excel",
            archived=False,
        )

        if row_id in existing_map:
            session.execute(
                update(DividendEvent)
                .where(DividendEvent.row_id == row_id)
                .values(**payload)
            )
            updated_count += 1
        else:
            session.add(DividendEvent(**payload))
            inserted += 1

    archived_candidates = 0
    if sync_mode:
        for row_id, meta in existing_map.items():
            if meta["source"] == "excel" and not meta["archived"] and row_id not in incoming_row_ids:
                session.execute(
                    update(DividendEvent)
                    .where(DividendEvent.row_id == row_id)
                    .values(archived=True)
                )
                archived_candidates += 1

    return ImportResult(inserted=inserted, updated=updated_count, archived_candidates=archived_candidates)
