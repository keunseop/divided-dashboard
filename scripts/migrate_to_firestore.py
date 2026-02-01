#!/usr/bin/env python3
"""Migrate core portfolio data from SQLite to Firestore.

Focused tables:
- holding_positions -> users/{user_id}/portfolios/{portfolio_id}/positions/{ticker}
- holding_lots      -> users/{user_id}/portfolios/{portfolio_id}/trades/{trade_id}
- dividend_events   -> users/{user_id}/portfolios/{portfolio_id}/dividends/{row_id}
- portfolio_snapshots -> users/{user_id}/portfolios/{portfolio_id}/snapshots/{snapshot_id}

Other tables (price_cache, ticker_master, dividend_cache, dividend_dps_cache) are optional and skipped.
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


def _require_firebase() -> Any:
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore
    except Exception as exc:  # pragma: no cover - environment-specific
        raise SystemExit(
            "firebase_admin is required. Install with: python -m pip install firebase-admin"
        ) from exc
    return firebase_admin, credentials, firestore


def _connect_sqlite(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise SystemExit(f"SQLite DB not found: {path}")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _fetch_rows(conn: sqlite3.Connection, sql: str) -> List[sqlite3.Row]:
    cur = conn.cursor()
    cur.execute(sql)
    return cur.fetchall()


def _chunked(items: List[Tuple[str, Dict[str, Any]]], size: int) -> Iterable[List[Tuple[str, Dict[str, Any]]]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _write_batch(db: Any, full_collection_path: str, docs: List[Tuple[str, Dict[str, Any]]], dry_run: bool) -> int:
    if dry_run:
        return len(docs)
    batch = db.batch()
    for doc_id, data in docs:
        doc_ref = db.document(f"{full_collection_path}/{doc_id}")
        batch.set(doc_ref, data, merge=True)
    batch.commit()
    return len(docs)


def _migrate_positions(conn: sqlite3.Connection) -> List[Tuple[str, Dict[str, Any]]]:
    rows = _fetch_rows(
        conn,
        """
        SELECT ticker, account_type, quantity, avg_buy_price_krw, total_cost_krw,
               note, source, updated_at
        FROM holding_positions
        """,
    )
    docs: List[Tuple[str, Dict[str, Any]]] = []
    for r in rows:
        data = {
            "ticker": r["ticker"],
            "account_type": r["account_type"],
            "quantity": r["quantity"],
            "avg_buy_price_krw": r["avg_buy_price_krw"],
            "total_cost_krw": r["total_cost_krw"],
            "note": r["note"],
            "source": r["source"],
            "updated_at": r["updated_at"],
        }
        docs.append((r["ticker"], data))
    return docs


def _migrate_trades(conn: sqlite3.Connection) -> List[Tuple[str, Dict[str, Any]]]:
    rows = _fetch_rows(
        conn,
        """
        SELECT id, external_id, trade_date, ticker, account_type, side, quantity, price,
               currency, fx_rate, krw_amount, fees_krw, note, source, created_at, updated_at,
               price_krw, amount_krw
        FROM holding_lots
        """,
    )
    docs: List[Tuple[str, Dict[str, Any]]] = []
    for r in rows:
        doc_id = r["external_id"] or str(r["id"])
        data = {
            "external_id": r["external_id"],
            "trade_date": r["trade_date"],
            "ticker": r["ticker"],
            "account_type": r["account_type"],
            "side": r["side"],
            "quantity": r["quantity"],
            "price": r["price"],
            "currency": r["currency"],
            "fx_rate": r["fx_rate"],
            "krw_amount": r["krw_amount"],
            "fees_krw": r["fees_krw"],
            "note": r["note"],
            "source": r["source"],
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
            "price_krw": r["price_krw"],
            "amount_krw": r["amount_krw"],
        }
        docs.append((doc_id, data))
    return docs


def _migrate_dividends(conn: sqlite3.Connection) -> List[Tuple[str, Dict[str, Any]]]:
    rows = _fetch_rows(
        conn,
        """
        SELECT row_id, pay_date, year, month, ticker, currency, fx_rate, gross_dividend,
               tax, net_dividend, krw_gross, krw_net, account_type, source, archived,
               raw_text, created_at, updated_at
        FROM dividend_events
        """,
    )
    docs: List[Tuple[str, Dict[str, Any]]] = []
    for r in rows:
        data = {
            "row_id": r["row_id"],
            "pay_date": r["pay_date"],
            "year": r["year"],
            "month": r["month"],
            "ticker": r["ticker"],
            "currency": r["currency"],
            "fx_rate": r["fx_rate"],
            "gross_dividend": r["gross_dividend"],
            "tax": r["tax"],
            "net_dividend": r["net_dividend"],
            "krw_gross": r["krw_gross"],
            "krw_net": r["krw_net"],
            "account_type": r["account_type"],
            "source": r["source"],
            "archived": bool(r["archived"]),
            "raw_text": r["raw_text"],
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
        }
        docs.append((r["row_id"], data))
    return docs


def _migrate_snapshots(conn: sqlite3.Connection) -> List[Tuple[str, Dict[str, Any]]]:
    rows = _fetch_rows(
        conn,
        """
        SELECT id, snapshot_date, account_type, contributed_krw, cash_krw, valuation_krw,
               note, source, created_at, updated_at
        FROM portfolio_snapshots
        """,
    )
    docs: List[Tuple[str, Dict[str, Any]]] = []
    for r in rows:
        doc_id = str(r["id"])
        data = {
            "snapshot_date": r["snapshot_date"],
            "account_type": r["account_type"],
            "contributed_krw": r["contributed_krw"],
            "cash_krw": r["cash_krw"],
            "valuation_krw": r["valuation_krw"],
            "note": r["note"],
            "source": r["source"],
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
        }
        docs.append((doc_id, data))
    return docs


def _init_firestore(service_account: Path | None):
    firebase_admin, credentials, firestore = _require_firebase()
    if not firebase_admin._apps:
        if service_account:
            cred = credentials.Certificate(str(service_account))
            firebase_admin.initialize_app(cred)
        else:
            firebase_admin.initialize_app()
    return firestore.client()


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate SQLite data to Firestore")
    parser.add_argument("--sqlite", default="var/dividends.sqlite3", help="Path to SQLite DB")
    parser.add_argument("--user-id", required=True, help="Firestore user id")
    parser.add_argument("--portfolio-id", required=True, help="Firestore portfolio id")
    parser.add_argument("--service-account", help="Service account JSON path (optional)")
    parser.add_argument("--dry-run", action="store_true", help="Print counts only")
    args = parser.parse_args()

    db_path = Path(args.sqlite)
    service_account = Path(args.service_account) if args.service_account else None

    conn = _connect_sqlite(db_path)
    try:
        positions = _migrate_positions(conn)
        trades = _migrate_trades(conn)
        dividends = _migrate_dividends(conn)
        snapshots = _migrate_snapshots(conn)
    finally:
        conn.close()

    if args.dry_run:
        print("dry-run counts")
        print("positions", len(positions))
        print("trades", len(trades))
        print("dividends", len(dividends))
        print("snapshots", len(snapshots))
        return

    db = _init_firestore(service_account)
    base_path = f"users/{args.user_id}/portfolios/{args.portfolio_id}"

    total = 0
    for label, collection, docs in [
        ("positions", f"{base_path}/positions", positions),
        ("trades", f"{base_path}/trades", trades),
        ("dividends", f"{base_path}/dividends", dividends),
        ("snapshots", f"{base_path}/snapshots", snapshots),
    ]:
        count = 0
        for chunk in _chunked(docs, 400):
            count += _write_batch(db, collection, chunk, dry_run=False)
        print(f"{label}: {count} docs")
        total += count

    print(f"done: {total} docs migrated")


if __name__ == "__main__":
    main()
