from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import pandas as pd
import yfinance as yf
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from core.dart_api import DartApiUnavailable, DartDividendFetcher
from core.kis.domestic_quotes import fetch_domestic_price_now
from core.kis.overseas_quotes import fetch_overseas_price_history, fetch_overseas_price_now
from core.kis.settings import get_kis_setting
from core.models import DividendCache, DividendEvent, PriceCache
from core.utils import normalize_market_code, normalize_ticker

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


@dataclass(slots=True)
class PriceQuote:
    ticker: str
    price: float
    currency: str
    as_of: datetime
    source: str


@dataclass(slots=True)
class DividendPoint:
    ticker: str
    event_date: date
    amount: float
    currency: str
    source: str


class MarketDataProvider(ABC):
    """Interface for pluggable market data providers."""

    name: str = "base"

    def get_current_price(self, session: Session, ticker: str) -> PriceQuote:
        normalized = normalize_ticker(ticker)
        quote = self._fetch_current_price(normalized)
        _upsert_price_cache(session, quote)
        return quote

    def get_dividend_history(
            self,
            session: Session,
            ticker: str,
            *,
            start_date: date | None = None,
            end_date: date | None = None,
    ) -> list[DividendPoint]:
        normalized = normalize_ticker(ticker)
        points = self._fetch_dividend_history(
            normalized,
            start_date=start_date,
            end_date=end_date,
        )
        _upsert_dividend_cache(session, points)
        return points

    @abstractmethod
    def _fetch_current_price(self, ticker: str) -> PriceQuote:
        raise NotImplementedError

    @abstractmethod
    def _fetch_dividend_history(
            self,
            ticker: str,
            *,
            start_date: date | None = None,
            end_date: date | None = None,
    ) -> list[DividendPoint]:
        raise NotImplementedError


PROVIDER_REGISTRY: Dict[str, MarketDataProvider] = {}


def register_market_provider(market_code: str, provider: MarketDataProvider) -> None:
    """Register/override a provider for the given market code (e.g., KR, US)."""
    normalized = normalize_market_code(market_code) or "US"
    PROVIDER_REGISTRY[normalized] = provider


def get_registered_provider(market_code: str | None) -> MarketDataProvider:
    normalized = normalize_market_code(market_code) or "US"
    provider = PROVIDER_REGISTRY.get(normalized)
    if provider:
        return provider
    fallback = PROVIDER_REGISTRY.get("US")
    if fallback:
        return fallback
    raise RuntimeError("No market data providers are registered.")


class BaseYFinanceProvider(MarketDataProvider):
    """Shared helper for yfinance-backed providers with multi-symbol fallback."""

    name = "yfinance"
    default_currency = "USD"

    def _candidate_symbols(self, ticker: str) -> list[str]:
        return [ticker]

    def _fetch_current_price(self, ticker: str) -> PriceQuote:
        last_error: Exception | None = None
        for symbol in self._candidate_symbols(ticker):
            try:
                ticker_obj = yf.Ticker(symbol)
                hist = ticker_obj.history(period="5d", interval="1d")
                close = hist.get("Close")
                if close is None or close.dropna().empty:
                    raise ValueError("가격 데이터가 비어 있습니다.")
                close = close.dropna()
                price = float(close.iloc[-1])
                idx = close.index[-1]
                as_of = idx.to_pydatetime() if hasattr(idx, "to_pydatetime") else datetime.utcnow()
                currency = self._resolve_currency(ticker_obj)
                return PriceQuote(
                    ticker=ticker,
                    price=price,
                    currency=currency,
                    as_of=as_of,
                    source=self.name,
                )
            except Exception as exc:  # pragma: no cover - network errors
                last_error = exc
                continue
        msg = f"{ticker}: yfinance 가격 데이터를 찾을 수 없습니다."
        if last_error:
            msg = f"{msg} ({last_error})"
        raise ValueError(msg)

    def _fetch_dividend_history(
            self,
            ticker: str,
            *,
            start_date: date | None = None,
            end_date: date | None = None,
    ) -> list[DividendPoint]:
        last_error: Exception | None = None
        for symbol in self._candidate_symbols(ticker):
            try:
                ticker_obj = yf.Ticker(symbol)
                dividends = ticker_obj.dividends
                if dividends is None or dividends.empty:
                    return []
                series = dividends.dropna()
                if series.empty:
                    return []

                points: list[DividendPoint] = []
                currency = self._resolve_currency(ticker_obj)
                for idx, value in series.items():
                    event_dt = idx.to_pydatetime().date() if hasattr(idx, "to_pydatetime") else idx.date()
                    if start_date and event_dt < start_date:
                        continue
                    if end_date and event_dt > end_date:
                        continue
                    points.append(
                        DividendPoint(
                            ticker=ticker,
                            event_date=event_dt,
                            amount=float(value),
                            currency=currency,
                            source=self.name,
                        )
                    )
                return points
            except Exception as exc:  # pragma: no cover - network errors
                last_error = exc
                continue

        msg = f"{ticker}: yfinance 배당 데이터를 찾을 수 없습니다."
        if last_error:
            msg = f"{msg} ({last_error})"
        raise ValueError(msg)

    def _resolve_currency(self, ticker_obj: yf.Ticker) -> str:
        fast_info = getattr(ticker_obj, "fast_info", None)
        currency = None
        if isinstance(fast_info, dict):
            currency = fast_info.get("currency")
        if not currency:
            info = getattr(ticker_obj, "info", {}) or {}
            currency = info.get("currency")
        return currency or self.default_currency


class USProviderYFinance(BaseYFinanceProvider):
    name = "yfinance-us"
    default_currency = "USD"


class KRYFinanceProvider(BaseYFinanceProvider):
    """YFinance provider for KR tickers using .KS/.KQ suffix heuristics."""

    name = "yfinance-kr"
    default_currency = "KRW"

    def _candidate_symbols(self, ticker: str) -> list[str]:
        normalized = normalize_ticker(ticker)
        base = normalized.lstrip("A")
        seeds = [normalized]
        if base and base != normalized:
            seeds.append(base)

        suffixes = [".KS", ".KQ", ".KO"]
        candidates: list[str] = []
        for seed in seeds:
            if not seed:
                continue
            if any(seed.endswith(suffix) for suffix in suffixes):
                candidates.append(seed)
                continue
            for suffix in suffixes:
                candidates.append(f"{seed}{suffix}")
            candidates.append(seed)

        deduped: list[str] = []
        seen: set[str] = set()
        for symbol in candidates:
            if symbol and symbol not in seen:
                seen.add(symbol)
                deduped.append(symbol)
        return deduped


class KISDomesticPriceProvider(MarketDataProvider):
    """KIS-backed provider for KR current price."""

    name = "kis-kr"

    def _fetch_current_price(self, ticker: str) -> PriceQuote:
        data = fetch_domestic_price_now(ticker)
        last = data.get("last")
        if last is None:
            raise ValueError(f"{ticker}: KIS 국내 현재가 응답에 가격이 없습니다.")
        as_of = data.get("as_of") or datetime.utcnow()
        return PriceQuote(
            ticker=ticker,
            price=float(last),
            currency="KRW",
            as_of=as_of,
            source=self.name,
        )

    def _fetch_dividend_history(
            self,
            ticker: str,
            *,
            start_date: date | None = None,
            end_date: date | None = None,
    ) -> list[DividendPoint]:
        raise NotImplementedError("KIS 국내 배당 내역은 지원하지 않습니다.")


class KISOverseasPriceProvider(MarketDataProvider):
    """KIS-backed provider for overseas current price with yfinance dividends."""

    name = "kis-overseas"

    def __init__(
        self,
        *,
        dividend_provider: MarketDataProvider | None = None,
        history_lookback_days: int | None = None,
    ) -> None:
        self._dividend_provider = dividend_provider or USProviderYFinance()
        configured = get_kis_setting("KIS_OVERSEAS_PRICE_LOOKBACK_DAYS")
        if history_lookback_days is not None:
            self._history_lookback_days = max(history_lookback_days, 1)
        elif configured:
            try:
                self._history_lookback_days = max(int(configured), 1)
            except ValueError:
                self._history_lookback_days = 10
        else:
            self._history_lookback_days = 10

    def _market_candidates(self) -> list[str]:
        raw = get_kis_setting("KIS_OVERSEAS_MARKET_PRIORITY")
        if raw:
            items = [item.strip() for item in raw.split(",") if item.strip()]
            if items:
                return items
        return ["NAS", "NYS", "AMS"]

    def _market_currency(self, market: str) -> str:
        upper = market.strip().upper()
        if upper in {"NAS", "NASDAQ", "NYS", "NYSE", "AMS"}:
            return "USD"
        return "USD"

    def _fetch_current_price(self, ticker: str) -> PriceQuote:
        last_error: Exception | None = None
        for market in self._market_candidates():
            try:
                data = fetch_overseas_price_now(market, ticker)
                last = data.get("last")
                if last is None:
                    raise ValueError("missing last price")
                as_of = data.get("as_of") or datetime.utcnow()
                currency = str(data.get("currency") or self._market_currency(market)).upper()
                return PriceQuote(
                    ticker=ticker,
                    price=float(last),
                    currency=currency,
                    as_of=as_of,
                    source=self.name,
                )
            except Exception as exc:  # pragma: no cover - network errors
                last_error = exc
                continue
        msg = f"{ticker}: KIS 해외 현재가 조회에 실패했습니다."
        if last_error:
            msg = f"{msg} ({last_error})"
        raise ValueError(msg)

    def _fetch_dividend_history(
            self,
            ticker: str,
            *,
            start_date: date | None = None,
            end_date: date | None = None,
    ) -> list[DividendPoint]:
        return self._dividend_provider._fetch_dividend_history(  # type: ignore[attr-defined]
            ticker,
            start_date=start_date,
            end_date=end_date,
        )


class KRLocalProvider(MarketDataProvider):
    """KR provider that uses local cache/snapshots for price and dividend_events for dividends."""

    name = "kr-local"
    SNAPSHOT_FILE = DATA_DIR / "kr_price_snapshot.csv"

    def __init__(self, *, fallback_provider: MarketDataProvider | None = None) -> None:
        self._snapshot_prices: dict[str, PriceQuote] | None = None
        self._fallback_provider = fallback_provider or KRYFinanceProvider()

    def get_current_price(self, session: Session, ticker: str) -> PriceQuote:
        normalized = normalize_ticker(ticker)
        quote = self._get_cached_quote(session, normalized)
        if quote:
            return quote

        snapshot = self._get_snapshot_quote(normalized)
        if snapshot:
            _upsert_price_cache(session, snapshot)
            return snapshot

        fallback_error: Exception | None = None
        if self._fallback_provider:
            try:
                return self._fallback_provider.get_current_price(session, normalized)
            except Exception as exc:  # pragma: no cover - network failure
                fallback_error = exc

        msg = (
            f"{ticker}: 가격 데이터를 찾을 수 없습니다. KR 종목 가격은 price_cache 또는 data/kr_price_snapshot.csv 에서만 제공합니다. "
            "스냅샷 파일에 최신 종가를 추가하거나 price_cache 를 채워주세요."
        )
        if fallback_error:
            msg = f"{msg} (추가 시도 실패: {fallback_error})"
        raise ValueError(msg)

    def get_dividend_history(
            self,
            session: Session,
            ticker: str,
            *,
            start_date: date | None = None,
            end_date: date | None = None,
    ) -> list[DividendPoint]:
        normalized = normalize_ticker(ticker)
        if not normalized:
            return []

        rows = session.execute(
            select(DividendEvent)
            .where(
                DividendEvent.ticker == normalized,
                DividendEvent.archived == False,
            )
            .order_by(DividendEvent.pay_date)
        ).scalars().all()

        points: list[DividendPoint] = []
        for row in rows:
            event_date = row.pay_date
            if start_date and event_date < start_date:
                continue
            if end_date and event_date > end_date:
                continue
            points.append(
                DividendPoint(
                    ticker=normalized,
                    event_date=event_date,
                    amount=row.gross_dividend,
                    currency=row.currency or "KRW",
                    source="dividend_events",
                )
            )

        if points:
            _upsert_dividend_cache(session, points)
        return points

    def _fetch_dividend_history(
            self,
            ticker: str,
            *,
            start_date: date | None = None,
            end_date: date | None = None,
    ) -> list[DividendPoint]:
        raise NotImplementedError

    def _get_cached_quote(self, session: Session, ticker: str) -> PriceQuote | None:
        row = session.execute(
            select(PriceCache)
            .where(PriceCache.ticker == ticker)
            .order_by(desc(PriceCache.as_of))
            .limit(1)
        ).scalar_one_or_none()
        if not row:
            return None
        return PriceQuote(
            ticker=row.ticker,
            price=row.price,
            currency=row.currency,
            as_of=row.as_of,
            source=row.source,
        )

    def _get_snapshot_quote(self, ticker: str) -> Optional[PriceQuote]:
        snapshots = self._load_snapshot_prices()
        entry = snapshots.get(ticker)
        if not entry:
            return None
        return PriceQuote(
            ticker=ticker,
            price=entry["price"],
            currency=entry["currency"],
            as_of=entry["as_of"],
            source="kr_snapshot",
        )

    def _load_snapshot_prices(self) -> dict[str, dict]:
        if self._snapshot_prices is not None:
            return self._snapshot_prices

        cache: dict[str, dict] = {}
        if self.SNAPSHOT_FILE.exists():
            try:
                df = pd.read_csv(self.SNAPSHOT_FILE)
                df["ticker"] = df["ticker"].map(normalize_ticker)
                df = df.dropna(subset=["ticker", "price"])
                for _, row in df.iterrows():
                    ticker = row["ticker"]
                    if not ticker:
                        continue
                    price = float(row["price"])
                    currency = str(row.get("currency") or "KRW").upper()
                    as_of_raw = row.get("as_of")
                    as_of = (
                        pd.to_datetime(as_of_raw).to_pydatetime()
                        if pd.notna(as_of_raw)
                        else datetime.utcnow()
                    )
                    cache[ticker] = {
                        "price": price,
                        "currency": currency,
                        "as_of": as_of,
                    }
            except Exception:
                cache = {}

        self._snapshot_prices = cache
        return cache

    def _fetch_current_price(self, ticker: str) -> PriceQuote:
        """Unused abstract hook; use get_current_price with session."""
        raise NotImplementedError("KRLocalProvider는 session 기반 get_current_price만 지원합니다.")


class KRDartProvider(MarketDataProvider):
    """KR provider that sources dividends from DART and prices from a configurable provider."""

    name = "dart-kr"

    def __init__(
            self,
            *,
            price_provider: MarketDataProvider | None = None,
            dividend_fetcher: DartDividendFetcher | None = None,
            dividend_fallback_provider: MarketDataProvider | None = None,
    ) -> None:
        self.price_provider = price_provider or KRLocalProvider()
        self.dividend_fetcher = dividend_fetcher or DartDividendFetcher()
        self.dividend_fallback_provider = dividend_fallback_provider or KRLocalProvider()

    def get_current_price(self, session: Session, ticker: str) -> PriceQuote:
        return self.price_provider.get_current_price(session, ticker)

    def get_dividend_history(
            self,
            session: Session,
            ticker: str,
            *,
            start_date: date | None = None,
            end_date: date | None = None,
    ) -> list[DividendPoint]:
        normalized = normalize_ticker(ticker)
        if not normalized:
            return []

        start_year = start_date.year if start_date else None
        end_year = end_date.year if end_date else None

        try:
            records = self.dividend_fetcher.fetch_dividend_records(
                normalized,
                start_year=start_year,
                end_year=end_year,
            )
        except DartApiUnavailable as exc:
            raise RuntimeError(str(exc)) from exc
        except Exception as exc:  # pragma: no cover - unexpected API errors
            raise RuntimeError(f"DART 배당 조회 중 오류가 발생했습니다: {exc}") from exc

        points: list[DividendPoint] = []
        for record in records:
            if start_date and record.event_date < start_date:
                continue
            if end_date and record.event_date > end_date:
                continue
            points.append(
                DividendPoint(
                    ticker=normalized,
                    event_date=record.event_date,
                    amount=record.amount,
                    currency=record.currency,
                    source="dart",
                )
            )

        if not points:
            if self.dividend_fallback_provider:
                return self.dividend_fallback_provider.get_dividend_history(
                    session,
                    normalized,
                    start_date=start_date,
                    end_date=end_date,
                )
            return []

        _upsert_dividend_cache(session, points)
        return points

    def _fetch_current_price(self, ticker: str) -> PriceQuote:
        raise NotImplementedError

    def _fetch_dividend_history(
            self,
            ticker: str,
            *,
            start_date: date | None = None,
            end_date: date | None = None,
    ) -> list[DividendPoint]:
        raise NotImplementedError


class KRExperimentalKRXProvider(MarketDataProvider):
    """Optional experimental provider (disabled by default) for direct KRX scraping."""

    name = "krx-experimental"

    def _fetch_current_price(self, ticker: str) -> PriceQuote:  # pragma: no cover - placeholder
        raise NotImplementedError("KRX scraping provider is experimental and not enabled by default.")

    def _fetch_dividend_history(
            self,
            ticker: str,
            *,
            start_date: date | None = None,
            end_date: date | None = None,
    ) -> list[DividendPoint]:  # pragma: no cover - placeholder
        raise NotImplementedError("KRX scraping provider is experimental and not enabled by default.")


register_market_provider("US", KISOverseasPriceProvider())
register_market_provider("KR", KRDartProvider(price_provider=KISDomesticPriceProvider()))


def _upsert_price_cache(session: Session, quote: PriceQuote) -> None:
    existing = session.execute(
        select(PriceCache).where(
            PriceCache.ticker == quote.ticker,
            PriceCache.as_of == quote.as_of,
        )
    ).scalar_one_or_none()

    if existing:
        existing.price = quote.price
        existing.currency = quote.currency
        existing.source = quote.source
    else:
        session.add(
            PriceCache(
                ticker=quote.ticker,
                as_of=quote.as_of,
                price=quote.price,
                currency=quote.currency,
                source=quote.source,
            )
        )


def _upsert_dividend_cache(session: Session, points: Iterable[DividendPoint]) -> None:
    for point in points:
        existing = session.execute(
            select(DividendCache).where(
                DividendCache.ticker == point.ticker,
                DividendCache.event_date == point.event_date,
            )
        ).scalar_one_or_none()

        if existing:
            existing.amount = point.amount
            existing.currency = point.currency
            existing.source = point.source
        else:
            session.add(
                DividendCache(
                    ticker=point.ticker,
                    event_date=point.event_date,
                    amount=point.amount,
                    currency=point.currency,
                    source=point.source,
                )
            )
