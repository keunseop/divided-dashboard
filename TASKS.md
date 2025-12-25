# Tasks

## P0 (Now)
- [x] Add thousand-separator KRW formatting in Dashboard metrics and tables.
- [x] Add Missing Tickers page:
  - Find tickers present in DividendEvent but missing in TickerMaster.
  - Provide CSV download for quick completion.
- [x] Ensure ticker normalization (strip + uppercase) consistently in both dividend importer and ticker master importer.

## P1 (Next)
- [x] Add TickerMaster optional fields (market/currency) + importer support.
- [x] Add filters in Dashboard:
  - accountType (ALL/TAXABLE/ISA)

## P2 (Later)
- [ ] Alimtalk parser module:
  - Save raw_text
  - Extract gross/net/tax/currency/payDate/ticker
  - Upsert into DividendEvent with source=alimtalk
- [ ] Stock Finder:
  - Data source decision (KRX first, then DART, optional commercial data)
  - Screener for dividend growth (3-5y), yield, stability
  - Price chart + yield-at-current-price
