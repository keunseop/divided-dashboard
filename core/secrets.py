from __future__ import annotations

import os


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

    env_value = os.environ.get(name)
    if env_value and env_value.strip():
        return env_value.strip()
    return None
