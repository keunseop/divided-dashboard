from __future__ import annotations

import os
from dataclasses import dataclass


def _get_secret(name: str) -> str | None:
    try:
        import streamlit as st  # type: ignore
    except Exception:
        st = None  # type: ignore

    if st is not None and hasattr(st, "secrets"):
        value = st.secrets.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()

    env_value = os.environ.get(name)
    if env_value and env_value.strip():
        return env_value.strip()
    return None


def _normalize_env(value: str | None) -> str:
    normalized = (value or "prod").strip().lower()
    return "paper" if normalized in {"paper", "vts", "mock"} else "prod"


@dataclass(frozen=True)
class KISConfig:
    app_key: str
    app_secret: str
    env: str
    custtype: str
    base_url: str
    personalseckey: str | None = None


def load_kis_config(env: str | None = None) -> KISConfig:
    app_key = _get_secret("KIS_APP_KEY") or ""
    app_secret = _get_secret("KIS_APP_SECRET") or ""
    if not app_key or not app_secret:
        raise RuntimeError("KIS_APP_KEY/KIS_APP_SECRET is not configured in secrets or env.")

    env_value = _normalize_env(env or _get_secret("KIS_ENV"))
    custtype = _get_secret("KIS_CUSTTYPE") or "P"

    base_url_prod = _get_secret("KIS_BASE_URL_PROD") or "https://openapi.koreainvestment.com:9443"
    base_url_paper = _get_secret("KIS_BASE_URL_PAPER") or "https://openapivts.koreainvestment.com:29443"
    base_url = base_url_paper if env_value == "paper" else base_url_prod
    personal_key = _get_secret("KIS_PERSONAL_SECKEY")

    return KISConfig(
        app_key=app_key,
        app_secret=app_secret,
        env=env_value,
        custtype=custtype,
        base_url=base_url,
        personalseckey=personal_key,
    )


def get_kis_setting(name: str, default: str | None = None) -> str | None:
    value = _get_secret(name)
    if value is not None:
        return value
    return default
