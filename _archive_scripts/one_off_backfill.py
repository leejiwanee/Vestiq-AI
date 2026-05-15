
import os
import sys
import django
import time
import requests
import pandas as pd
from datetime import timedelta

# 1. Setup Django Environment
# Assumes this script is in the root directory (same level as manage.py)
sys.path.append(os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'stockweb.settings') # Verify 'config.settings' is correct for this project
django.setup()

from django.conf import settings
from django.utils import timezone
from updatedata.models import Ticker, PriceHistory

def run_backfill():
    print("=== One-off Backfill Script: FMP Price History ===")
    
    # Configuration
    API_KEY = settings.FMP_API_KEY
    if not API_KEY:
        print("Error: FMP_API_KEY not set in settings.")
        return

    # Rate Limit: Max 295 req/min => ~0.22s delay
    SLEEP_DELAY = 0.22 
    
    # 2. Identify Target Tickers (< 1200 days history)
    print("Identifying tickers with insufficient history (checking < 1200 days)...")
    
    all_tickers = Ticker.objects.all().order_by('symbol')
    targets = []
    
    # Count check
    for t in all_tickers:
        cnt = PriceHistory.objects.filter(symbol=t).count()
        if cnt < 1200:
            targets.append(t)
    
    total_targets = len(targets)
    print(f"Found {total_targets} tickers to backfill.")
    
    if total_targets == 0:
        return

    # 3. Execution Loop
    updated_count = 0
    
    for i, ticker in enumerate(targets):
        symbol = ticker.symbol
        req_sym = symbol.replace('.', '-') # FMP format
        
        print(f"[{i+1}/{total_targets}] Fetching {symbol}...", end='', flush=True)
        
        try:
            # Use STABLE endpoint: historical-price-eod/full
            # Fetch 5 years (approx 1825 days)
            from_date = (timezone.now().date() - timedelta(days=1825)).strftime('%Y-%m-%d')
            url = f"https://financialmodelingprep.com/stable/historical-price-eod/full?symbol={req_sym}&from={from_date}&apikey={API_KEY}"
            
            # Rate Limiting
            time.sleep(SLEEP_DELAY)
            
            resp = requests.get(url, timeout=10)
            
            if resp.status_code == 429:
                print(" Rate Limit (429). Sleeping 60s...", end='', flush=True)
                time.sleep(61)
                resp = requests.get(url, timeout=10) # Retry once
            
            if resp.status_code == 200:
                data = resp.json()
                
                # FMP 'historical-price-eod/full' returns a List[Dict] directly
                if isinstance(data, list):
                    hist_list = data
                elif isinstance(data, dict) and 'historical' in data: # Fallback just in case
                    hist_list = data['historical']
                else:
                    hist_list = []

                if hist_list:
                     # Sort by date asc
                     hist_list.sort(key=lambda x: x.get('date'))
                     
                     for row in hist_list:
                         d_str = row.get('date')
                         if not d_str: continue
                         
                         r_date = pd.to_datetime(d_str).date()
                         
                         PriceHistory.objects.update_or_create(
                             symbol=ticker,
                             date=r_date,
                             defaults={
                                 'open': row.get('open'),
                                 'high': row.get('high'),
                                 'low': row.get('low'),
                                 'close': row.get('close'),
                                 'volume': row.get('volume'),
                                 'adj_close': row.get('adjClose'), # Might be None for this endpoint
                                 'updated_at': timezone.now()
                             }
                         )
                     
                     updated_count += 1
                     print(f" OK ({len(hist_list)} records)")
                else:
                     print(" No Data")
            else:
                print(f" HTTP {resp.status_code}")
                
        except Exception as e:
            print(f" Err: {e}")
            
    print(f"\nCompleted! Backfilled {updated_count}/{total_targets} tickers.")

if __name__ == "__main__":
    run_backfill()
