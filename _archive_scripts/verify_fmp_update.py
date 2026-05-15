
import os
import sys
import django

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'stockweb.settings')
django.setup()

from updatedata.tasks import update_daily_close
from updatedata.models import PriceHistory, FundamentalData, Ticker

# Pick a few symbols
symbols = ['AAPL', 'NVDA']
print(f"Running update_daily_close for: {symbols}")

update_daily_close(symbols=symbols)

print("\n--- Verification ---")
for sym in symbols:
    t = Ticker.objects.filter(symbol=sym).first()
    if not t:
        print(f"{sym}: Ticker not found.")
        continue
        
    ph = PriceHistory.objects.filter(symbol=t).order_by('-date').first()
    fd = FundamentalData.objects.filter(symbol=t).order_by('-date').first()
    
    print(f"\nSymbol: {sym}")
    if ph:
        print(f"PriceHistory: Date={ph.date}, Close={ph.close}, Vol={ph.volume}")
    else:
        print("PriceHistory: None")
        
    if fd:
        print(f"FundamentalData: Date={fd.date}, MarketCap={fd.market_cap}")
    else:
        print("FundamentalData: None (FAILED)")
