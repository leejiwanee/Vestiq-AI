
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
# apps.py checks: if any(x in sys.argv for x in ['makemigrations', 'migrate', 'shell', 'dbshell'])
sys.argv.append('shell')

django.setup()

from django.conf import settings
from django.utils import timezone
from updatedata.models import Ticker, PriceHistory, BackupPriceHistory

def run_manual_backfill_tiingo():
    """
    Smart Backfill: Checks for missing PriceHistory dates (Business Days) and fills gaps via Tiingo.
    Also saves to BackupPriceHistory.
    """
    api_key = settings.TIINGO_API_KEY
    if not api_key:
        print("❌ Error: TIINGO_API_KEY is missing/empty.")
        print("Please check your .env or settings.py")
        return

    print("=== Smart Price History Backfill (Tiingo) + Backup ===")
    
    # 2. Get Targets
    tickers_qs = Ticker.objects.all().order_by('symbol')
    total = tickers_qs.count()
    print(f"🎯 Target: {total} Tickers")
    # Removed start delay
    # print("⏳ Starting in 3 seconds...")
    # time.sleep(3)

    # 3. Parameters
    today = dt.date.today()
    # 5 years lookback
    start_date = today - timedelta(days=365*5)
    start_str = start_date.strftime('%Y-%m-%d')
    
    # Generate expected business days (approximate market days)
    expected_range = pd.bdate_range(start=start_date, end=today)
    expected_dates = set(d.date() for d in expected_range)
    total_expected = len(expected_dates)
    
    success_count = 0
    fail_count = 0
    skip_count = 0
    
    # Helper for Symbol Map
    def get_tiingo_symbol(sym):
        # User requested BRK.B -> BRK-B (and BF.B fix)
        map_fix = {
            'BRK.B': 'BRK-B', 
            'BRK/B': 'BRK-B',
            'BF.B': 'BF-B',
            'BF-B': 'BF-B',
            'BF.A': 'BF-A',
            'BF-A': 'BF-A'
        }
        if sym in map_fix: return map_fix[sym]
        return sym.replace('.', '-') # Generic fallback

    # 4. Processing Loop
    for i, t_obj in enumerate(tickers_qs):
        sym = t_obj.symbol
        
        # A. Check existing data
        existing_dates_qs = PriceHistory.objects.filter(
            symbol=t_obj, 
            date__gte=start_date
        ).values_list('date', flat=True)
        
        existing_dates = set(existing_dates_qs)
        
        # B. Calculate Gaps
        common = expected_dates.intersection(existing_dates)
        
        current_count = len(existing_dates)
        threshold_count = total_expected - 80 # Generous holiday buffer
        
        if current_count >= threshold_count:
            # Check recency
            recent_missing = False
            if existing_dates:
                latest = max(existing_dates)
                if (today - latest).days > 4: 
                    recent_missing = True
            
            if not recent_missing:
                # Data looks good enough
                skip_count += 1
                continue
        
        print(f"[{i+1}/{total}] {sym}: Found Gaps ({current_count}/{total_expected}). Fetching...", end=' ')
        sys.stdout.flush()
        
        # C. Tiingo Request
        req_sym = get_tiingo_symbol(sym)
        url = f"https://api.tiingo.com/tiingo/daily/{req_sym}/prices?startDate={start_str}&token={api_key}"
        headers = {'Content-Type': 'application/json'}
        
        try:
            # Removed Rate Limit Sleep
            res = requests.get(url, headers=headers, timeout=15)
            
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, list):
                    count_saved = 0
                    for row in data:
                        d_str = row.get('date')
                        if not d_str: continue
                        
                        r_date = pd.to_datetime(d_str).date()
                        
                        # 1. Main Table
                        PriceHistory.objects.update_or_create(
                            symbol=t_obj,
                            date=r_date,
                            defaults={
                                'open': float(row.get('open', 0) or 0),
                                'high': float(row.get('high', 0) or 0),
                                'low': float(row.get('low', 0) or 0),
                                'close': float(row.get('close', 0) or 0),
                                'volume': int(row.get('volume', 0) or 0),
                                'adj_close': float(row.get('adjClose', 0)) if row.get('adjClose') else None,
                                'updated_at': timezone.now()
                            }
                        )
                        
                        # 2. Backup Table
                        BackupPriceHistory.objects.update_or_create(
                            symbol=t_obj,
                            date=r_date,
                            defaults={
                                'open': float(row.get('open', 0) or 0),
                                'high': float(row.get('high', 0) or 0),
                                'low': float(row.get('low', 0) or 0),
                                'close': float(row.get('close', 0) or 0),
                                'volume': int(row.get('volume', 0) or 0),
                                'adj_close': float(row.get('adjClose', 0)) if row.get('adjClose') else None,
                                'updated_at': timezone.now()
                            }
                        )
                        count_saved += 1
                    
                    print(f"✅ Filled {count_saved}.")
                    success_count += 1
                else:
                    print(f"⚠️ Empty.")
            elif res.status_code == 429:
                print(f"⛔ Rate Limit (429).")
                # Removed Sleep
                fail_count += 1
            else:
                print(f"❌ HTTP {res.status_code}")
                fail_count += 1
                
        except Exception as e:
            print(f"❌ Err: {e}")
            fail_count += 1
            
    print("\n" + "="*40)
    print(f"🎉 Smart Backfill Complete!")
    print(f"skipped: {skip_count} (Data OK)")
    print(f"updated: {success_count} (Filled Gaps)")
    print(f"failed:  {fail_count}")

if __name__ == "__main__":
    run_manual_backfill_tiingo()
