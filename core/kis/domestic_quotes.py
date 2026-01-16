from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd

from core.kis.client import kis_request
from core.kis.settings import get_kis_setting


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def _to_int(value: object) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text.replace(",", "")))
    except ValueError:
        return None


def _get_domestic_tr_id(env: str) -> str:
    if env == "paper":
        return get_kis_setting("KIS_TR_ID_DOMESTIC_PRICE_PAPER", "FHKST01010100") or "FHKST01010100"
    return get_kis_setting("KIS_TR_ID_DOMESTIC_PRICE", "FHKST01010100") or "FHKST01010100"


def _get_domestic_symbol_info_tr_id(env: str) -> str | None:
    if env == "paper":
        return get_kis_setting("KIS_TR_ID_DOMESTIC_SYMBOL_INFO_PAPER")
    return get_kis_setting("KIS_TR_ID_DOMESTIC_SYMBOL_INFO")


def _get_domestic_symbol_info_path() -> str | None:
    return get_kis_setting("KIS_DOMESTIC_SYMBOL_INFO_PATH")


def fetch_domestic_price_now(symbol_6: str, *, env: str | None = None) -> dict:
    symbol = symbol_6.strip()
    if symbol.startswith("A") and symbol[1:].isdigit():
        symbol = symbol[1:]

    params = {
        "fid_cond_mrkt_div_code": "J",
        "fid_input_iscd": symbol,
    }
    tr_id = _get_domestic_tr_id(env or "prod")
    data = kis_request(
        "GET",
        "/uapi/domestic-stock/v1/quotations/inquire-price",
        params=params,
        tr_id=tr_id,
        env=env,
    )
    output = _pick_price_output(data)
    name_ko = _extract_name_ko(output)

    return {
        "symbol": symbol,
        "name_ko": name_ko,
        "last": _to_float(output.get("stck_prpr") or output.get("last")),
        "change": _to_float(output.get("prdy_vrss") or output.get("diff")),
        "change_rate": _to_float(output.get("prdy_ctrt") or output.get("diff_rate")),
        "volume": _to_int(output.get("acml_vol") or output.get("volume")),
        "open": _to_float(output.get("stck_oprc") or output.get("open")),
        "high": _to_float(output.get("stck_hgpr") or output.get("high")),
        "low": _to_float(output.get("stck_lwpr") or output.get("low")),
        "as_of": datetime.now(),
        "raw": output,
    }


def fetch_domestic_symbol_info(symbol_6: str, *, env: str | None = None) -> dict:
    path = _get_domestic_symbol_info_path()
    tr_id = _get_domestic_symbol_info_tr_id(env or "prod")
    if not path or not tr_id:
        return {}

    symbol = symbol_6.strip()
    if symbol.startswith("A") and symbol[1:].isdigit():
        symbol = symbol[1:]

    params = {
        "fid_cond_mrkt_div_code": "J",
        "fid_input_iscd": symbol,
    }
    data = kis_request(
        "GET",
        path,
        params=params,
        tr_id=tr_id,
        env=env,
    )
    output = _pick_price_output(data)
    return {
        "symbol": symbol,
        "name_ko": _extract_name_ko(output),
        "raw": output,
    }


def _extract_name_ko(output: dict) -> str | None:
    candidates = [
        "hts_kor_isnm",
        "kor_isnm",
        "stck_name",
        "itms_nm",
        "prdt_name",
        "prdt_abrv_name",
        "name",
        "stock_name",
        "itm_name",
    ]
    for key in candidates:
        value = output.get(key)
        if value:
            text = str(value).strip()
            if text:
                return text
    for key, value in output.items():
        if not isinstance(value, str):
            continue
        text = value.strip()
        if not text:
            continue
        lower = key.lower()
        if "name" in lower or "isnm" in lower:
            if any(bad in lower for bad in ("bstp", "inds", "sector", "market")):
                continue
            return text
    for key, value in output.items():
        if not isinstance(value, str):
            continue
        text = value.strip()
        if not text:
            continue
        lower = key.lower()
        if "name" in lower or "isnm" in lower:
            return text
    return None


def _pick_price_output(data: dict) -> dict:
    for key in ("output", "output1", "output2"):
        value = data.get(key)
        if isinstance(value, dict):
            return value
        if isinstance(value, list) and value:
            first = value[0]
            if isinstance(first, dict):
                return first
    return {}


def _get_domestic_history_tr_id(env: str) -> str:
    if env == "paper":
        return get_kis_setting("KIS_TR_ID_DOMESTIC_HISTORY_PAPER", "FHKST03010100") or "FHKST03010100"
    return get_kis_setting("KIS_TR_ID_DOMESTIC_HISTORY", "FHKST03010100") or "FHKST03010100"


def _pick_history_output(data: dict) -> list[dict]:
    for key in ("output2", "output1", "output"):
        value = data.get(key)
        if isinstance(value, list):
            return value
    return []


def _parse_domestic_history(rows: list[dict]) -> pd.DataFrame:
    records: list[dict] = []
    for row in rows:
        date_raw = row.get("stck_bsop_date") or row.get("date") or row.get("xymd")
        if not date_raw:
            continue
        try:
            parsed_date = datetime.strptime(str(date_raw), "%Y%m%d").date()
        except ValueError:
            parsed_date = pd.to_datetime(date_raw).date()

        records.append(
            {
                "date": parsed_date,
                "open": _to_float(row.get("stck_oprc") or row.get("open")),
                "high": _to_float(row.get("stck_hgpr") or row.get("high")),
                "low": _to_float(row.get("stck_lwpr") or row.get("low")),
                "close": _to_float(row.get("stck_clpr") or row.get("close")),
                "volume": _to_int(row.get("acml_vol") or row.get("volume")),
            }
        )

    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    df = df.dropna(subset=["date", "close"]).sort_values("date")
    return df


def fetch_domestic_price_history(
    symbol_6: str,
    *,
    period: str = "D",
    start: date,
    end: date,
    env: str | None = None,
) -> pd.DataFrame:
    symbol = symbol_6.strip()
    if symbol.startswith("A") and symbol[1:].isdigit():
        symbol = symbol[1:]

    chunk_days = int(get_kis_setting("KIS_HISTORY_CHUNK_DAYS", "300") or 300)
    step = timedelta(days=chunk_days)
    cursor = start
    frames: list[pd.DataFrame] = []

    while cursor <= end:
        chunk_end = min(cursor + step, end)
        params = {
            "fid_cond_mrkt_div_code": "J",
            "fid_input_iscd": symbol,
            "fid_input_date_1": cursor.strftime("%Y%m%d"),
            "fid_input_date_2": chunk_end.strftime("%Y%m%d"),
            "fid_period_div_code": period,
            "fid_org_adj_prc": "0",
        }
        data = kis_request(
            "GET",
            "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
            params=params,
            tr_id=_get_domestic_history_tr_id(env or "prod"),
            env=env,
        )
        rows = _pick_history_output(data)
        frame = _parse_domestic_history(rows)
        if not frame.empty:
            frames.append(frame)
        cursor = chunk_end + timedelta(days=1)

    if not frames:
        return pd.DataFrame()
    merged = pd.concat(frames, ignore_index=True)
    merged = merged.drop_duplicates(subset=["date"]).sort_values("date")
    return merged.reset_index(drop=True)
