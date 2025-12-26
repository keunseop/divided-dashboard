from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from typing import List
from zipfile import ZipFile
import xml.etree.ElementTree as ET

import pandas as pd
import requests


class DartApiUnavailable(Exception):
    """Raised when OpenDART cannot be used (missing module, API key, or request failure)."""


@dataclass
class DartDividendRecord:
    ticker: str
    event_date: date
    amount: float
    currency: str = "KRW"
    year: int | None = None
    cash_yield_pct: float | None = None
    total_cash_dividend: float | None = None
    payout_ratio_pct: float | None = None
    frequency_hint: str | None = None
    source_note: str | None = None


class DartDividendFetcher:
    """Thin wrapper around OpenDartReader to retrieve dividend DPS information."""

    ALOT_MATTER_URL = "https://opendart.fss.or.kr/api/alotMatter.json"
    CORP_CODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml"
    REPRT_CODE = "11011"  # 사업보고서

    STOCK_KND_COMMON_HINTS = ["보통", "COMMON"]

    def __init__(self, api_key_path: str | Path | None = None) -> None:
        self.api_key_path = Path(api_key_path or "dart_api_key")
        self._api_key_cache: str | None = None
        self._corp_codes_loaded = False
        self._corp_code_by_stock: dict[str, str] = {}
        self._corp_code_by_name: dict[str, str] = {}

    def fetch_dividend_records(
        self,
        ticker: str,
        *,
        start_year: int | None = None,
        end_year: int | None = None,
    ) -> List[DartDividendRecord]:
        normalized = ticker.strip()
        if not normalized:
            return []
        corp_code = self._resolve_corp_code(normalized)
        if corp_code is None:
            raise DartApiUnavailable(f"{normalized}: DART 고유번호를 찾을 수 없습니다.")

        current_year = date.today().year
        start = max(start_year or (current_year - 10), 2000)
        end = end_year or current_year
        if end < start:
            end = start

        records: list[DartDividendRecord] = []
        for year in range(start, end + 1):
            df = self._fetch_alot_matter_dataframe(corp_code, year)
            if df is None or getattr(df, "empty", True):
                continue

            df = df.copy()
            for column in df.columns:
                if isinstance(column, str):
                    df[column] = df[column].astype(str).map(str.strip)

            year_records = self._convert_alot_rows(df, normalized, year)
            records.extend(year_records)

        return records

    def _fetch_alot_matter_dataframe(
        self, corp_code: str, year: int
    ) -> pd.DataFrame | None:
        api_key = self._load_api_key()
        try:
            response = requests.get(
                self.ALOT_MATTER_URL,
                params={
                    "crtfc_key": api_key,
                    "corp_code": corp_code,
                    "bsns_year": str(year),
                    "reprt_code": self.REPRT_CODE,
                },
                timeout=15,
            )
            response.raise_for_status()
        except Exception as exc:  # pragma: no cover - network errors
            raise DartApiUnavailable(f"DART 배당 공시를 조회할 수 없습니다: {exc}") from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise DartApiUnavailable("DART 배당 공시 응답을 JSON으로 파싱할 수 없습니다.") from exc

        status = data.get("status")
        if status != "000":
            if status == "013":
                return None
            message = data.get("message", "알 수 없는 오류")
            raise DartApiUnavailable(f"DART 배당 공시 오류({status}): {message}")

        rows = data.get("list")
        if not rows:
            return None

        df = pd.DataFrame(rows)

        if df is None or df.empty:
            return None
        return df

    def _load_api_key(self) -> str:
        if self._api_key_cache:
            return self._api_key_cache
        if not self.api_key_path.exists():
            raise DartApiUnavailable(
                f"DART API 키 파일({self.api_key_path})을 찾을 수 없습니다."
            )
        key = self.api_key_path.read_text(encoding="utf-8").strip()
        if not key:
            raise DartApiUnavailable(f"DART API 키 파일({self.api_key_path})에 값이 없습니다.")
        self._api_key_cache = key
        return key

    def _ensure_corp_codes_loaded(self) -> None:
        if self._corp_codes_loaded:
            return

        api_key = self._load_api_key()
        try:
            response = requests.get(
                self.CORP_CODE_URL,
                params={"crtfc_key": api_key},
                timeout=30,
            )
            response.raise_for_status()
        except Exception as exc:
            raise DartApiUnavailable(f"DART 고유번호 파일을 다운로드할 수 없습니다: {exc}") from exc

        try:
            with ZipFile(BytesIO(response.content)) as zf:
                xml_name = next((name for name in zf.namelist() if name.lower().endswith(".xml")), None)
                if not xml_name:
                    raise DartApiUnavailable("DART 고유번호 압축 파일에서 XML을 찾을 수 없습니다.")
                xml_bytes = zf.read(xml_name)
        except DartApiUnavailable:
            raise
        except Exception as exc:
            raise DartApiUnavailable(f"DART 고유번호 파일을 읽을 수 없습니다: {exc}") from exc

        try:
            root = ET.fromstring(xml_bytes)
        except Exception as exc:
            raise DartApiUnavailable(f"DART 고유번호 XML 파싱에 실패했습니다: {exc}") from exc

        for entry in root.findall("list"):
            corp_code = (entry.findtext("corp_code") or "").strip()
            stock_code = (entry.findtext("stock_code") or "").strip()
            corp_name = (entry.findtext("corp_name") or "").strip().upper()
            if corp_code and stock_code:
                self._corp_code_by_stock[stock_code] = corp_code
            if corp_code and corp_name:
                self._corp_code_by_name[corp_name] = corp_code

        self._corp_codes_loaded = True

    def _resolve_corp_code(self, ticker_or_name: str) -> str | None:
        self._ensure_corp_codes_loaded()
        stripped = ticker_or_name.strip().upper()
        digits = "".join(ch for ch in stripped if ch.isdigit())
        if digits:
            corp_code = self._corp_code_by_stock.get(digits)
            if corp_code:
                return corp_code
        corp_code = self._corp_code_by_name.get(stripped)
        if corp_code:
            return corp_code
        return None

    def _convert_alot_rows(
        self,
        df: pd.DataFrame,
        ticker: str,
        year: int,
    ) -> list[DartDividendRecord]:
        records: list[DartDividendRecord] = []
        if "se" not in df.columns:
            return records

        per_share_row = self._find_row(df, "주당 현금배당금", stock_filter=self._is_common_stock_kind)
        if per_share_row is None:
            return records

        amount = self._to_float(per_share_row.get("thstrm"))
        if amount is None or amount <= 0:
            return records

        event_date = self._extract_alot_date(per_share_row, year)

        cash_yield = self._to_float(
            self._find_row_value(df, "현금배당수익률", stock_filter=self._is_common_stock_kind)
        )
        if cash_yield is not None:
            cash_yield = float(cash_yield)

        payout_ratio = self._to_float(
            self._find_row_value(df, "(연결)현금배당성향", stock_filter=None)
        )
        if payout_ratio is None:
            payout_ratio = self._to_float(
                self._find_row_value(df, "현금배당성향", stock_filter=None)
            )

        total_cash_dividend = self._to_float(
            self._find_row_value(df, "현금배당금총액", stock_filter=None)
        )
        if total_cash_dividend is not None:
            total_cash_dividend *= 1_000_000  # 백만원 단위

        frequency_hint = self._infer_frequency(amount)

        records.append(
            DartDividendRecord(
                ticker=ticker,
                event_date=event_date,
                amount=amount,
                year=year,
                cash_yield_pct=cash_yield,
                total_cash_dividend=total_cash_dividend,
                payout_ratio_pct=payout_ratio,
                frequency_hint=frequency_hint,
                source_note="alotMatter",
            )
        )
        return records

    def _find_row(self, df: pd.DataFrame, keyword: str, *, stock_filter=None) -> pd.Series | None:
        normalized_keyword = self._normalize_text(keyword)
        for _, row in df.iterrows():
            se_value = self._normalize_text(row.get("se", ""))
            if normalized_keyword not in se_value:
                continue
            if stock_filter:
                stock_value = str(row.get("stock_knd") or "")
                if not stock_filter(stock_value):
                    continue
            return row
        return None

    def _find_row_value(self, df: pd.DataFrame, keyword: str, *, stock_filter=None):
        row = self._find_row(df, keyword, stock_filter=stock_filter)
        if row is None:
            return None
        return row.get("thstrm")

    @staticmethod
    def _normalize_text(value: str | None) -> str:
        if not value:
            return ""
        return str(value).replace(" ", "").strip().upper()

    def _is_common_stock_kind(self, value: str) -> bool:
        upper = value.upper()
        for hint in self.STOCK_KND_COMMON_HINTS:
            if hint in upper:
                return True
        if "PREF" in upper or "우선" in value:
            return False
        return True

    def _infer_frequency(self, annual_amount: float) -> str | None:
        if annual_amount <= 0:
            return None
        candidates = [
            (4, "분기배당(추정)"),
            (2, "반기배당(추정)"),
            (12, "월배당(추정)"),
            (1, "연 1회"),
        ]
        for divisor, label in candidates:
            portion = annual_amount / divisor
            if abs(portion - round(portion)) < 0.5:
                return label
        return None

    def _extract_alot_date(self, row: pd.Series, default_year: int) -> date:
        for column in ("thstrm_dt", "thstrm_dt_nm", "thstrm_dt_1", "thstrm_dt_2"):
            parsed = self._to_date(row.get(column))
            if parsed:
                return parsed.date()
        return date(default_year, 12, 31)

    @staticmethod
    def _to_float(value) -> float | None:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            cleaned = value.replace(",", "").replace("원", "").strip()
            if cleaned == "":
                return None
            try:
                return float(cleaned)
            except ValueError:
                return None
        return None

    @staticmethod
    def _to_date(value) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, (datetime, pd.Timestamp)):
            return value
        try:
            return pd.to_datetime(value, errors="coerce")
        except Exception:
            return None
