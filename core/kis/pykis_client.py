from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from core.secrets import get_secret


def _normalize_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return None


def is_pykis_enabled() -> bool:
    flag = _normalize_bool(get_secret("PYKIS_ENABLED"))
    return True if flag is None else flag


def _secret_path() -> Path | None:
    secret_path = get_secret("PYKIS_SECRET_PATH") or get_secret("PYKIS_SECRET_JSON")
    if not secret_path:
        return None
    return Path(secret_path).expanduser()


def is_pykis_configured() -> bool:
    if _secret_path():
        return True
    required = ["PYKIS_ID", "PYKIS_ACCOUNT", "PYKIS_APPKEY", "PYKIS_SECRETKEY"]
    return all(get_secret(name) for name in required)


@lru_cache(maxsize=1)
def get_pykis():
    try:
        from pykis import PyKis  # type: ignore
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("pykis 라이브러리가 설치되어 있지 않습니다.") from exc

    secret_path = _secret_path()
    if secret_path:
        return PyKis(str(secret_path), keep_token=True)

    kis_id = get_secret("PYKIS_ID")
    account = get_secret("PYKIS_ACCOUNT")
    appkey = get_secret("PYKIS_APPKEY")
    secretkey = get_secret("PYKIS_SECRETKEY")

    if not all([kis_id, account, appkey, secretkey]):
        raise RuntimeError("PYKIS 설정값이 부족합니다. PYKIS_SECRET_PATH 또는 개별 키를 설정해 주세요.")

    return PyKis(
        id=kis_id,
        account=account,
        appkey=appkey,
        secretkey=secretkey,
        keep_token=True,
    )
