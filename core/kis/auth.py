from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from core.secrets import get_secret

_AUTH_LOCK = threading.Lock()
_AUTH_INSTANCES: dict[str, object] = {}
_DEFAULT_SECRET_PATH = Path(__file__).resolve().parents[2] / "var" / "kis_secret.json"


def get_access_token(*, env: str | None = None, force_refresh: bool = False) -> str:
    auth = _get_auth(env)
    if force_refresh:
        _refresh_auth(auth)
    token = _extract_access_token(auth, env)
    if not token:
        raise RuntimeError("pykis token provider did not return an access token.")
    return token


def _get_auth(env: str | None) -> object:
    env_key = (env or get_secret("KIS_ENV") or "default").strip().lower() or "default"
    cached = _AUTH_INSTANCES.get(env_key)
    if cached is not None:
        return cached
    with _AUTH_LOCK:
        cached = _AUTH_INSTANCES.get(env_key)
        if cached is None:
            cached = _build_auth(env_key)
            _AUTH_INSTANCES[env_key] = cached
    return cached


def _build_auth(env_key: str) -> object:
    Api, DomainInfo = _import_public_api()
    auth_payload = _load_auth_payload(env_key)
    key_info = {
        "appkey": auth_payload["appkey"],
        "appsecret": auth_payload["appsecret"],
    }
    domain_kind = "virtual" if auth_payload["virtual"] else "real"
    return Api(key_info, domain_info=DomainInfo(kind=domain_kind))


def _import_public_api() -> tuple[type, type]:
    import importlib
    import sys

    errors: list[str] = []
    candidates = (
        "pykis.public_api",
        "pykis.api",
        "pykis.kis",
        "pykis",
        "python_kis.public_api",
        "python_kis",
    )
    for module_name in candidates:
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            errors.append(f"{module_name}: {exc}")
            continue
        Api = getattr(module, "Api", None)
        DomainInfo = getattr(module, "DomainInfo", None)
        if Api is not None and DomainInfo is not None:
            return Api, DomainInfo

    raise RuntimeError(
        "KIS auth library is required but could not be imported. "
        "Install python-kis (preferred) or pykis. "
        f"python={sys.executable}. error={'; '.join(errors) or 'module not found'}"
    )


def _load_auth_payload(env_key: str) -> dict[str, Any]:
    secret_path = (get_secret("KIS_PYKIS_SECRET_PATH") or "").strip()
    if not secret_path and _DEFAULT_SECRET_PATH.exists():
        secret_path = str(_DEFAULT_SECRET_PATH)

    app_key = (get_secret("KIS_APP_KEY") or "").strip()
    app_secret = (get_secret("KIS_APP_SECRET") or "").strip()
    virtual_from_file: bool | None = None

    if secret_path:
        loaded = _load_auth_from_file(secret_path)
        if loaded:
            app_key = loaded.get("appkey") or app_key
            app_secret = loaded.get("secretkey") or app_secret
            virtual_from_file = loaded.get("virtual")

    if not (app_key and app_secret):
        raise RuntimeError(
            "Missing KIS auth config. Provide KIS_PYKIS_SECRET_PATH or "
            "KIS_APP_KEY/KIS_APP_SECRET."
        )

    virtual_override = _read_bool(get_secret("KIS_VIRTUAL"))
    if virtual_override is None:
        if env_key in {"paper", "vts", "mock"}:
            virtual = True
        elif virtual_from_file is not None:
            virtual = bool(virtual_from_file)
        else:
            virtual = False
    else:
        virtual = virtual_override

    return {
        "appkey": app_key,
        "appsecret": app_secret,
        "virtual": virtual,
    }


def _load_auth_from_file(path: str) -> dict[str, Any] | None:
    try:
        from pykis.client.auth import KisAuth  # type: ignore
    except Exception:
        KisAuth = None

    if KisAuth is not None:
        try:
            auth = KisAuth.load(path)
            return {
                "appkey": getattr(auth, "appkey", None),
                "secretkey": getattr(auth, "secretkey", None),
                "virtual": getattr(auth, "virtual", None),
            }
        except Exception:
            pass

    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            return None
        return {
            "appkey": data.get("appkey"),
            "secretkey": data.get("secretkey"),
            "virtual": data.get("virtual"),
        }
    except Exception:
        return None


def _extract_access_token(auth: object, env: str | None) -> str | None:
    if _is_pykis_client(auth):
        token_obj = _get_pykis_token(auth, env)
        return _normalize_token(token_obj)
    if _is_public_api_client(auth):
        return _get_public_api_token(auth)

    for attr in ("access_token", "token", "accessToken", "token_info", "tokenInfo", "_token"):
        try:
            value = getattr(auth, attr)
        except Exception:
            value = None
        token = _normalize_token(value)
        if token:
            return token

    for name in (
        "get_access_token",
        "access_token",
        "get_token",
        "token",
        "token_info",
        "get_token_info",
        "request_token",
        "issue_token",
        "create_token",
        "refresh_token",
    ):
        method = getattr(auth, name, None)
        if not callable(method):
            continue
        try:
            value = method()
        except TypeError:
            continue
        except Exception:
            continue
        token = _normalize_token(value)
        if token:
            return token
    return None


def _normalize_token(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return _strip_bearer(value.strip())
    if isinstance(value, dict):
        for key in ("access_token", "token", "accessToken", "value"):
            token = value.get(key)
            if isinstance(token, str) and token.strip():
                return _strip_bearer(token.strip())
    for attr in ("access_token", "token", "accessToken", "value"):
        try:
            token = getattr(value, attr)
        except Exception:
            token = None
        if isinstance(token, str) and token.strip():
            return _strip_bearer(token.strip())
    return None


def _refresh_auth(auth: object) -> None:
    if _is_public_api_client(auth):
        try:
            auth.create_token()
            return
        except Exception:
            pass
    for name in ("refresh", "refresh_token", "request_token", "update_token", "create_token"):
        method = getattr(auth, name, None)
        if not callable(method):
            continue
        try:
            method()
            return
        except Exception:
            continue


def _is_public_api_client(auth: object) -> bool:
    module = getattr(type(auth), "__module__", "")
    name = getattr(type(auth), "__name__", "")
    return module.startswith("pykis.public_api") and name == "Api"


def _get_public_api_token(auth: object) -> str | None:
    try:
        if getattr(auth, "need_authentication")():
            getattr(auth, "create_token")()
        return _normalize_token(getattr(auth, "token"))
    except Exception:
        return None


def _is_pykis_client(auth: object) -> bool:
    module = getattr(type(auth), "__module__", "")
    name = getattr(type(auth), "__name__", "")
    return module.startswith("pykis.kis") and name == "PyKis"


def _get_pykis_token(auth: object, env: str | None) -> object | None:
    env_key = (env or get_secret("KIS_ENV") or "").strip().lower()
    use_virtual = env_key in {"paper", "vts", "mock"}
    try:
        return getattr(auth, "primary_token") if use_virtual else getattr(auth, "token")
    except Exception:
        return None


def _strip_bearer(token: str) -> str:
    prefix = "bearer "
    if token.lower().startswith(prefix):
        return token[len(prefix) :].strip()
    return token


def _read_bool(raw: str | None) -> bool | None:
    if raw is None:
        return None
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "y", "on"}:
        return True
    if value in {"0", "false", "no", "n", "off"}:
        return False
    return None
