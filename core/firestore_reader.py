from __future__ import annotations

from datetime import date, datetime
from functools import lru_cache
from typing import Any, Iterable, Sequence

from core.secrets import get_bool_secret, get_secret


class FirestoreConfigError(RuntimeError):
    pass


def is_firestore_enabled() -> bool:
    return get_bool_secret("FIRESTORE_ENABLED", default=False)


def _require_firebase():
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore
    except Exception as exc:  # pragma: no cover - environment-specific
        raise FirestoreConfigError(
            "firebase_admin is required. Install with: python -m pip install firebase-admin"
        ) from exc
    return firebase_admin, credentials, firestore


def _get_firestore_config() -> tuple[str, str, str | None]:
    user_id = get_secret("FIRESTORE_USER_ID")
    portfolio_id = get_secret("FIRESTORE_PORTFOLIO_ID")
    if not user_id or not portfolio_id:
        raise FirestoreConfigError(
            "FIRESTORE_USER_ID and FIRESTORE_PORTFOLIO_ID are required when FIRESTORE_ENABLED=1."
        )
    service_account = get_secret("FIRESTORE_SERVICE_ACCOUNT")
    return user_id, portfolio_id, service_account


@lru_cache(maxsize=1)
def _get_firestore_client():
    firebase_admin, credentials, firestore = _require_firebase()
    user_id, portfolio_id, service_account = _get_firestore_config()
    if not firebase_admin._apps:
        if service_account:
            cred = credentials.Certificate(service_account)
            firebase_admin.initialize_app(cred)
        else:
            firebase_admin.initialize_app()
    return firestore.client()


def get_firestore_client():
    return _get_firestore_client()


def get_collection_path(collection: str) -> str:
    return _collection_path(collection)


def get_root_collection_path(collection: str) -> str:
    return _root_collection_path(collection)


def _collection_path(collection: str) -> str:
    user_id, portfolio_id, _ = _get_firestore_config()
    return f"users/{user_id}/portfolios/{portfolio_id}/{collection}"


def _root_collection_path(collection: str) -> str:
    return collection


def _stream_collection(path: str) -> Iterable[Any]:
    db = _get_firestore_client()
    return db.collection(path).stream()


def list_positions() -> list[dict[str, Any]]:
    docs = _stream_collection(_collection_path("positions"))
    results: list[dict[str, Any]] = []
    for doc in docs:
        data = doc.to_dict() or {}
        if "ticker" not in data:
            data["ticker"] = doc.id
        results.append(data)
    return results


def list_trades() -> list[dict[str, Any]]:
    docs = _stream_collection(_collection_path("trades"))
    results: list[dict[str, Any]] = []
    for doc in docs:
        data = doc.to_dict() or {}
        if "trade_id" not in data:
            data["trade_id"] = doc.id
        results.append(data)
    return results


def list_dividends() -> list[dict[str, Any]]:
    docs = _stream_collection(_collection_path("dividends"))
    results: list[dict[str, Any]] = []
    for doc in docs:
        data = doc.to_dict() or {}
        if "row_id" not in data:
            data["row_id"] = doc.id
        results.append(data)
    return results


def list_portfolio_snapshots() -> list[dict[str, Any]]:
    docs = _stream_collection(_collection_path("snapshots"))
    results: list[dict[str, Any]] = []
    for doc in docs:
        data = doc.to_dict() or {}
        if "snapshot_id" not in data:
            data["snapshot_id"] = doc.id
        results.append(data)
    return results


def list_ticker_master(tickers: Sequence[str] | None = None) -> dict[str, dict[str, Any]]:
    docs = _stream_collection(_root_collection_path("tickers"))
    results: dict[str, dict[str, Any]] = {}
    filter_set = {t.upper() for t in tickers} if tickers else None
    for doc in docs:
        data = doc.to_dict() or {}
        ticker = (data.get("ticker") or doc.id or "").upper()
        if not ticker:
            continue
        if filter_set and ticker not in filter_set:
            continue
        results[ticker] = data
    return results


def list_cash_snapshots() -> list[dict[str, Any]]:
    docs = _stream_collection(_collection_path("cash_snapshots"))
    results: list[dict[str, Any]] = []
    for doc in docs:
        data = doc.to_dict() or {}
        if "snapshot_id" not in data:
            data["snapshot_id"] = doc.id
        results.append(data)
    return results


def list_valuation_snapshots() -> list[dict[str, Any]]:
    docs = _stream_collection(_collection_path("valuation_snapshots"))
    results: list[dict[str, Any]] = []
    for doc in docs:
        data = doc.to_dict() or {}
        if "valuation_id" not in data:
            data["valuation_id"] = doc.id
        results.append(data)
    return results


def parse_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except Exception:
            return None
    return None
