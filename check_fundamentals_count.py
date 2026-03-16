import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "stockweb.settings")
django.setup()

from updatedata.models import Ticker, FundamentalData

# Check counts
ticker_count = Ticker.objects.count()
fundamental_count = FundamentalData.objects.count()
unique_symbols_with_fundamentals = FundamentalData.objects.values('symbol').distinct().count()

print(f"=== Database Status ===")
print(f"Total Tickers in DB: {ticker_count}")
print(f"Total FundamentalData rows: {fundamental_count}")
print(f"Unique symbols with fundamentals: {unique_symbols_with_fundamentals}")
print(f"\nMissing fundamentals: {ticker_count - unique_symbols_with_fundamentals}")

# Show some sample tickers
print(f"\nFirst 10 ticker symbols:")
for t in Ticker.objects.all()[:10]:
    has_fund = FundamentalData.objects.filter(symbol=t).exists()
    print(f"  {t.symbol} - Fundamentals: {'✅' if has_fund else '❌'}")
