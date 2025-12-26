from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import AccountType, HoldingPosition


@dataclass
class HoldingPositionView:
    ticker: str
    account_type: AccountType
    quantity: float
    avg_buy_price_krw: float
    total_cost_krw: float


def get_positions(
    session: Session,
    *,
    account_type: AccountType | None = None,
    tickers: Sequence[str] | None = None,
) -> list[HoldingPositionView]:
    stmt = select(HoldingPosition).order_by(HoldingPosition.account_type, HoldingPosition.ticker)
    if account_type:
        stmt = stmt.where(HoldingPosition.account_type == account_type)
    if tickers:
        stmt = stmt.where(HoldingPosition.ticker.in_([t.upper() for t in tickers]))

    rows = session.execute(stmt).scalars().all()
    return [
        HoldingPositionView(
            ticker=row.ticker,
            account_type=row.account_type,
            quantity=row.quantity,
            avg_buy_price_krw=row.avg_buy_price_krw,
            total_cost_krw=row.total_cost_krw,
        )
        for row in rows
        if row.quantity > 0
    ]


def apply_buy(
    session: Session,
    *,
    ticker: str,
    account_type: AccountType,
    buy_quantity: float,
    buy_price_krw: float,
    note: str | None = None,
    source: str = "manual",
) -> HoldingPosition:
    if buy_quantity <= 0:
        raise ValueError("매수 수량은 0보다 커야 합니다.")
    if buy_price_krw <= 0:
        raise ValueError("매수 단가는 0보다 커야 합니다.")

    ticker_norm = ticker.strip().upper()
    stmt = select(HoldingPosition).where(
        HoldingPosition.ticker == ticker_norm,
        HoldingPosition.account_type == account_type,
    )
    position = session.execute(stmt).scalar_one_or_none()

    added_cost = buy_quantity * buy_price_krw
    if position:
        new_qty = position.quantity + buy_quantity
        new_cost = position.total_cost_krw + added_cost
        position.quantity = new_qty
        position.total_cost_krw = new_cost
        position.avg_buy_price_krw = new_cost / new_qty if new_qty else 0.0
        if note:
            position.note = note
        position.source = source or position.source
        return position

    new_position = HoldingPosition(
        ticker=ticker_norm,
        account_type=account_type,
        quantity=buy_quantity,
        avg_buy_price_krw=buy_price_krw,
        total_cost_krw=added_cost,
        note=note,
        source=source or "manual",
    )
    session.add(new_position)
    return new_position
