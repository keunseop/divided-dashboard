# Repository Guidelines

## Project Structure & Module Organization
- `app.py` is the Streamlit entrypoint; navigation uses `st.Page` and explicit registration.
- UI pages live in `app_pages/` (e.g., `app_pages/1_대시보드.py`). Keep the numeric prefix for ordering.
- Core logic is under `core/` (DB models, services, KIS integration, secrets).
- Data files and snapshots: `data/`, `var/`, and `dividends-seed.sqlite3` (seed DB).
- Docs and cache: `docs/`, `docs_cache/`.
- Helper scripts: `scripts/` (e.g., `scripts/fetch_market_prices.py`).

## Build, Test, and Development Commands
- Install deps: `python -m pip install -r requirements.txt`
- Run locally: `streamlit run app.py`
- (Optional) Run helper scripts:
  - `python scripts/fetch_market_prices.py` (market data fetch)
  - `python scripts/update_kr_price_cache.py` (KR price cache)
  - `python scripts/test_market_data.py` (ad‑hoc checks; not a formal test suite)

## Coding Style & Naming Conventions
- Python, 4-space indentation.
- Use `snake_case` for functions/vars, `PascalCase` for classes, `UPPER_SNAKE_CASE` for constants.
- Keep Streamlit page file names as `<number>_<name>.py` to maintain order.
- Avoid non-ASCII unless the file already uses it (many UI labels are Korean).

## Testing Guidelines
- No formal test framework in this repo yet.
- Validate changes manually by running the app and exercising relevant pages.
- For market data/KIS changes, run `scripts/test_market_data.py` if applicable.

## Commit & Pull Request Guidelines
- Git history uses short, descriptive Korean messages (e.g., “pykis 인증 수정2”).
- Keep commits focused and scoped to one change area.
- PRs (if used) should describe behavior changes and include UI screenshots for page updates.

## Security & Configuration Tips
- Secrets must be provided via `.streamlit/secrets.toml` or environment variables (see `README.md`).
- Do not commit API keys or KIS secrets; prefer `var/` for runtime-only files.
- DB defaults to `var/dividends.sqlite3` with fallback to `~/.dividend-dashboard/`.
