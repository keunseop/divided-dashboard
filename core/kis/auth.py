from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import requests

from core.kis.settings import load_kis_config

TOKEN_FILE = Path(__file__).resolve().parents[2] / "var" / "kis_token.json"


def _load_cached_token(env: str) -> dict[str, Any] | None:
    if not TOKEN_FILE.exists():
        return None
    try:
        payload = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None

    if payload.get("env") != env:
        return None
    if not payload.get("access_token"):
        return None
    return payload


def _save_cached_token(env: str, data: dict[str, Any]) -> None:
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {"env": env, **data}
    TOKEN_FILE.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def _is_token_valid(payload: dict[str, Any]) -> bool:
    expired_at = payload.get("expired_at")
    if not isinstance(expired_at, (int, float)):
        return False
    return int(time.time()) < int(expired_at)


def get_access_token(*, env: str | None = None, force_refresh: bool = False) -> str:
    config = load_kis_config(env)
    cached = _load_cached_token(config.env)
    if cached and not force_refresh and _is_token_valid(cached):
        return str(cached["access_token"])

    url = f"{config.base_url}/oauth2/tokenP"
    payload = {
        "grant_type": "client_credentials",
        "appkey": config.app_key,
        "appsecret": config.app_secret,
    }
    resp = requests.post(url, json=payload, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"KIS access_token missing in response: {data}")

    expires_in = data.get("expires_in")
    try:
        expires_in = int(expires_in)
    except Exception:
        expires_in = 60 * 60 * 24
    issued_at = int(time.time())
    expired_at = issued_at + max(expires_in - 60, 60)

    cache_payload = {
        "access_token": token,
        "issued_at": issued_at,
        "expired_at": expired_at,
        "expires_in": expires_in,
    }
    _save_cached_token(config.env, cache_payload)
    return str(token)
