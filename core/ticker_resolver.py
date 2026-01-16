from __future__ import annotations

from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.kis.domestic_quotes import fetch_domestic_price_now, fetch_domestic_symbol_info
from core.pykis_adapter import fetch_pykis_stock_name
from core.models import TickerMaster
from core.utils import infer_market_from_ticker, normalize_ticker


def resolve_missing_ticker_names(session: Session, tickers: Iterable[str]) -> dict[str, str]:
    normalized = {normalize_ticker(t) for t in tickers if normalize_ticker(t)}
    if not normalized:
        return {}

    rows = session.execute(
        select(TickerMaster.ticker, TickerMaster.name_ko).where(TickerMaster.ticker.in_(normalized))
    ).all()
    name_map = {ticker: name for ticker, name in rows}
    missing = [ticker for ticker in normalized if _needs_refined_name(name_map.get(ticker))]

    changed = False
    for ticker in missing:
        market = infer_market_from_ticker(ticker)
        if market != "KR":
            continue
        pykis_name, _ = fetch_pykis_stock_name(ticker)
        name_ko = str(pykis_name or "").strip()
        try:
            data = fetch_domestic_price_now(ticker)
        except Exception:
            data = {}
        if not name_ko:
            name_ko = str(data.get("name_ko") or "").strip()
        if _needs_refined_name(name_ko):
            try:
                info = fetch_domestic_symbol_info(ticker)
            except Exception:
                info = {}
            refined = str(info.get("name_ko") or "").strip()
            if refined:
                name_ko = refined
        if not name_ko:
            continue

        obj = session.get(TickerMaster, ticker)
        if obj:
            if obj.name_ko != name_ko:
                obj.name_ko = name_ko
                changed = True
            if not obj.market:
                obj.market = market
                changed = True
            if not obj.currency:
                obj.currency = "KRW"
                changed = True
        else:
            session.add(
                TickerMaster(
                    ticker=ticker,
                    name_ko=name_ko,
                    market=market,
                    currency="KRW",
                )
            )
            changed = True
        name_map[ticker] = name_ko

    if changed:
        session.flush()

    return name_map


def _needs_refined_name(name_ko: str | None) -> bool:
    if not name_ko:
        return True
    normalized = str(name_ko).strip().upper()
    return normalized in {"ETF", "ETN", "ETP"}
