from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.firestore_reader import (
    is_firestore_enabled,
    list_positions as list_positions_firestore,
    list_trades as list_trades_firestore,
    parse_date,
)
from core.firestore_writer import upsert_trades as upsert_trades_firestore
from core.models import AccountType, HoldingLot, HoldingPosition, TickerMaster, TradeSide
from core.ticker_reader import get_ticker_meta_map
from core.ticker_resolver import resolve_missing_ticker_names
from core.utils import normalize_ticker


@dataclass
class HoldingPositionView:
    ticker: str
    name_ko: str | None
    account_type: AccountType
    quantity: float
    avg_buy_price_krw: float
    total_cost_krw: float
    realized_pnl_krw: float | None = None


def get_positions(
    session: Session,
    *,
    account_type: AccountType | None = None,
    tickers: Sequence[str] | None = None,
) -> list[HoldingPositionView]:
    if is_firestore_enabled():
        return _positions_from_firestore(session, account_type=account_type, tickers=tickers)

    if _has_lots(session):
        return _positions_from_lots(session, account_type=account_type, tickers=tickers)

    stmt = (
        select(HoldingPosition, TickerMaster.name_ko)
        .join(TickerMaster, TickerMaster.ticker == HoldingPosition.ticker, isouter=True)
        .order_by(HoldingPosition.account_type, HoldingPosition.ticker)
    )
    if account_type:
        stmt = stmt.where(HoldingPosition.account_type == account_type)
    if tickers:
        stmt = stmt.where(HoldingPosition.ticker.in_([t.upper() for t in tickers]))

    rows = session.execute(stmt).all()
    missing = {position.ticker for position, name_ko in rows if not name_ko}
    resolved = resolve_missing_ticker_names(session, missing) if missing else {}
    views: list[HoldingPositionView] = []
    for position, name_ko in rows:
        if position.quantity <= 0:
            continue
        views.append(
            HoldingPositionView(
                ticker=position.ticker,
                name_ko=name_ko or resolved.get(position.ticker),
                account_type=position.account_type,
                quantity=position.quantity,
                avg_buy_price_krw=position.avg_buy_price_krw,
                total_cost_krw=position.total_cost_krw,
                realized_pnl_krw=None,
            )
        )
    return views


def _positions_from_firestore(
    session: Session,
    *,
    account_type: AccountType | None,
    tickers: Sequence[str] | None,
) -> list[HoldingPositionView]:
    rows = list_positions_firestore()
    if not rows:
        return []

    normalized = [normalize_ticker(t) for t in (tickers or []) if normalize_ticker(t)]
    if account_type is not None:
        rows = [row for row in rows if row.get("account_type") == account_type.value]
    if normalized:
        allowed = set(normalized)
        rows = [row for row in rows if normalize_ticker(str(row.get("ticker", ""))) in allowed]

    ticker_meta = {}
    if rows:
        try:
            ticker_meta = get_ticker_meta_map(
                session,
                tickers=[row.get("ticker") for row in rows if row.get("ticker")],
            )
        except Exception:
            ticker_meta = {}

    views: list[HoldingPositionView] = []
    for row in rows:
        ticker = normalize_ticker(str(row.get("ticker", "")))
        if not ticker:
            continue
        qty = float(row.get("quantity") or 0)
        if qty <= 0:
            continue
        acct_value = row.get("account_type")
        account = AccountType(acct_value) if acct_value in AccountType._value2member_map_ else AccountType.TAXABLE
        name_ko = row.get("name_ko") or ticker_meta.get(ticker, {}).get("name_ko")
        total_cost = float(row.get("total_cost_krw") or 0)
        avg_price = float(row.get("avg_buy_price_krw") or (total_cost / qty if qty else 0))
        views.append(
            HoldingPositionView(
                ticker=ticker,
                name_ko=name_ko,
                account_type=account,
                quantity=qty,
                avg_buy_price_krw=avg_price,
                total_cost_krw=total_cost,
                realized_pnl_krw=None,
            )
        )

    views.sort(key=lambda v: (v.account_type.value, v.ticker))
    return views


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
    record_trade(
        session,
        trade_date=date.today(),
        ticker=ticker,
        account_type=account_type,
        side=TradeSide.BUY,
        quantity=buy_quantity,
        price=buy_price_krw,
        currency="KRW",
        fx_rate=1.0,
        note=note,
        source=source,
    )
    # 기존 호출부 호환을 위해 Dummy HoldingPosition 반환
    return HoldingPosition(
        ticker=normalize_ticker(ticker),
        account_type=account_type,
        quantity=buy_quantity,
        avg_buy_price_krw=buy_price_krw,
        total_cost_krw=buy_quantity * buy_price_krw,
        note=note,
        source=source or "manual",
    )


def apply_sell(
    session: Session,
    *,
    ticker: str,
    account_type: AccountType,
    sell_quantity: float,
    sell_price_krw: float,
    note: str | None = None,
    source: str = "manual",
) -> HoldingLot:
    return record_trade(
        session,
        trade_date=date.today(),
        ticker=ticker,
        account_type=account_type,
        side=TradeSide.SELL,
        quantity=sell_quantity,
        price=sell_price_krw,
        currency="KRW",
        fx_rate=1.0,
        note=note,
        source=source,
    )


def record_trade(
    session: Session,
    *,
    trade_date: date,
    ticker: str,
    account_type: AccountType,
    side: TradeSide,
    quantity: float,
    price: float,
    currency: str = "KRW",
    fx_rate: float | None = None,
    price_krw: float | None = None,
    note: str | None = None,
    source: str = "manual",
    external_id: str | None = None,
) -> HoldingLot:
    if quantity <= 0:
        raise ValueError("수량은 0보다 커야 합니다.")
    if price <= 0:
        raise ValueError("단가는 0보다 커야 합니다.")

    ticker_norm = normalize_ticker(ticker)
    if not ticker_norm:
        raise ValueError("유효한 티커를 입력해 주세요.")

    currency_norm = (currency or "KRW").upper()
    fx = fx_rate
    if currency_norm == "KRW":
        fx = fx or 1.0
    elif fx is None or fx <= 0:
        raise ValueError("KRW 이외 통화는 환율(fx_rate)이 필요합니다.")

    price_per_share_krw = price_krw or price * fx
    amount_krw = price_per_share_krw * quantity

    if is_firestore_enabled():
        payload = {
            "external_id": external_id,
            "trade_date": trade_date,
            "ticker": ticker_norm,
            "account_type": account_type.value,
            "side": side.value,
            "quantity": quantity,
            "price": price,
            "currency": currency_norm,
            "fx_rate": fx,
            "price_krw": price_per_share_krw,
            "amount_krw": amount_krw,
            "note": note,
            "source": source or "manual",
        }
        upsert_trades_firestore([payload])
        return HoldingLot(
            external_id=external_id,
            trade_date=trade_date,
            ticker=ticker_norm,
            account_type=account_type,
            side=side,
            quantity=quantity,
            price=price,
            currency=currency_norm,
            fx_rate=fx,
            price_krw=price_per_share_krw,
            amount_krw=amount_krw,
            note=note,
            source=source or "manual",
        )

    lot = HoldingLot(
        external_id=external_id,
        trade_date=trade_date,
        ticker=ticker_norm,
        account_type=account_type,
        side=side,
        quantity=quantity,
        price=price,
        currency=currency_norm,
        fx_rate=fx,
        price_krw=price_per_share_krw,
        amount_krw=amount_krw,
        note=note,
        source=source or "manual",
    )
    session.add(lot)
    return lot


def list_trades(
    session: Session,
    *,
    account_type: AccountType | None = None,
    ticker: str | None = None,
    limit: int = 500,
) -> list[HoldingLot]:
    if is_firestore_enabled():
        rows = list_trades_firestore()
        results: list[HoldingLot] = []
        normalized_ticker = normalize_ticker(ticker) if ticker else None
        for row in rows:
            if account_type and row.get("account_type") != account_type.value:
                continue
            row_ticker = normalize_ticker(str(row.get("ticker", "")))
            if normalized_ticker and row_ticker != normalized_ticker:
                continue
            trade_date = parse_date(row.get("trade_date"))
            if trade_date is None:
                continue
            results.append(
                HoldingLot(
                    external_id=row.get("external_id"),
                    trade_date=trade_date,
                    ticker=row_ticker,
                    account_type=AccountType(row.get("account_type") or AccountType.TAXABLE.value),
                    side=TradeSide(row.get("side") or TradeSide.BUY.value),
                    quantity=float(row.get("quantity") or 0),
                    price=float(row.get("price") or 0),
                    currency=row.get("currency") or "KRW",
                    fx_rate=float(row.get("fx_rate") or 1.0),
                    price_krw=float(row.get("price_krw") or 0),
                    amount_krw=float(row.get("amount_krw") or 0),
                    note=row.get("note"),
                    source=row.get("source") or "manual",
                )
            )
        results.sort(key=lambda r: (r.trade_date, r.ticker))
        return results[-limit:] if limit else results

    stmt = select(HoldingLot).order_by(HoldingLot.trade_date.desc(), HoldingLot.id.desc()).limit(limit)
    if account_type:
        stmt = stmt.where(HoldingLot.account_type == account_type)
    if ticker:
        stmt = stmt.where(HoldingLot.ticker == normalize_ticker(ticker))
    return session.execute(stmt).scalars().all()


def _has_lots(session: Session) -> bool:
    stmt = select(HoldingLot.id).limit(1)
    return session.execute(stmt).first() is not None


def _positions_from_lots(
    session: Session,
    *,
    account_type: AccountType | None,
    tickers: Sequence[str] | None,
) -> list[HoldingPositionView]:
    base_positions_stmt = (
        select(HoldingPosition)
        .where(HoldingPosition.quantity > 0)
        .order_by(HoldingPosition.account_type, HoldingPosition.ticker)
    )
    normalized: list[str] = []
    if account_type:
        base_positions_stmt = base_positions_stmt.where(HoldingPosition.account_type == account_type)
    if tickers:
        normalized = [normalize_ticker(t) for t in tickers if normalize_ticker(t)]
        if normalized:
            base_positions_stmt = base_positions_stmt.where(HoldingPosition.ticker.in_(normalized))
    base_positions = session.execute(base_positions_stmt).scalars().all()

    stmt = select(HoldingLot).order_by(HoldingLot.trade_date, HoldingLot.id)
    if account_type:
        stmt = stmt.where(HoldingLot.account_type == account_type)
    if tickers and normalized:
        stmt = stmt.where(HoldingLot.ticker.in_(normalized))
    lots = session.execute(stmt).scalars().all()

    states: dict[tuple[str, AccountType], dict[str, float]] = {}
    for position in base_positions:
        key = (position.ticker, position.account_type)
        states[key] = {
            "qty": position.quantity,
            "cost": position.total_cost_krw,
            "realized": 0.0,
        }

    if not lots:
        return _build_position_views(session, states)

    for lot in lots:
        key = (lot.ticker, lot.account_type)
        state = states.setdefault(
            key,
            {"qty": 0.0, "cost": 0.0, "realized": 0.0},
        )
        if lot.side == TradeSide.BUY:
            state["qty"] += lot.quantity
            state["cost"] += lot.amount_krw
        else:
            qty_before = state["qty"]
            if qty_before <= 0:
                raise ValueError(f"{lot.ticker}({lot.account_type.value}) 포지션이 없어 매도할 수 없습니다.")
            if lot.quantity - qty_before > 1e-8:
                raise ValueError(
                    f"{lot.ticker}({lot.account_type.value}) 매도 수량이 보유 수량을 초과합니다. "
                    f"보유 {qty_before}, 매도 {lot.quantity}"
                )
            avg_cost = state["cost"] / qty_before if qty_before else 0.0
            cost_reduction = avg_cost * lot.quantity
            state["qty"] = max(qty_before - lot.quantity, 0.0)
            state["cost"] = max(state["cost"] - cost_reduction, 0.0)
            proceeds = lot.price_krw * lot.quantity
            state["realized"] += proceeds - cost_reduction

    return _build_position_views(session, states)


def _build_position_views(session: Session, states: dict[tuple[str, AccountType], dict[str, float]]) -> list[HoldingPositionView]:
    ticker_set = {ticker for (ticker, _) in states.keys()}
    names = (
        session.execute(
            select(TickerMaster.ticker, TickerMaster.name_ko).where(TickerMaster.ticker.in_(ticker_set))
        ).all()
        if ticker_set
        else []
    )
    name_map = {ticker: name for ticker, name in names}
    missing = {ticker for ticker in ticker_set if ticker not in name_map}
    if missing:
        name_map.update(resolve_missing_ticker_names(session, missing))

    views: list[HoldingPositionView] = []
    for (ticker, acct), state in states.items():
        qty = state["qty"]
        if qty <= 0:
            continue
        cost = state["cost"]
        avg = cost / qty if qty else 0.0
        views.append(
            HoldingPositionView(
                ticker=ticker,
                name_ko=name_map.get(ticker),
                account_type=acct,
                quantity=qty,
                avg_buy_price_krw=avg,
                total_cost_krw=cost,
                realized_pnl_krw=state.get("realized") or 0.0,
            )
        )
    views.sort(key=lambda v: (v.account_type.value, v.ticker))
    return views
