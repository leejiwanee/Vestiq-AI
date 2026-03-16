import os, sys
import django
from django.db.models import Count, Max

# Helper to setup Django env
sys.path.append(os.getcwd())
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "stockweb.settings")
django.setup()

from updatedata.models import Ticker, FundamentalData, PriceHistory

print("--- Checking Local Data ---")

ticker_count = Ticker.objects.count()
fund_count = FundamentalData.objects.count()
price_count = PriceHistory.objects.count()

print(f"Tickers: {ticker_count}")
print(f"Fundamental Records: {fund_count}")
print(f"Price History Records: {price_count}")

# Check Freshness
latest_price = PriceHistory.objects.order_by('-date').first()
print(f"Latest Price Date: {latest_price.date if latest_price else 'None'}")

# Check Sector Coverage
sector_counts = Ticker.objects.values('sector').annotate(count=Count('id')).order_by('-count')
print("\nSector Distribution (Top 5):")
for s in sector_counts[:5]:
    print(f"{s['sector']}: {s['count']}")

print("--- End Check ---")
