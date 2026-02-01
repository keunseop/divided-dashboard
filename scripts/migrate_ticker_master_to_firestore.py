#!/usr/bin/env python3
"""Migrate SQLite ticker_master to Firestore tickers collection."""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.firestore_reader import is_firestore_enabled
from core.firestore_writer import upsert_tickers


def _connect_sqlite(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise SystemExit(f"SQLite DB not found: {path}")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate ticker_master from SQLite to Firestore")
    parser.add_argument("--sqlite", default="var/dividends.sqlite3", help="Path to SQLite DB")
    args = parser.parse_args()

    if not is_firestore_enabled():
        raise SystemExit("FIRESTORE_ENABLED=1 is required.")

    conn = _connect_sqlite(Path(args.sqlite))
    try:
        rows = conn.execute("SELECT ticker, name_ko, market, currency FROM ticker_master").fetchall()
    finally:
        conn.close()

    records = []
    for row in rows:
        ticker = (row["ticker"] or "").strip().upper()
        if not ticker:
            continue
        records.append(
            {
                "ticker": ticker,
                "name_ko": row["name_ko"],
                "market": row["market"],
                "currency": row["currency"],
            }
        )

    inserted, updated = upsert_tickers(records)
    print(f"done: {len(records)} tickers uploaded (inserted={inserted}, updated={updated})")


if __name__ == "__main__":
    main()
