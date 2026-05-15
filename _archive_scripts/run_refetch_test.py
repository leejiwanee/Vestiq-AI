
import os
import sys
import django
import datetime

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'stockweb.settings')
django.setup()

from updatedata.models import PriceHistory, Ticker, FundamentalData
from updatedata.tasks import update_daily_close

symbols = ['AAPL', 'NVDA']
print(f"--- Step 1: Deleting latest data for {symbols} ---")

for sym in symbols:
    t = Ticker.objects.filter(symbol=sym).first()
    if not t: continue
    
    # Delete latest PriceHistory
    latest_ph = PriceHistory.objects.filter(symbol=t).order_by('-date').first()
    if latest_ph:
        print(f"[{sym}] Deleting PriceHistory for {latest_ph.date}")
        latest_ph.delete()
    else:
        print(f"[{sym}] No PriceHistory found to delete.")

    # Delete latest FundamentalData (to verify it comes back too)
    latest_fd = FundamentalData.objects.filter(symbol=t).order_by('-date').first()
    if latest_fd:
        print(f"[{sym}] Deleting FundamentalData for {latest_fd.date}")
        latest_fd.delete()

print("\n--- Step 2: Running update_daily_close (FMP Fetch) ---")
update_daily_close(symbols=symbols)

print("\n--- Step 3: Verification ---")
for sym in symbols:
    t = Ticker.objects.filter(symbol=sym).first()
    
    # Check Price
    ph = PriceHistory.objects.filter(symbol=t).order_by('-date').first()
    if ph:
        print(f"[{sym}] Restored Price: {ph.date} | Close: {ph.close}")
    else:
        print(f"[{sym}] Price NOT restored.")

    # Check Fund
    fd = FundamentalData.objects.filter(symbol=t).order_by('-date').first()
    if fd:
        print(f"[{sym}] Restored Fund: {fd.date} | MarketCap: {fd.market_cap}")
    else:
        print(f"[{sym}] Fund NOT restored.")
