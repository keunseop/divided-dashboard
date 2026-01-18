from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any


def get_secret(name: str) -> str | None:
    """Fetch a secret from Streamlit configuration or environment variables."""
    try:
        import streamlit as st  # type: ignore
    except Exception:
        st = None  # type: ignore

    if st is not None and hasattr(st, "secrets"):
        value = st.secrets.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()

    value = _get_toml_secret(name)
    if isinstance(value, str) and value.strip():
        return value.strip()

    env_value = os.environ.get(name)
    if env_value and env_value.strip():
        return env_value.strip()
    return None


@lru_cache(maxsize=1)
def _load_toml_secrets() -> dict[str, Any]:
    secrets_path = Path(__file__).resolve().parents[1] / ".streamlit" / "secrets.toml"
    if not secrets_path.exists():
        return {}
    try:
        import tomllib
    except Exception:
        return {}
    try:
        return tomllib.loads(secrets_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _get_toml_secret(name: str) -> Any:
    data = _load_toml_secrets()
    return data.get(name)
