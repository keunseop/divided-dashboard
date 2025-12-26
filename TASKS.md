# Tasks

## Context / Goal
We are building a Streamlit-based dividend dashboard app (SQLite + SQLAlchemy).
We already import dividend cashflow events from Excel CSV into `dividend_events`.
Now we want two main stock-level features that do NOT depend on personal cost basis or share count:
1) For tickers we hold (or have in our events), show whether the company's dividends are increasing or decreasing (dividend growth).
2) For any searched ticker (not held), show the same dividend trend plus current dividend yield vs current price.

Important: "Dividend yield" here should be computed using market price + dividend per share (DPS / trailing dividend), NOT user’s cost basis.

## Definitions
- Dividend Growth (YoY): year-over-year % change of annual dividend per share (DPS) or total annual dividends.
- Dividend Growth (CAGR): multi-year compounded annual growth rate using DPS (preferred) or annual dividend totals.
- Trailing Dividend Yield: (sum of dividends per share over last 12 months) / (current price).
- For ETFs like TLTW, use the dividend/distribution history; label as "distribution" if needed.

## Data Requirements
We need external market data:
- US tickers: dividend history + current price
- KR tickers: dividend history + current price
Also we need caching in our DB to avoid repeated API calls.

---

# P0: Create provider abstraction + caching

## Task P0-1: Create DB tables for cached market data
- Add SQLAlchemy models and migrations (simple recreate DB is ok in dev, but prefer non-destructive if possible).
Tables:
1) `price_cache`
   - ticker (PK or composite with date)
   - as_of_date (date, for daily close) or datetime (for current)
   - price (float)
   - currency (str)
   - source (str)
   - updated_at
2) `dividend_cache`
   - ticker
   - ex_date (date) OR pay_date (date if ex_date unavailable)
   - amount (float)  # per share dividend/distribution in ticker currency
   - currency (str)
   - source (str)
   - created_at
Indexes: ticker + date

Acceptance:
- DB tables exist and can be queried.
- Cache upsert logic exists (avoid duplicates).

## Task P0-2: Provider interface
Create a Python interface-like abstraction:
- `MarketDataProvider`
  - `get_current_price(ticker) -> PriceQuote`
  - `get_dividend_history(ticker, start_date, end_date) -> list[DividendPoint]`
Implementations:
- `USProviderYFinance` using `yfinance`
- `KRProvider` placeholder (raise NotImplementedError) for now

Acceptance:
- USProvider works for ticker "MMM" and "TLTW" returning price and dividend history.
- Results are stored in cache tables.

Notes:
- Normalize tickers to uppercase.
- Handle errors gracefully and show user-friendly messages.

---

# P1: Stock dividend analytics (ticker-level) reusable functions

## Task P1-1: Compute annual dividends per share series
Given dividend history (per share events):
- Aggregate by year: `annual_dividend[year] = sum(amounts in that year)`
- Provide dataframe with columns: year, annual_dividend

Acceptance:
- Unit tests or quick checks for MMM produce reasonable series.

## Task P1-2: Compute growth metrics
Given annual dividend series:
- YoY growth per year: (this/prev - 1)
- 3y/5y CAGR (when enough data):
  - CAGR = (last/first)^(1/n) - 1
- Mark trend:
  - "Growing" if last 3 years non-decreasing and CAGR > 0
  - "Shrinking" if last 2 years decreasing or CAGR < 0
  - "Volatile" otherwise

Acceptance:
- Functions return metrics + a trend label.

## Task P1-3: Compute trailing dividend yield
- trailing_12m_dividend = sum(dividends over last 365 days)
- yield = trailing_12m_dividend / current_price

Acceptance:
- For US tickers, yield is computed and displayed.

---

# P2: UI pages (Streamlit)

## Task P2-1: "Held Tickers Dividend Trend" page
Purpose:
- Show dividend trend for tickers we "hold" defined as:
  - union of tickers present in `dividend_events` (non-archived) OR tickers listed in ticker_master
- For each ticker:
  - Name (from ticker_master if exists)
  - Current price (cached)
  - Trailing yield (cached dividends)
  - Dividend growth: YoY last year, 3y/5y CAGR
  - Trend label (Growing/Shrinking/Volatile)
- Provide filters:
  - market: KR/US/ALL (if known via ticker_master.market; otherwise infer: numeric -> KR, else US)
  - minimum years of history (e.g., >=3)

Acceptance:
- Page loads without errors.
- Shows a table summary for at least MMM if present.
- Clicking a ticker expands details (annual dividend chart).

## Task P2-2: "Ticker Search" page
- Input ticker symbol (e.g., MMM, TLTW, 005930)
- Fetch/cache price and dividend history
- Display:
  - annual dividends per share chart
  - YoY and CAGR metrics
  - trailing dividend yield
  - basic info: currency, data source timestamp
- Provide error handling:
  - "No dividend data found"
  - "Ticker not supported by provider"

Acceptance:
- Searching "MMM" works end-to-end.

---

# P3: Korea data provider recommendation/implementation options

## Task P3-1: Investigate KR data sources and propose implementation
We need an approach for KR tickers:
Options:
- OpenDART (official) for dividend announcements (requires parsing, more complex)
- KRX / pykrx (scraping-based, easier but needs reliability review)
Deliverable:
- A short design note in `docs/kr_data_provider.md` recommending:
  - MVP approach (fast)
  - Production approach (official)
  - Expected fields available (DPS, ex-date, pay-date, yield)

Acceptance:
- A clear recommendation with pros/cons and next steps.

---

# Engineering Notes / Constraints
- Do NOT compute user-specific yield based on cost basis or share count.
- Always store and display values as "ticker-level" (per share) metrics.
- Cache all API results; do not hammer providers.
- Streamlit pages must not use ORM objects outside session context (convert to dict/df inside session).
- Format KRW with thousand separators and "원" suffix in UI where applicable.














## P4 (Later)
- [x] Alimtalk parser module:
  - Save raw_text
  - Extract gross/net/tax/currency/payDate/ticker
  - Upsert into DividendEvent with source=alimtalk
- [ ] Stock Finder:
  - Data source decision (KRX first, then DART, optional commercial data)
  - Screener for dividend growth (3-5y), yield, stability
  - Price chart + yield-at-current-price




## P5 
- [ ] Dashboard 의 top 15 종목에 대하여, 각 종목별 전체 배당엑 대비 차지하는 비율을 표시해줄 수 있는 원형 차트를 그려줘.
  - 1~15개 종목 + 기타 종목 해서 16개 종목의 비율이겠지
