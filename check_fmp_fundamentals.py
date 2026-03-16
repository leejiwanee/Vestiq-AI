
import os
import django
import sys
from datetime import date

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'stockweb.settings')
django.setup()

from updatedata.models import Ticker, FundamentalData
from updatedata.tasks import _update_fundamentals

# Ensure AAPL exists
ticker, created = Ticker.objects.get_or_create(symbol='AAPL', defaults={'name': 'Apple Inc.'})
print(f"Testing FMP Update for {ticker.symbol}...")

# Call the function (it expects a list of objects or strings)
# Logic handles strings or objects.
try:
    _update_fundamentals([ticker])
except Exception as e:
    print(f"Error calling _update_fundamentals: {e}")

# Check Result
fd = FundamentalData.objects.filter(symbol=ticker, date=date.today()).first()
if fd:
    print(f"\n[SUCCESS] Data Updated for {fd.date}")
    print(f"Market Cap: {fd.market_cap}")
    print(f"PE Ratio (TTM): {fd.trailing_pe}")
    print(f"PB Ratio: {fd.price_to_book}")
    print(f"ROE: {fd.return_on_equity}")
    print(f"Sector (Ticker): {ticker.sector}")
    print(f"Industry (Ticker): {ticker.industry}")
else:
    print("\n[FAILURE] No FundamentalData found for today.")
