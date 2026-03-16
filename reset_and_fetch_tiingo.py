
import os
import django
import sys
import logging
import requests
import datetime
import pandas as pd
from django.conf import settings
from django.utils import timezone

# Setup Django Environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'stockweb.settings')
django.setup()

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('console_debug')

from updatedata.models import PriceHistory, Ticker

def reset_and_fetch_tiingo():
    print("\n" + "="*60)
    print("      VESTIQ HARD RESET & TIINGO BACKFILL      ")
    print("="*60 + "\n")
    
    # 1. Truncate PriceHistory
    print("[1/3] Truncating 'PriceHistory' table (Deleting all records)...")
    count, _ = PriceHistory.objects.all().delete()
    print(f"✅ Deleted {count} records. Table is now empty.\n")
    
    # 2. Setup Tiingo Fetch
    API_KEY = settings.TIINGO_API_KEY
    if not API_KEY:
        print("❌ Error: TIINGO_API_KEY not found in settings.")
        return

    tickers_qs = Ticker.objects.all().order_by('symbol')
    total = tickers_qs.count()
    
    today = datetime.date.today()
    start_date = today - datetime.timedelta(days=365*5) # 5 Years
    start_date_str = start_date.strftime('%Y-%m-%d')
    
    headers = {
        'Content-Type': 'application/json'
    }

    print(f"[2/3] Fetching 5-Year History from Tiingo for {total} tickers...")
    print(f"      Start Date: {start_date_str}")
    print(f"      API Endpoint: https://api.tiingo.com/tiingo/daily/{{sym}}/prices")
    print("-" * 60)

    success_count = 0
    fail_count = 0
    
    # 3. Loop and Fetch
    for i, t_obj in enumerate(tickers_qs):
        sym = t_obj.symbol
        # Handle special symbols for Tiingo
        if sym == 'BRK.B': req_sym = 'BRK-B' # Tiingo uses BRK-B? Or BRK.B? 
        # Tiingo usually uses 'BRK-B' for Berkshire
        # Let's try standard mapping
        map_fix = {
            'LENB': 'LEN.B', 'LEN-B': 'LEN.B',
            'CWENA': 'CWEN.A', 'CWEN-A': 'CWEN.A',
            'BFA': 'BF.A', 'BF-A': 'BF.A',
            'BFB': 'BF.B', 'BF-B': 'BF.B',
            'BRKB': 'BRK.B', 'BRK-B': 'BRK.B',
            'BRK/B': 'BRK.B'
        }
        # In Tiingo specific checks:
        # Actually Tiingo documentation uses '-' for dot usually, e.g. BRK-B.
        # But let's stick to simple replace if map fails.
        req_sym = sym.replace('.', '-') 
        
        url = f"https://api.tiingo.com/tiingo/daily/{req_sym}/prices?startDate={start_date_str}&token={API_KEY}"
        
        print(f"[{i+1}/{total}] Fetching {sym} (Req: {req_sym})... ", end='')
        
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            
            if resp.status_code == 200:
                data = resp.json()
                
                # Check format
                if isinstance(data, list) and len(data) > 0:
                    rec_count = len(data)
                    print(f"✅ OK ({rec_count} records)")
                    
                    # Optional: Print first record as sample (User asked for json print)
                    # outputting 1200 lines per ticker is too much, let's print just the summary or 1st line if requested.
                    # User: "print(requestResponse.json()) 이건 예시고... 작업 과정을 콘솔창에 보이게끔해줘"
                    # I will NOT print the full json for every ticker (millions of lines), but showing "OK" is good.
                    
                    # Save to DB
                    batch = []
                    for row in data:
                        d_str = row.get('date')
                        if not d_str: continue
                        r_date = pd.to_datetime(d_str).date()
                        
                        # Parse Fields
                        # Fields: date, open, high, low, close, volume, adjOpen, adjHigh, adjLow, adjClose, adjVolume, divCash, splitFactor
                        
                        prev_close = None # Not calculating change for backfill speed
                        
                        ph = PriceHistory(
                            symbol=t_obj,
                            date=r_date,
                            open=float(row.get('open', 0)),
                            high=float(row.get('high', 0)),
                            low=float(row.get('low', 0)),
                            close=float(row.get('close', 0)),
                            volume=int(row.get('volume', 0)),
                            
                            adj_open=float(row.get('adjOpen')) if row.get('adjOpen') else None,
                            adj_high=float(row.get('adjHigh')) if row.get('adjHigh') else None,
                            adj_low=float(row.get('adjLow')) if row.get('adjLow') else None,
                            adj_close=float(row.get('adjClose')) if row.get('adjClose') else None,
                            adj_volume=int(row.get('adjVolume')) if row.get('adjVolume') else None,
                            
                            div_cash=float(row.get('divCash')) if row.get('divCash') else None,
                            split_factor=float(row.get('splitFactor')) if row.get('splitFactor') else None,
                            
                            updated_at=timezone.now()
                        )
                        batch.append(ph)
                    
                    # Bulk Create for Speed
                    PriceHistory.objects.bulk_create(batch, ignore_conflicts=True)
                    success_count += 1
                    
                else:
                    print(f"⚠️ Empty List returned.")
                    
            elif resp.status_code == 429:
                print(f"❌ Rate Limit (429). Waiting 10s...")
                import time
                time.sleep(10)
                fail_count += 1
            else:
                print(f"❌ Error {resp.status_code}: {resp.text[:50]}")
                fail_count += 1
                
        except Exception as e:
            print(f"❌ Exception: {e}")
            fail_count += 1
            
    print("\n" + "="*60)
    print(f"      COMPLETED: Success {success_count} / Fail {fail_count}      ")
    print("="*60 + "\n")

if __name__ == '__main__':
    reset_and_fetch_tiingo()
