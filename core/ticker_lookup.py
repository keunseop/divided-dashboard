from __future__ import annotations

from dataclasses import dataclass
from typing import List

from sqlalchemy import select

from core.db import db_session
from core.models import TickerMaster
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
