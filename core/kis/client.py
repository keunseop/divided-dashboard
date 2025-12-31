from __future__ import annotations

from typing import Any

import requests

from core.kis.auth import get_access_token
from core.kis.settings import load_kis_config


def _build_headers(
    *,
    access_token: str,
    app_key: str,
    app_secret: str,
    custtype: str | None,
    tr_id: str | None,
    personalseckey: str | None,
    extra_headers: dict[str, str] | None,
) -> dict[str, str]:
    headers = {
        "authorization": f"Bearer {access_token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "content-type": "application/json; charset=utf-8",
    }
    if custtype:
        headers["custtype"] = custtype
    if tr_id:
        headers["tr_id"] = tr_id
    if personalseckey:
        headers["personalseckey"] = personalseckey
    if extra_headers:
        headers.update(extra_headers)
    return headers


def kis_request(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    tr_id: str | None = None,
    env: str | None = None,
    timeout: int = 15,
) -> dict[str, Any]:
    config = load_kis_config(env)
    access_token = get_access_token(env=config.env)
    url = f"{config.base_url}{path}"

    req_headers = _build_headers(
        access_token=access_token,
        app_key=config.app_key,
        app_secret=config.app_secret,
        custtype=config.custtype,
        tr_id=tr_id,
        personalseckey=config.personalseckey,
        extra_headers=headers,
    )
    resp = requests.request(
        method=method.upper(),
        url=url,
        headers=req_headers,
        params=params,
        json=json,
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()

    if isinstance(data, dict) and data.get("rt_cd") not in (None, "0", 0):
        msg = data.get("msg1") or data.get("msg")
        raise RuntimeError(f"KIS API error ({data.get('rt_cd')}): {msg or data}")
    return data
