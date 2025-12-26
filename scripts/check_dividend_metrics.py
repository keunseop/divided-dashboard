from __future__ import annotations

from datetime import date

from core.analytics import (
    compute_annual_dividends,
    compute_growth_metrics,
    compute_trailing_dividend_yield,
)
from core.db import db_session
from core.market_data import USProviderYFinance


def main() -> None:
    provider = USProviderYFinance()
    ticker = "MMM"

    with db_session() as session:
        price = provider.get_current_price(session, ticker)
        history = provider.get_dividend_history(session, ticker, start_date=date(2015, 1, 1))

    annual = compute_annual_dividends(history)
    metrics = compute_growth_metrics(annual)
    trailing = compute_trailing_dividend_yield(history, price)

    print(f"Ticker: {ticker}")
    print(f"Price:  {price.price:.2f} {price.currency} @ {price.as_of.date()}")
    print()
    print("Annual dividends (most recent 5 years):")
    print(annual.tail(5).to_string(index=False))
    print()
    print("Growth metrics:")
    print(f"  3y CAGR: {metrics['cagr_3y']:.2%}" if metrics["cagr_3y"] is not None else "  3y CAGR: N/A")
    print(f"  5y CAGR: {metrics['cagr_5y']:.2%}" if metrics["cagr_5y"] is not None else "  5y CAGR: N/A")
    print(f"  Trend:   {metrics['trend']}")
    print()
    print("Trailing 12M yield:")
    if trailing["trailing_yield"] is not None:
        print(f"  Dividend: {trailing['trailing_dividend']:.4f} {price.currency}")
        print(f"  Yield:    {trailing['trailing_yield']:.2%}")
    else:
        print("  Unable to compute (missing data)")


if __name__ == "__main__":
    main()
