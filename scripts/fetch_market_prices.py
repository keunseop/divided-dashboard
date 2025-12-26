#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path
from typing import Iterable, List

import FinanceDataReader as fdr
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SNAPSHOT = PROJECT_ROOT / "data" / "kr_price_snapshot.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch latest closing prices via FinanceDataReader and update local CSV outputs."
    )
    parser.add_argument(
        "--kr",
        nargs="+",
        metavar="TICKER",
        help="KR tickers (e.g., 005930). Latest price will be appended to the snapshot CSV.",
    )
    parser.add_argument(
        "--us",
        nargs="+",
        metavar="TICKER",
        help="US/global tickers (e.g., AAPL, TLTW). Prices are printed to stdout.",
    )
    parser.add_argument(
        "--snapshot",
        default=str(DEFAULT_SNAPSHOT),
        help=f"Path to KR snapshot CSV (default: {DEFAULT_SNAPSHOT})",
    )
    return parser.parse_args()


def fetch_latest_price(symbol: str, *, start: str | None = None) -> pd.Series:
    df = fdr.DataReader(symbol, start=start)
    if df is None or df.empty:
        raise ValueError(f"{symbol}: FinanceDataReader returned no rows.")
    cleaned = df.dropna(subset=["Close"])
    if cleaned.empty:
        raise ValueError(f"{symbol}: Close column is empty.")
    last_row = cleaned.iloc[-1].copy()
    last_row.name = cleaned.index[-1]
    return last_row


def update_snapshot(path: Path, rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    df.to_csv(path, index=False)


def main() -> None:
    args = parse_args()
    today = dt.date.today().strftime("%Y-%m-%d")

    snapshot_rows: List[dict] = []

    if args.kr:
        for ticker in args.kr:
            record = fetch_latest_price(ticker)
            as_of = record.name
            price = float(record["Close"])
            snapshot_rows.append(
                {
                    "ticker": ticker,
                    "price": price,
                    "currency": "KRW",
                    "as_of": as_of.strftime("%Y-%m-%d %H:%M") if hasattr(as_of, "strftime") else str(as_of),
                }
            )
            print(f"[KR] {ticker} ({today}) close: {price}")

        if snapshot_rows:
            update_snapshot(Path(args.snapshot), snapshot_rows)
            print(f"Saved {len(snapshot_rows)} KR entries to {args.snapshot}")

    if args.us:
        for ticker in args.us:
            record = fetch_latest_price(ticker, start=today)
            price = float(record["Close"])
            as_of = record.name
            print(f"[US] {ticker} close {price} ({as_of})")

    if not args.kr and not args.us:
        print("No tickers specified. Use --kr and/or --us.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
