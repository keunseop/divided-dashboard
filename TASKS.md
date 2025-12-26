# Tasks

## Project Context
- Streamlit multipage app + SQLite + SQLAlchemy.
- We already manage:
  - Dividend events imported from Excel CSV (`dividend_events`)
  - Ticker master (`ticker_master`)
  - FX rates and DART dividend lookup (DART URL API, not OpenDartReader module)
- New goal: add **portfolio contribution / valuation tracking** and **per-ticker position summary**.
- User contributes **KRW 600,000 per month** into a dividend account.
- There are 2 accounts: TAXABLE(일반) and ISA.
- Requirements include:
  - Total invested amount (매수 원금) trend
  - Current valuation (평가금액) trend
  - Cash (현금) trend
  - Per-ticker: average buy price, quantity, market price, P/L (+/-)
  - Per-ticker: show dividend trend together (from our existing dividend datasets)

## Scope / Rules
- We DO compute user-specific holdings metrics in this feature set:
  - average buy price, quantity, valuation, P/L.
- We do NOT need brokerage integration; data entry can be via CSV imports (Excel source of truth).
- Keep DB as the canonical store after import. Do not require live network calls for holdings.
- UI should format KRW with thousands separators and "원".

---

# P0: Data Model for Contributions / Cash / Holdings

## Task P0-1: Add new tables/models
Add SQLAlchemy models + create tables:

### 1) `portfolio_snapshots` (time-series of totals)
- snapshot_id (PK autoincrement)
- snapshot_date (date)  # monthly or arbitrary
- account_type (enum: TAXABLE/ISA/ALL)
- contributed_krw (float)  # 누적 납입/입금 원금 (e.g., monthly 600k)
- cash_krw (float)         # snapshot cash balance
- valuation_krw (float)    # total market value of holdings at snapshot_date (optional if not provided)
- note (text, optional)
- source (str: "excel"|"manual")

### 2) `holding_positions` (per-account aggregated position)
- id (PK)
- ticker (str, 32)
- account_type (enum)
- quantity (float)
- avg_buy_price_krw (float)
- total_cost_krw (float)  # quantity * avg price
- note (text, optional)
- source ("excel"|"manual")

Acceptance:
- Models exist; tables created; basic CRUD works.
- Use `String(32)` for ticker to support KR + US tickers.

## Task P0-2: Decide the user input format (CSV)
We will keep Excel as source of truth. Create CSV schemas:

1) `holding_positions.csv` (현재 보유 잔고)
Header example:
종목코드,계좌구분,수량,평균매입가(원),비고
- 평균 매입가는 원화 기준.
- 계좌구분: 일반->TAXABLE, ISA->ISA

2) `portfolio_snapshots.csv` (optional if we track cash & totals monthly)
Header example:
snapshotId,기준일,계좌구분,누적원금,현금,평가금액,비고

Acceptance:
- Importers handle Korean headers and normalize values.
- Duplicate/blank columns are ignored.
- "-" treated as null.

---

# P1: Holdings Calculator (per ticker, per account)

## Task P1-1: Compute position from lots
Implement logic that produces current position per ticker (per account):
- total_qty = running quantity (start from CSV baseline, then add manual buys)
- avg_buy_price_krw = weighted average cost as buys are appended
- invested_cost_krw = total_qty * avg_buy_price_krw
- (Optional) realized P/L can be computed later.

Acceptance:
- Given sample lots, position outputs correct qty and avg price.
- Handles partial sells.

## Task P1-2: Store derived positions (optional)
Optionally store computed positions into `holdings_positions` table for faster UI.
Or compute on-the-fly in the dashboard.

Acceptance:
- Dashboard can render within 1s for typical dataset size.

---

# P2: Market Price Integration (for valuation / P&L)

## Task P2-1: Price input method
Since KR network sources can be unreliable, avoid mandatory live calls.
Support two modes:
- Manual price import CSV (`prices.csv`)
- Optional provider-based live fetch for US (yfinance) and KR (later)

Schema `prices.csv`:
asOfDate,ticker,price,currency,fxRate,priceKrw

Acceptance:
- App can compute valuation_krw = qty * priceKrw.

## Task P2-2: Valuation + P/L computation
For each ticker:
- market_price_krw
- valuation_krw = qty * market_price_krw
- cost_basis_krw = qty * avg_buy_price_krw
- pnl_krw = valuation_krw - cost_basis_krw
- pnl_pct = pnl_krw / cost_basis_krw

Acceptance:
- Per ticker table shows + / - indicator and formatted values.

---

# P3: UI / Dashboard Enhancements

## Task P3-1: Portfolio Overview dashboard card
Add to Dashboard page:
- Total contributed_krw (if snapshots exist) OR sum of BUY krw_amount as "invested"
- Total valuation_krw (sum over tickers)
- Total cash_krw (from snapshots or manual input)
- Total P/L and P/L%

Charts:
- Time-series chart of contributed vs valuation vs cash (from `portfolio_snapshots`)
- If snapshots not provided, show only current totals.

Acceptance:
- KRW values formatted with commas and "원".
- No SQLAlchemy DetachedInstanceError (convert inside session).

## Task P3-2: Holdings table widget
Create a table:
Columns:
- ticker
- name_ko (join ticker_master)
- account_type (filter)
- qty
- avg_buy_price_krw
- market_price_krw
- cost_basis_krw
- valuation_krw
- pnl_krw, pnl_pct
- status: "+" / "-" / "N/A"

Interactions:
- filter by account_type (ALL/TAXABLE/ISA)
- search ticker

Acceptance:
- Works with KR + US tickers.

## Task P3-3: Ticker detail view (combined holdings + dividends)
When user clicks/selects a ticker:
- Show holdings summary (qty, avg price, pnl)
- Show dividend trend:
  - from existing dividend_events cashflow (krwGross) by year/month
  - and/or DART dividend per share trend if available
- Charts:
  - annual dividend cashflow (KRW) from dividend_events
  - annual DPS series (if we store DART results)
- Provide notes if dividend data missing.

Acceptance:
- "Single ticker" page works end-to-end for a ticker in both holdings and dividend_events.

---

# P4: Import Pages

## Task P4-1: Add "Import Holdings Lots CSV" page
- Upload CSV
- Preview
- Import button
- Upsert by tradeId
- Sync mode optional (archive missing trades rather than delete)

## Task P4-2: Add "Import Portfolio Snapshots CSV" page
- Upload CSV
- Preview
- Import button
- Upsert by snapshotId

## Task P4-3: Add "Import Prices CSV" page
- Upload CSV
- Preview
- Import button
- Upsert by (asOfDate, ticker)

Acceptance:
- All imports provide success counts inserted/updated/archived candidates.

---

# Notes / Implementation Guidance
- Use ticker normalization: `strip().upper()`
- Account type normalization:
  - "일반" -> TAXABLE
  - "ISA" -> ISA
- Keep the app stable without network calls. Live price fetching is optional.
- Ensure all monetary outputs use thousand separators.

## P5 
- [ ] Dashboard 의 top 15 종목에 대하여, 각 종목별 전체 배당엑 대비 차지하는 비율을 표시해줄 수 있는 원형 차트를 그려줘.
  - 1~15개 종목 + 기타 종목 해서 16개 종목의 비율이겠지
