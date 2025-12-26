from __future__ import annotations

import enum
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class AccountType(str, enum.Enum):
    TAXABLE = "TAXABLE"  # 일반
    ISA = "ISA"          # ISA
    ALL = "ALL"


class DividendSource(str, enum.Enum):
    EXCEL = "excel"
    ALIMTALK = "alimtalk"
    MANUAL = "manual"


class DividendEvent(Base):
    __tablename__ = "dividend_events"
    __table_args__ = (
        UniqueConstraint("row_id", name="uq_dividend_row_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    row_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    pay_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    month: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    ticker: Mapped[str] = mapped_column(String(16), nullable=False, index=True)

    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="KRW")
    fx_rate: Mapped[float | None] = mapped_column(Float, nullable=True)

    gross_dividend: Mapped[float] = mapped_column(Float, nullable=False)  # 세전
    tax: Mapped[float | None] = mapped_column(Float, nullable=True)       # 세금(없으면 null)
    net_dividend: Mapped[float | None] = mapped_column(Float, nullable=True)  # 세후(없으면 null)

    krw_gross: Mapped[float | None] = mapped_column(Float, nullable=True)
    krw_net: Mapped[float | None] = mapped_column(Float, nullable=True)

    account_type: Mapped[AccountType] = mapped_column(
        Enum(AccountType), nullable=False, default=AccountType.TAXABLE
    )

    source: Mapped[str] = mapped_column(String(16), nullable=False, default=DividendSource.EXCEL.value)
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    raw_text: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class TickerMaster(Base):
    __tablename__ = "ticker_master"

    ticker: Mapped[str] = mapped_column(String(32), primary_key=True)
    name_ko: Mapped[str] = mapped_column(String(128), nullable=False)

    market: Mapped[str | None] = mapped_column(String(16), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)


class PriceCache(Base):
    __tablename__ = "price_cache"
    __table_args__ = (
        UniqueConstraint("ticker", "as_of", name="uq_price_cache_ticker_asof"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    as_of: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class DividendCache(Base):
    __tablename__ = "dividend_cache"
    __table_args__ = (
        UniqueConstraint("ticker", "event_date", name="uq_dividend_cache_ticker_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    event_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"
    __table_args__ = (
        UniqueConstraint("snapshot_date", "account_type", name="uq_snapshot_date_account"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    account_type: Mapped[AccountType] = mapped_column(
        Enum(AccountType), nullable=False, default=AccountType.ALL
    )
    contributed_krw: Mapped[float | None] = mapped_column(Float, nullable=True)
    cash_krw: Mapped[float | None] = mapped_column(Float, nullable=True)
    valuation_krw: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="excel")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class HoldingPosition(Base):
    __tablename__ = "holding_positions"
    __table_args__ = (
        UniqueConstraint("ticker", "account_type", name="uq_holding_position"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    account_type: Mapped[AccountType] = mapped_column(Enum(AccountType), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    avg_buy_price_krw: Mapped[float] = mapped_column(Float, nullable=False)
    total_cost_krw: Mapped[float] = mapped_column(Float, nullable=False)
    note: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class HoldingValuationSnapshot(Base):
    __tablename__ = "holding_valuation_snapshots"
    __table_args__ = (
        UniqueConstraint("valuation_date", "account_type", name="uq_valuation_snapshot"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    valuation_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    account_type: Mapped[AccountType] = mapped_column(Enum(AccountType), nullable=False, index=True)
    total_cost_krw: Mapped[float] = mapped_column(Float, nullable=False)
    market_value_krw: Mapped[float] = mapped_column(Float, nullable=False)
    gain_loss_krw: Mapped[float] = mapped_column(Float, nullable=False)
    gain_loss_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
