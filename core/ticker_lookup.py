from __future__ import annotations

from dataclasses import dataclass
from typing import List

from sqlalchemy import select

from core.db import db_session
from core.firestore_reader import is_firestore_enabled, list_ticker_master
from core.models import TickerMaster
from core.ticker_resolver import resolve_missing_ticker_names
from core.utils import normalize_ticker


@dataclass(frozen=True)
class TickerSuggestion:
    ticker: str
    name_ko: str

    @property
    def display(self) -> str:
        return f"{self.name_ko} ({self.ticker})"


def find_ticker_candidates(query: str, limit: int = 20) -> List[TickerSuggestion]:
    term = (query or "").strip()
    normalized = normalize_ticker(term)

    if is_firestore_enabled():
        entries = list_ticker_master()
        suggestions: list[TickerSuggestion] = []
        seen: set[str] = set()

        if normalized and normalized in entries:
            name = entries[normalized].get("name_ko") or normalized
            suggestions.append(TickerSuggestion(ticker=normalized, name_ko=name))
            seen.add(normalized)

        for ticker, meta in entries.items():
            name_ko = meta.get("name_ko") or ""
            if term and term not in name_ko and term not in ticker:
                continue
            if ticker in seen:
                continue
            suggestions.append(TickerSuggestion(ticker=ticker, name_ko=name_ko or ticker))
            seen.add(ticker)
            if len(suggestions) >= limit:
                break

        return suggestions

    with db_session() as session:
        suggestions: list[TickerSuggestion] = []
        seen: set[str] = set()

        if normalized:
            exact = session.get(TickerMaster, normalized)
            if exact:
                suggestions.append(TickerSuggestion(ticker=exact.ticker, name_ko=exact.name_ko))
                seen.add(exact.ticker)

        stmt = None
        if term:
            stmt = (
                select(TickerMaster)
                .where(TickerMaster.name_ko.contains(term))
                .order_by(TickerMaster.name_ko.asc())
                .limit(limit)
            )
        if stmt is None:
            stmt = select(TickerMaster).order_by(TickerMaster.name_ko.asc()).limit(limit)

        rows = session.execute(stmt).scalars().all()
        for row in rows:
            if row.ticker in seen:
                continue
            suggestions.append(TickerSuggestion(ticker=row.ticker, name_ko=row.name_ko))
            seen.add(row.ticker)
            if len(suggestions) >= limit:
                return suggestions

        if term and normalized and _is_complete_ticker(normalized):
            resolved = resolve_missing_ticker_names(session, [normalized])
            if normalized in resolved:
                refreshed = session.get(TickerMaster, normalized)
                if refreshed and refreshed.ticker not in seen:
                    suggestions.append(
                        TickerSuggestion(ticker=refreshed.ticker, name_ko=refreshed.name_ko)
                    )
                    seen.add(refreshed.ticker)
                    return suggestions

        if term and normalized:
            stmt = (
                select(TickerMaster)
                .where(TickerMaster.ticker.contains(normalized))
                .order_by(TickerMaster.ticker.asc())
                .limit(limit)
            )
            rows = session.execute(stmt).scalars().all()
            for row in rows:
                if row.ticker in seen:
                    continue
                suggestions.append(TickerSuggestion(ticker=row.ticker, name_ko=row.name_ko))
                seen.add(row.ticker)
                if len(suggestions) >= limit:
                    break

    return suggestions


def _is_complete_ticker(value: str) -> bool:
    if not value:
        return False
    if value.isdigit():
        return len(value) == 6
    if value.startswith("A") and value[1:].isdigit():
        return len(value) == 7
    if len(value) == 6 and value[0].isdigit() and value.isalnum():
        return any(ch.isalpha() for ch in value)
    return False
