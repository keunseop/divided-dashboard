from __future__ import annotations

import re
from typing import Any, Iterable

from core.firestore_reader import (
    get_collection_path,
    get_firestore_client,
    get_root_collection_path,
    is_firestore_enabled,
    list_dividends,
)


def _safe_doc_id(value: str) -> str:
    if not value:
        return ""
    return re.sub(r"[^A-Za-z0-9_\-]", "_", value)


def _chunked(items: list[tuple[str, dict[str, Any]]], size: int) -> Iterable[list[tuple[str, dict[str, Any]]]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _write_batch(collection_path: str, docs: list[tuple[str, dict[str, Any]]]) -> int:
    if not docs:
        return 0
    db = get_firestore_client()
    batch = db.batch()
    for doc_id, data in docs:
        if not doc_id:
            continue
        ref = db.document(f"{collection_path}/{doc_id}")
        batch.set(ref, data, merge=True)
    batch.commit()
    return len(docs)


def upsert_dividends_from_df(df, *, sync_mode: bool) -> tuple[int, int, int]:
    if not is_firestore_enabled():
        raise RuntimeError("Firestore is not enabled.")

    rows = df.to_dict("records")
    incoming_ids = {row["rowId"] for row in rows}

    docs: list[tuple[str, dict[str, Any]]] = []
    for row in rows:
        row_id = row["rowId"]
        payload = {
            "row_id": row_id,
            "pay_date": row["payDate"],
            "year": int(row["year"]),
            "month": int(row["month"]),
            "ticker": row["ticker"],
            "currency": row["currency"],
            "fx_rate": row.get("fxRate"),
            "gross_dividend": float(row["grossDividend"]),
            "tax": row.get("tax"),
            "net_dividend": row.get("netDividend"),
            "krw_gross": float(row["krwGross"]),
            "krw_net": row.get("krwNet"),
            "account_type": row["accountType"],
            "source": "excel",
            "archived": False,
        }
        docs.append((_safe_doc_id(row_id), payload))

    collection = get_collection_path("dividends")
    inserted = 0
    updated = 0
    for chunk in _chunked(docs, 400):
        _write_batch(collection, chunk)
    inserted = len(docs)

    archived_candidates = 0
    if sync_mode:
        existing = list_dividends()
        updates: list[tuple[str, dict[str, Any]]] = []
        for row in existing:
            if row.get("source") != "excel":
                continue
            if row.get("archived"):
                continue
            row_id = row.get("row_id")
            if row_id and row_id not in incoming_ids:
                updates.append((_safe_doc_id(row_id), {"archived": True}))
        for chunk in _chunked(updates, 400):
            _write_batch(collection, chunk)
        archived_candidates = len(updates)

    return inserted, updated, archived_candidates


def upsert_positions(records: list[dict[str, Any]]) -> tuple[int, int]:
    if not is_firestore_enabled():
        raise RuntimeError("Firestore is not enabled.")
    docs: list[tuple[str, dict[str, Any]]] = []
    for row in records:
        ticker = row.get("ticker")
        account_type = row.get("account_type")
        doc_id = _safe_doc_id(f"{ticker}_{account_type}") if account_type else _safe_doc_id(str(ticker))
        docs.append((doc_id, row))
    collection = get_collection_path("positions")
    for chunk in _chunked(docs, 400):
        _write_batch(collection, chunk)
    return len(docs), 0


def upsert_trades(records: list[dict[str, Any]]) -> tuple[int, int]:
    if not is_firestore_enabled():
        raise RuntimeError("Firestore is not enabled.")
    docs: list[tuple[str, dict[str, Any]]] = []
    for idx, row in enumerate(records):
        external_id = row.get("external_id")
        base = external_id or f"{row.get('trade_date')}_{row.get('ticker')}_{row.get('account_type')}_{idx}"
        doc_id = _safe_doc_id(str(base))
        docs.append((doc_id, row))
    collection = get_collection_path("trades")
    for chunk in _chunked(docs, 400):
        _write_batch(collection, chunk)
    return len(docs), 0


def upsert_portfolio_snapshots(records: list[dict[str, Any]]) -> tuple[int, int]:
    if not is_firestore_enabled():
        raise RuntimeError("Firestore is not enabled.")
    docs: list[tuple[str, dict[str, Any]]] = []
    for row in records:
        external_id = row.get("external_id")
        base = external_id or f"{row.get('snapshot_date')}_{row.get('account_type')}"
        doc_id = _safe_doc_id(str(base))
        docs.append((doc_id, row))
    collection = get_collection_path("snapshots")
    for chunk in _chunked(docs, 400):
        _write_batch(collection, chunk)
    return len(docs), 0


def upsert_cash_snapshots(records: list[dict[str, Any]]) -> tuple[int, int]:
    if not is_firestore_enabled():
        raise RuntimeError("Firestore is not enabled.")
    docs: list[tuple[str, dict[str, Any]]] = []
    for row in records:
        base = f"{row.get('snapshot_date')}_{row.get('account_type')}"
        doc_id = _safe_doc_id(str(base))
        docs.append((doc_id, row))
    collection = get_collection_path("cash_snapshots")
    for chunk in _chunked(docs, 400):
        _write_batch(collection, chunk)
    return len(docs), 0


def upsert_valuation_snapshots(records: list[dict[str, Any]]) -> tuple[int, int]:
    if not is_firestore_enabled():
        raise RuntimeError("Firestore is not enabled.")
    docs: list[tuple[str, dict[str, Any]]] = []
    for row in records:
        base = f"{row.get('valuation_date')}_{row.get('account_type')}"
        doc_id = _safe_doc_id(str(base))
        docs.append((doc_id, row))
    collection = get_collection_path("valuation_snapshots")
    for chunk in _chunked(docs, 400):
        _write_batch(collection, chunk)
    return len(docs), 0


def upsert_tickers(records: list[dict[str, Any]]) -> tuple[int, int]:
    if not is_firestore_enabled():
        raise RuntimeError("Firestore is not enabled.")
    docs: list[tuple[str, dict[str, Any]]] = []
    for row in records:
        ticker = row.get("ticker")
        if not ticker:
            continue
        doc_id = _safe_doc_id(str(ticker))
        docs.append((doc_id, row))
    collection = get_root_collection_path("tickers")
    for chunk in _chunked(docs, 400):
        _write_batch(collection, chunk)
    return len(docs), 0
