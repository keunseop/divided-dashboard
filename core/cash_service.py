from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.firestore_reader import (
    is_firestore_enabled,
    list_cash_snapshots as list_cash_snapshots_firestore,
    parse_date,
)
from core.firestore_writer import upsert_cash_snapshots
from core.models import AccountType, CashSnapshot


@dataclass
class CashSnapshotView:
    snapshot_date: date
    account_type: AccountType
    cash_krw: float
    note: str | None


def upsert_cash_snapshot(
    session: Session,
    *,
    snapshot_date: date,
    account_type: AccountType,
    cash_krw: float,
    note: str | None = None,
) -> CashSnapshot:
    if cash_krw < 0:
        raise ValueError("현금 금액은 0 이상이어야 합니다.")

    if is_firestore_enabled():
        record = {
            "snapshot_date": snapshot_date,
            "account_type": account_type.value,
            "cash_krw": cash_krw,
            "note": note,
        }
        upsert_cash_snapshots([record])
        return CashSnapshot(
            snapshot_date=snapshot_date,
            account_type=account_type,
            cash_krw=cash_krw,
            note=note,
        )

    stmt = select(CashSnapshot).where(
        CashSnapshot.snapshot_date == snapshot_date,
        CashSnapshot.account_type == account_type,
    )
    existing = session.execute(stmt).scalar_one_or_none()
    if existing:
        existing.cash_krw = cash_krw
        existing.note = note
        return existing

    snapshot = CashSnapshot(
        snapshot_date=snapshot_date,
        account_type=account_type,
        cash_krw=cash_krw,
        note=note,
    )
    session.add(snapshot)
    return snapshot


def list_cash_snapshots(
    session: Session,
    *,
    account_type: AccountType,
    limit: int | None = None,
) -> list[CashSnapshotView]:
    if is_firestore_enabled():
        rows = list_cash_snapshots_firestore()
        filtered = []
        for row in rows:
            if row.get("account_type") != account_type.value:
                continue
            snapshot_date = parse_date(row.get("snapshot_date"))
            if snapshot_date is None:
                continue
            filtered.append(
                CashSnapshotView(
                    snapshot_date=snapshot_date,
                    account_type=account_type,
                    cash_krw=float(row.get("cash_krw") or 0),
                    note=row.get("note"),
                )
            )
        filtered.sort(key=lambda r: r.snapshot_date)
        if limit:
            return filtered[-limit:]
        return filtered

    order_clause = CashSnapshot.snapshot_date.desc() if limit else CashSnapshot.snapshot_date.asc()
    stmt = (
        select(CashSnapshot)
        .where(CashSnapshot.account_type == account_type)
        .order_by(order_clause)
    )
    if limit:
        stmt = stmt.limit(limit)
        rows = list(reversed(session.execute(stmt).scalars().all()))
    else:
        rows = session.execute(stmt).scalars().all()
    return [
        CashSnapshotView(
            snapshot_date=row.snapshot_date,
            account_type=row.account_type,
            cash_krw=row.cash_krw,
            note=row.note,
        )
        for row in rows
    ]


def get_latest_cash_snapshot(
    session: Session,
    *,
    account_type: AccountType,
) -> CashSnapshotView | None:
    if is_firestore_enabled():
        rows = list_cash_snapshots_firestore()
        latest: CashSnapshotView | None = None
        for row in rows:
            if row.get("account_type") != account_type.value:
                continue
            snapshot_date = parse_date(row.get("snapshot_date"))
            if snapshot_date is None:
                continue
            candidate = CashSnapshotView(
                snapshot_date=snapshot_date,
                account_type=account_type,
                cash_krw=float(row.get("cash_krw") or 0),
                note=row.get("note"),
            )
            if latest is None or candidate.snapshot_date > latest.snapshot_date:
                latest = candidate
        return latest

    stmt = (
        select(CashSnapshot)
        .where(CashSnapshot.account_type == account_type)
        .order_by(CashSnapshot.snapshot_date.desc())
        .limit(1)
    )
    row = session.execute(stmt).scalar_one_or_none()
    if row is None:
        return None
    return CashSnapshotView(
        snapshot_date=row.snapshot_date,
        account_type=row.account_type,
        cash_krw=row.cash_krw,
        note=row.note,
    )


def get_latest_cash_snapshot_on_or_before(
    session: Session,
    *,
    account_type: AccountType,
    snapshot_date: date,
) -> CashSnapshotView | None:
    if is_firestore_enabled():
        rows = list_cash_snapshots_firestore()
        latest: CashSnapshotView | None = None
        for row in rows:
            if row.get("account_type") != account_type.value:
                continue
            row_date = parse_date(row.get("snapshot_date"))
            if row_date is None or row_date > snapshot_date:
                continue
            candidate = CashSnapshotView(
                snapshot_date=row_date,
                account_type=account_type,
                cash_krw=float(row.get("cash_krw") or 0),
                note=row.get("note"),
            )
            if latest is None or candidate.snapshot_date > latest.snapshot_date:
                latest = candidate
        return latest

    stmt = (
        select(CashSnapshot)
        .where(
            CashSnapshot.account_type == account_type,
            CashSnapshot.snapshot_date <= snapshot_date,
        )
        .order_by(CashSnapshot.snapshot_date.desc())
        .limit(1)
    )
    row = session.execute(stmt).scalar_one_or_none()
    if row is None:
        return None
    return CashSnapshotView(
        snapshot_date=row.snapshot_date,
        account_type=row.account_type,
        cash_krw=row.cash_krw,
        note=row.note,
    )


def apply_cash_delta(
    session: Session,
    *,
    account_type: AccountType,
    snapshot_date: date,
    delta_krw: float,
    note: str | None = None,
) -> CashSnapshot | None:
    if abs(delta_krw) < 1e-9:
        return None

    base_snapshot = get_latest_cash_snapshot_on_or_before(
        session,
        account_type=account_type,
        snapshot_date=snapshot_date,
    )
    if base_snapshot is None:
        if delta_krw < 0:
            return None
        new_cash = delta_krw
    else:
        new_cash = base_snapshot.cash_krw + delta_krw

    if new_cash < 0:
        return None

    return upsert_cash_snapshot(
        session,
        snapshot_date=snapshot_date,
        account_type=account_type,
        cash_krw=new_cash,
        note=note,
    )
