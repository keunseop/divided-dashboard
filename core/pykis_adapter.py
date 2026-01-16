from __future__ import annotations

import importlib
import inspect
import pkgutil
from functools import lru_cache

from core.secrets import get_secret

_LAST_PYKIS_ERROR: str | None = None


def fetch_pykis_stock_name(ticker: str) -> tuple[str | None, str | None]:
    client = _get_pykis_client()
    if client is None:
        return None, None
    try:
        stock = client.stock(ticker)
    except Exception:
        return None, None

    name = _safe_getattr(stock, "name")
    info = _safe_getattr(stock, "info")
    info_name = _safe_getattr(info, "name")
    market_name = _safe_getattr(info, "market_name")

    resolved_name = _first_text(name, info_name)
    resolved_market = _first_text(market_name)
    return resolved_name, resolved_market


def debug_pykis_stock(ticker: str) -> dict[str, object]:
    info: dict[str, object] = {
        "ticker": ticker,
        "import_ok": False,
        "client_ready": False,
        "client_type": None,
        "client_error": None,
        "stock_error": None,
        "name": None,
        "market_name": None,
    }

    try:
        import pykis  # type: ignore
    except Exception as exc:
        info["client_error"] = f"import_error: {exc}"
        return info

    info["import_ok"] = True
    info["module_attrs"] = _pick_kis_attrs(pykis)
    info["module_dir_sample"] = _pick_dir_sample(pykis)
    info["module_file"] = getattr(pykis, "__file__", None)
    info["module_version"] = getattr(pykis, "__version__", None)
    info["module_has_stock"] = hasattr(pykis, "stock")
    info["module_submodules"] = _list_submodules(pykis)
    public_api = _import_optional("pykis.public_api")
    if public_api is not None:
        info["public_api_has_stock"] = hasattr(public_api, "stock")
        info["public_api_dir_sample"] = _pick_dir_sample(public_api)
        info["public_api_attrs"] = _pick_kis_attrs(public_api)
    client = _get_pykis_client()
    if client is None:
        info["client_error"] = _LAST_PYKIS_ERROR or "pykis client init failed"
        return info

    info["client_ready"] = True
    info["client_type"] = type(client).__name__
    try:
        stock = client.stock(ticker)
    except Exception as exc:
        info["stock_error"] = str(exc)
        return info

    name = _safe_getattr(stock, "name")
    info["name"] = _first_text(name)
    info_obj = _safe_getattr(stock, "info")
    info["market_name"] = _first_text(_safe_getattr(info_obj, "market_name"))
    return info


def _first_text(*values: object) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _safe_getattr(obj: object, name: str) -> object | None:
    if obj is None:
        return None
    return getattr(obj, name, None)


@lru_cache(maxsize=1)
def _get_pykis_client() -> object | None:
    global _LAST_PYKIS_ERROR
    _LAST_PYKIS_ERROR = None
    try:
        import pykis  # type: ignore
    except Exception:
        _LAST_PYKIS_ERROR = "pykis import failed"
        return None

    module_client = getattr(pykis, "kis", None)
    if module_client is not None and hasattr(module_client, "stock"):
        return module_client
    if hasattr(pykis, "stock"):
        return pykis

    errors: list[str] = []
    client = _try_public_api_client(errors)
    if client is not None and hasattr(client, "stock"):
        return client
    for name in ("Kis", "PyKis", "KIS", "Client"):
        cls = getattr(pykis, name, None)
        if cls is None:
            continue
        client = _try_build_client(cls, pykis, errors)
        if client is not None and hasattr(client, "stock"):
            return client

    for module_name in ("pykis.kis", "pykis.client", "pykis.api", "pykis.core", "pykis.public_api"):
        try:
            mod = importlib.import_module(module_name)
        except Exception:
            continue
        module_client = getattr(mod, "kis", None)
        if module_client is not None and hasattr(module_client, "stock"):
            return module_client
        if hasattr(mod, "stock"):
            return mod
        for name in ("Kis", "PyKis", "KIS", "Client"):
            cls = getattr(mod, name, None)
            if cls is None:
                continue
            client = _try_build_client(cls, mod, errors)
            if client is not None and hasattr(client, "stock"):
                return client
    _LAST_PYKIS_ERROR = "; ".join(errors) if errors else "pykis client builder not found"
    return None


def _try_build_client(cls: type, module: object, errors: list[str]) -> object | None:
    for method in ("from_env", "from_config", "from_envvar", "load"):
        builder = getattr(cls, method, None)
        if builder is not None:
            try:
                return builder()
            except Exception:
                errors.append(f"{cls.__name__}.{method} failed")

    for method in ("from_env", "from_config", "load"):
        builder = getattr(module, method, None)
        if builder is not None:
            try:
                return builder()
            except Exception:
                errors.append(f"pykis.{method} failed")

    try:
        sig = inspect.signature(cls)
    except Exception:
        errors.append(f"{cls.__name__} signature unavailable")
        return None

    kwargs: dict[str, object] = {}
    app_key = get_secret("KIS_APP_KEY")
    app_secret = get_secret("KIS_APP_SECRET")
    user_id = get_secret("KIS_USER_ID") or get_secret("KIS_ID")
    account = (
        get_secret("KIS_ACCOUNT")
        or get_secret("KIS_ACCOUNT_NO")
        or get_secret("KIS_ACCOUNT_NUMBER")
        or get_secret("KIS_ACCOUNT_NUM")
    )
    keep_token_raw = get_secret("KIS_KEEP_TOKEN")
    env = (get_secret("KIS_ENV") or "").strip().lower()
    is_paper = env in {"paper", "vts", "mock"}
    keep_token = None
    if keep_token_raw is not None:
        keep_token = keep_token_raw.strip().lower() in {"1", "true", "yes", "y", "on"}

    for param in sig.parameters.values():
        name = param.name.lower()
        if name in {"id", "user_id", "userid", "login_id"} and user_id:
            kwargs[param.name] = user_id
        elif name in {"app_key", "appkey", "key"} and app_key:
            kwargs[param.name] = app_key
        elif name in {"app_secret", "appsecret", "secret", "secretkey"} and app_secret:
            kwargs[param.name] = app_secret
        elif name in {"account", "account_no", "account_number", "account_num", "acct", "acct_no"} and account:
            kwargs[param.name] = account
        elif name in {"keep_token", "keep", "save_token", "persist_token"} and keep_token is not None:
            kwargs[param.name] = keep_token
        elif name in {"virtual", "paper", "is_paper", "is_virtual", "mock", "is_mock", "sandbox"}:
            kwargs[param.name] = is_paper

    try:
        return cls(**kwargs)
    except Exception as exc:
        errors.append(f"{cls.__name__} init failed: {exc}")
        return None


def _try_public_api_client(errors: list[str]) -> object | None:
    public_api = _import_optional("pykis.public_api")
    if public_api is None:
        errors.append("pykis.public_api import failed")
        return None

    KisAuth = getattr(public_api, "KisAuth", None)
    PyKis = getattr(public_api, "PyKis", None)
    if KisAuth is None or PyKis is None:
        errors.append("pykis.public_api missing KisAuth/PyKis")
        return None

    secret_path = get_secret("KIS_PYKIS_SECRET_PATH") or ""
    keep_token = _read_bool(get_secret("KIS_KEEP_TOKEN"))
    if secret_path:
        try:
            auth = KisAuth.load(secret_path)
            return PyKis(auth, keep_token=keep_token) if keep_token is not None else PyKis(auth)
        except Exception as exc:
            errors.append(f"KisAuth.load failed: {exc}")

    app_key = get_secret("KIS_APP_KEY")
    app_secret = get_secret("KIS_APP_SECRET")
    user_id = get_secret("KIS_USER_ID") or get_secret("KIS_ID")
    account = (
        get_secret("KIS_ACCOUNT")
        or get_secret("KIS_ACCOUNT_NO")
        or get_secret("KIS_ACCOUNT_NUMBER")
        or get_secret("KIS_ACCOUNT_NUM")
    )
    virtual = _read_bool(get_secret("KIS_VIRTUAL"))
    if virtual is None:
        env = (get_secret("KIS_ENV") or "").strip().lower()
        virtual = env in {"paper", "vts", "mock"}

    if not (user_id and app_key and app_secret and account):
        errors.append("KisAuth config missing (id/appkey/secret/account)")
        return None

    try:
        auth = KisAuth(
            id=user_id,
            appkey=app_key,
            secretkey=app_secret,
            account=account,
            virtual=bool(virtual),
        )
        if keep_token is None:
            return PyKis(auth)
        return PyKis(auth, keep_token=keep_token)
    except Exception as exc:
        errors.append(f"KisAuth init failed: {exc}")
        return None


def _pick_kis_attrs(module: object) -> list[str]:
    try:
        names = dir(module)
    except Exception:
        return []
    keep: list[str] = []
    for name in names:
        lower = name.lower()
        if "kis" in lower or "stock" in lower:
            keep.append(name)
    return sorted(keep)[:30]


def _pick_dir_sample(module: object) -> list[str]:
    try:
        names = dir(module)
    except Exception:
        return []
    return sorted(names)[:50]


def _list_submodules(module: object) -> list[str]:
    try:
        pkg_path = getattr(module, "__path__", None)
        if not pkg_path:
            return []
    except Exception:
        return []
    names: list[str] = []
    for info in pkgutil.iter_modules(pkg_path):
        names.append(info.name)
        if len(names) >= 50:
            break
    return sorted(names)


def _import_optional(name: str) -> object | None:
    try:
        return importlib.import_module(name)
    except Exception:
        return None


def _read_bool(raw: str | None) -> bool | None:
    if raw is None:
        return None
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "y", "on"}:
        return True
    if value in {"0", "false", "no", "n", "off"}:
        return False
    return None
