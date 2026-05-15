
import os
import django
import sys
import time
import requests
import datetime as dt
from datetime import timedelta
import pandas as pd

# 1. Setup Django Environment
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'stockweb.settings')

# Trick updatedata/apps.py to NOT run startup_check (Thread)
sys.argv.append('shell')

django.setup()

from django.conf import settings
from django.utils import timezone
from updatedata.models import Ticker, PriceHistory

def run_tiingo_backfill_5y():
    """
    Backfills 5 years of Price History from Tiingo.
    Usage:
        python run_tiingo_backfill_5y.py test  (Default: Runs for AAPL only)
        python run_tiingo_backfill_5y.py full  (Runs for ALL tickers)
    """
    api_key = settings.TIINGO_API_KEY
    if not api_key:
        print("❌ Error: TIINGO_API_KEY is missing/empty.")
        return

    # Determine Mode
    mode = 'test'
    if len(sys.argv) > 1 and sys.argv[1] == 'full':
        mode = 'full'
        
    print(f"=== Tiingo 5Y Backfill (Mode: {mode.upper()}) ===")
    
    # 2. Get Targets
    if mode == 'full':
        tickers_qs = Ticker.objects.all().order_by('symbol')
        print(f"🎯 Target: ALL {tickers_qs.count()} Tickers")
    else:
        # Test Mode: Use AAPL (or first available)
        tickers_qs = Ticker.objects.filter(symbol='AAPL')
        if not tickers_qs.exists():
            tickers_qs = Ticker.objects.all()[:1]
        print(f"🎯 Target: TEST (1 Ticker: {tickers_qs.first()})")
    
    total = tickers_qs.count()
    
    # 3. Parameters
    today = dt.date.today()
    start_date = today - timedelta(days=365*5) # 5 Years
    start_str = start_date.strftime('%Y-%m-%d')
    
    success_count = 0
    fail_count = 0
    
    # Helper for Symbol Map
    def get_tiingo_symbol(sym):
        map_fix = {
            'BRK.B': 'BRK-B', 
            'BRK/B': 'BRK-B',
            'BF.B': 'BF-B',
            'BF-B': 'BF-B',
            'BF.A': 'BF-A',
            'BF-A': 'BF-A',
            'MOGA': 'MOG.A', # User request earlier
            'MOG.A': 'MOG.A'
        }
        if sym in map_fix: return map_fix[sym]
        return sym.replace('.', '-') # Generic fallback

    # 4. Processing Loop
    for i, t_obj in enumerate(tickers_qs):
        sym = t_obj.symbol
        print(f"[{i+1}/{total}] {sym}: Fetching 5Y history...", end=' ')
        sys.stdout.flush()
        
        req_sym = get_tiingo_symbol(sym)
        url = f"https://api.tiingo.com/tiingo/daily/{req_sym}/prices?startDate={start_str}&token={api_key}"
        headers = {'Content-Type': 'application/json'}
        
        try:
            res = requests.get(url, headers=headers, timeout=15)
            
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, list) and len(data) > 0:
                    count_saved = 0
                    batch_data = []
                    
                    # Prepare objects for bulk_create or update_or_create ??
                    # update_or_create is safer if partial data exists
                    # Assuming user truncated, bulk_create is faster?
                    # But safer to loop to handle logic.
                    
                    for row in data:
                        d_str = row.get('date')
                        if not d_str: continue
                        r_date = pd.to_datetime(d_str).date()
                        
                        PriceHistory.objects.update_or_create(
                            symbol=t_obj,
                            date=r_date,
                            defaults={
                                'open': float(row.get('open', 0) or 0),
                                'high': float(row.get('high', 0) or 0),
                                'low': float(row.get('low', 0) or 0),
                                'close': float(row.get('close', 0) or 0),
                                'volume': int(row.get('volume', 0) or 0),
                                'adj_close': None, # Requested: No Adj
                                'div_cash': float(row.get('divCash', 0.0)),
                                'split_factor': float(row.get('splitFactor', 1.0)),
                                'updated_at': timezone.now()
                            }
                        )
                        count_saved += 1
                    
                    print(f"✅ Filled {count_saved} rows.")
                    success_count += 1
                else:
                    print(f"⚠️ Empty Response.")
            elif res.status_code == 429:
                print(f"⛔ Rate Limit (429). Sleeping 10s...")
                time.sleep(10)
                fail_count += 1
            else:
                print(f"❌ HTTP {res.status_code}")
                fail_count += 1
                
        except Exception as e:
            print(f"❌ Err: {e}")
            fail_count += 1
            
    print("\n" + "="*40)
    print(f"🎉 Backfill Complete! Success: {success_count}, Failed: {fail_count}")

if __name__ == "__main__":
    run_tiingo_backfill_5y()
