# Dividend Dashboard Project Rules

## Goal
- Build a web (mobile-friendly) service for a couple to manage dividend investing.
- Main focus: dividend dashboard based on KRW-converted gross dividend amounts.
- Secondary focus (later): finding dividend growth stocks (Korean-focused, but portfolio includes overseas tickers too).

## Tech Stack (MVP)
- Streamlit multipage app.
- SQLite (local file DB) using SQLAlchemy.
- Data import via CSV exported from Excel (Excel remains the primary data-entry source).

## Source of Truth
- Excel is the source of truth for dividend events.
- App imports CSV repeatedly; sync mode supports updates and archives missing rows.
- Deletion is handled by "archived" flag, not hard delete (unless explicitly implemented later).

## Data Model (Core)
### DividendEvent
- row_id: unique key from Excel, must be stable across imports.
- pay_date, year, month
- ticker: supports both KR tickers (e.g., 005930, Axxxx) and overseas tickers (e.g., MMM, TLTW). Store as string, uppercase normalize.
- currency: dividend currency (KRW/USD/etc.)
- fx_rate: optional
- gross_dividend: original currency gross dividend
- krw_gross: KRW-converted gross dividend (MOST IMPORTANT dashboard value)
- tax, net_dividend: optional (from Alimtalk or later enrichment)
- account_type: TAXABLE (일반) or ISA
- source: excel/alimtalk/manual
- archived: boolean

### TickerMaster
- ticker (PK)
- name_ko (standard display name)
- Optional fields may be added later: market, currency

## CSV Import Format (Current)
Header:
rowId,날짜,년도,월,종목명,배당금,통화,환율,세전배당금,종목코드,세후배당금,세금,계좌구분

Mapping:
- 배당금 -> gross_dividend (original currency)
- 세전배당금 -> krw_gross (KRW converted gross; required)
- 종목코드 -> ticker (required)
- 계좌구분: 일반 -> TAXABLE, ISA -> ISA
- 종목명 is not used for display; use TickerMaster.name_ko.

Parsing rules:
- payDate format examples: "2020. 4. 9" (with dots/spaces)
- numbers may contain commas and quotes; importer must normalize to floats.
- treat "-" as null

## UI Rules
- Dashboard should primarily use krw_gross for aggregation.
- Show KRW values with thousand separators and "원" suffix.
- Avoid DetachedInstanceError: never use ORM objects outside session context; convert to dict/DataFrame inside session.

## Near-term Roadmap
1) Stabilize CSV import + sync/archiving.
2) TickerMaster management + Missing tickers page.
3) Basic analytics: yearly/monthly trend, YoY, CAGR.
4) Alimtalk parser (later): ingest messages and fill tax/net fields.
5) Stock finder module (later): data sources (KRX/DART/etc.), screening, charts, yield at current price.

## Scope Clarification (Important)

- This project does NOT compute user-specific investment returns.
- Cost basis, average purchase price, share count, and personal yield-on-cost are explicitly out of scope.
- All dividend yield and growth metrics are computed at the **ticker level only**, based on:
  - Dividend per share (DPS) or distribution history
  - Market price (current or historical)
- The app focuses on:
  - Dividend trend quality (growing / shrinking / volatile)
  - Ticker-level dividend yield and growth
  - Cashflow tracking via imported dividend events (KRW-converted gross amounts)