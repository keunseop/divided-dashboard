from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd

from core.kis.client import kis_request
from core.kis.settings import get_kis_setting

_MARKET_EXCD = {
    "US": "NAS",
    "NAS": "NAS",
    "NASDAQ": "NAS",
    "NASD": "NAS",
    "NYSE": "NYS",
    "NYS": "NYS",
    "AMEX": "AMS",
    "AMS": "AMS",
}


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


def _normalize_market(market: str) -> str:
    key = market.strip().upper()
    return _MARKET_EXCD.get(key, key)


def _market_candidates(market: str | None = None) -> list[str]:
    if not market or market.upper() in {"", "US", "AUTO"}:
        raw = get_kis_setting("KIS_OVERSEAS_MARKET_PRIORITY")
        if raw:
            items = [item.strip() for item in raw.split(",") if item.strip()]
            if items:
                return [_normalize_market(item) for item in items]
        return ["NAS", "NYS", "AMS"]
    return [_normalize_market(market)]


def _get_overseas_tr_id(env: str) -> str:
    if env == "paper":
        return get_kis_setting("KIS_TR_ID_OVERSEAS_PRICE_PAPER", "HHDFS00000300") or "HHDFS00000300"
    return get_kis_setting("KIS_TR_ID_OVERSEAS_PRICE", "HHDFS00000300") or "HHDFS00000300"


def _pick_output(data: dict) -> dict:
    if isinstance(data.get("output"), dict):
        return data["output"]
    if isinstance(data.get("output1"), dict):
        return data["output1"]
    if isinstance(data.get("output2"), dict):
        return data["output2"]
    return data


def fetch_overseas_price_now(market: str, ticker: str, *, env: str | None = None) -> dict:
    excd = _normalize_market(market)
    symbol = ticker.strip().upper()
    auth_param = get_kis_setting("KIS_AUTH") or ""

    params = {
        "AUTH": auth_param,
        "EXCD": excd,
        "SYMB": symbol,
    }
    path = get_kis_setting("KIS_OVERSEAS_PRICE_PATH", "/uapi/overseas-price/v1/quotations/price")
    tr_id = _get_overseas_tr_id(env or "prod")
    data = kis_request(
        "GET",
        path,
        params=params,
        tr_id=tr_id,
        env=env,
    )
    output = _pick_output(data)

    return {
        "ticker": symbol,
        "market": excd,
        "last": _to_float(output.get("last") or output.get("clos") or output.get("ovrs_prpr")),
        "change": _to_float(output.get("diff") or output.get("prdy_vrss")),
        "change_rate": _to_float(output.get("rate") or output.get("prdy_ctrt")),
        "volume": _to_int(output.get("tvol") or output.get("volume")),
        "currency": (
            output.get("curr")
            or output.get("currency")
            or output.get("crcy_cd")
            or "USD"
        ),
        "time": output.get("tr_time") or output.get("trade_time") or output.get("last_time"),
        "as_of": datetime.now(),
        "raw": output,
    }


def _get_overseas_history_tr_id(env: str) -> str:
    if env == "paper":
        return get_kis_setting("KIS_TR_ID_OVERSEAS_HISTORY_PAPER", "HHDFS76240000") or "HHDFS76240000"
    return get_kis_setting("KIS_TR_ID_OVERSEAS_HISTORY", "HHDFS76240000") or "HHDFS76240000"


def _pick_history_output(data: dict) -> list[dict]:
    for key in ("output2", "output1", "output"):
        value = data.get(key)
        if isinstance(value, list):
            return value
    return []


def _parse_overseas_history(rows: list[dict]) -> pd.DataFrame:
    records: list[dict] = []
    for row in rows:
        date_raw = row.get("xymd") or row.get("date") or row.get("stck_bsop_date")
        if not date_raw:
            continue
        try:
            parsed_date = datetime.strptime(str(date_raw), "%Y%m%d").date()
        except ValueError:
            parsed_date = pd.to_datetime(date_raw).date()

        records.append(
            {
                "date": parsed_date,
                "open": _to_float(row.get("open") or row.get("stck_oprc") or row.get("ovrs_oprc")),
                "high": _to_float(row.get("high") or row.get("stck_hgpr") or row.get("ovrs_hgpr")),
                "low": _to_float(row.get("low") or row.get("stck_lwpr") or row.get("ovrs_lwpr")),
                "close": _to_float(row.get("close") or row.get("clos") or row.get("ovrs_prpr")),
                "volume": _to_int(row.get("tvol") or row.get("volume") or row.get("trdvol")),
            }
        )

    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    df = df.dropna(subset=["date", "close"]).sort_values("date")
    return df


def _fetch_overseas_history_for_exchange(
    excd: str,
    ticker: str,
    *,
    period: str,
    start: date,
    end: date,
    auth: str,
    modp: str,
    tr_id: str,
    env: str | None,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    period_map = {"D": "0", "W": "1", "M": "2"}
    gubn = period_map.get(period.upper(), "0")
    path = get_kis_setting("KIS_OVERSEAS_HISTORY_PATH", "/uapi/overseas-price/v1/quotations/dailyprice")

    cursor = min(end, date.today())
    max_calls = int(get_kis_setting("KIS_OVERSEAS_HISTORY_MAX_CALLS", "60") or 60)

    while cursor >= start and max_calls > 0:
        params = {
            "AUTH": auth,
            "EXCD": excd,
            "SYMB": ticker,
            "GUBN": gubn,
            "BYMD": cursor.strftime("%Y%m%d"),
            "MODP": modp,
        }
        data = kis_request(
            "GET",
            path,
            params=params,
            tr_id=tr_id,
            env=env,
        )
        rows = _pick_history_output(data)
        frame = _parse_overseas_history(rows)
        if frame.empty:
            break
        frames.append(frame)
        min_date = frame["date"].min()
        if not isinstance(min_date, date):
            break
        if min_date <= start:
            break
        cursor = min_date - timedelta(days=1)
        max_calls -= 1

    if not frames:
        return pd.DataFrame()
    merged = pd.concat(frames, ignore_index=True)
    merged = merged.drop_duplicates(subset=["date"])
    merged = merged[(merged["date"] >= start) & (merged["date"] <= end)]
    merged = merged.sort_values("date").reset_index(drop=True)
    return merged


def fetch_overseas_price_history(
    market: str | None,
    ticker: str,
    *,
    period: str = "D",
    start: date,
    end: date,
    env: str | None = None,
) -> pd.DataFrame:
    symbol = ticker.strip().upper()
    auth_param = get_kis_setting("KIS_AUTH") or ""
    modp = get_kis_setting("KIS_OVERSEAS_HISTORY_MODP", "1") or "1"
    tr_id = _get_overseas_history_tr_id(env or "prod")

    for candidate in _market_candidates(market):
        frame = _fetch_overseas_history_for_exchange(
            candidate,
            symbol,
            period=period,
            start=start,
            end=end,
            auth=auth_param,
            modp=modp,
            tr_id=tr_id,
            env=env,
        )
        if not frame.empty:
            return frame
    return pd.DataFrame()
