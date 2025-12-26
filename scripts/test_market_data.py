from __future__ import annotations

from datetime import date

from core.db import db_session
from core.market_data import USProviderYFinance


def main() -> None:
    provider = USProviderYFinance()

    with db_session() as session:
        quote = provider.get_current_price(session, "MMM")
        history = provider.get_dividend_history(session, "MMM", start_date=date(2018, 1, 1))

    print("Latest price quote")
    print(f"  ticker:   {quote.ticker}")
    print(f"  price:    {quote.price:.2f} {quote.currency}")
    print(f"  as_of:    {quote.as_of}")
    print(f"  source:   {quote.source}")
    print()
    print(f"Dividend history points saved: {len(history)}")
    if history:
        sample = history[-5:]
        print("Most recent dividend events:")
        for point in sample:
            print(f"  {point.event_date}: {point.amount:.4f} {point.currency}")


if __name__ == "__main__":
    main()
