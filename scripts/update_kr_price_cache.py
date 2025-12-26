#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import sys
from typing import List, Set

import FinanceDataReader as fdr
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db import db_session
from core.market_data import PriceQuote, _upsert_price_cache
from core.models import DividendEvent, TickerMaster
from core.utils import infer_market_from_ticker, normalize_ticker


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch latest KR ticker prices via FinanceDataReader and store them in price_cache."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional maximum number of tickers to process.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and print prices without writing to the database.",
    )
    return parser.parse_args()


def gather_kr_tickers(session: Session, limit: int | None = None) -> List[str]:
    tickers: Set[str] = set()

    event_rows = session.execute(
        select(DividendEvent.ticker)
        .where(DividendEvent.archived == False)
        .distinct()
    ).scalars().all()
    for ticker in event_rows:
        normalized = normalize_ticker(ticker)
        if normalized and infer_market_from_ticker(normalized) == "KR":
            tickers.add(normalized)

    ordered = sorted(tickers)
    if limit is not None:
        ordered = ordered[:limit]
    return ordered


def fetch_latest_price(ticker: str) -> PriceQuote:
    df = fdr.DataReader(ticker)
    if df is None or df.empty:
        raise ValueError(f"{ticker}: FinanceDataReader returned no rows.")

    cleaned = df.dropna(subset=["Close"])
    if cleaned.empty:
        raise ValueError(f"{ticker}: 'Close' column has no data.")

    last_row = cleaned.iloc[-1]
    idx = cleaned.index[-1]
    as_of = idx.to_pydatetime() if hasattr(idx, "to_pydatetime") else dt.datetime.now()

    return PriceQuote(
        ticker=ticker,
        price=float(last_row["Close"]),
        currency="KRW",
        as_of=as_of,
        source="FinanceDataReader",
    )


def main() -> None:
    args = parse_args()

    with db_session() as session:
        tickers = gather_kr_tickers(session, args.limit)
        if not tickers:
            print("No KR tickers found in the database.")
            return

        successes = 0
        failures: list[str] = []

        for ticker in tickers:
            try:
                quote = fetch_latest_price(ticker)
            except Exception as exc:
                failures.append(f"{ticker}: {exc}")
                continue

            print(f"[KR] {quote.ticker}: {quote.price:.2f} KRW (as of {quote.as_of})")
            if not args.dry_run:
                try:
                    _upsert_price_cache(session, quote)
                except Exception as exc:
                    failures.append(f"{ticker}: failed to store price ({exc})")
                    continue
            successes += 1

        if args.dry_run:
            print(f"Dry run complete. {successes} tickers fetched.")
        else:
            print(f"Completed: stored {successes} ticker prices in price_cache.")

        if failures:
            print("\nSome tickers failed:")
            for msg in failures:
                print(f" - {msg}")
            if not args.dry_run:
                print("Partial failures do not roll back successful entries.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(1)
