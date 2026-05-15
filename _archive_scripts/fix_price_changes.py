
import os
import django
import sys
import logging
import pandas as pd
from django.db import transaction

# Setup Django Environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'stockweb.settings')
django.setup()

from updatedata.models import PriceHistory, Ticker

def fix_price_changes():
    print("\n" + "="*50)
    print("      CALCULATING HISTORICAL CHANGES      ")
    print("="*50 + "\n")
    
    tickers_qs = Ticker.objects.all().order_by('symbol')
    total = tickers_qs.count()
    
    print(f"Target: {total} tickers. Processing...")
    
    for i, t_obj in enumerate(tickers_qs):
        try:
            # Load all history for ticker
            # Optimize: Only fetch id, close, date
            qs = PriceHistory.objects.filter(symbol=t_obj).order_by('date').values('id', 'date', 'close') # Removed prev_close
            
            df = pd.DataFrame(tuple(qs), columns=['id', 'date', 'close'])
            
            if df.empty: continue
            
            # Calculate Shift
            df['prev_close_calc'] = df['close'].shift(1)
            
            # Calculate Changes
            # change = close - prev
            # pct = (change / prev) * 100
            
            # We only need to update rows where calculation is possible
            df_upd = df.dropna(subset=['prev_close_calc'])
            
            updates = []
            for _, row in df_upd.iterrows():
                prev = row['prev_close_calc']
                curr = row['close']
                
                if prev == 0: continue
                
                chg = curr - prev
                pct = (chg / prev) * 100
                
                # Create Model Instance for bulk_update (only with ID and fields to update)
                p = PriceHistory(id=row['id'])
                p.change_amount = round(chg, 4)
                p.change_percent = round(pct, 4)
                # Should we save prev_close too? Model doesn't seem to have 'prev_close' column based on earlier views.
                # Let's check model... 'prev_close' variable was used in tasks.py, but is it a field?
                # tasks.py used: change_amount = current_close - prev_close
                # It didn't save prev_close to DB.
                
                updates.append(p)
                
            if updates:
                # Bulk Update
                PriceHistory.objects.bulk_update(updates, ['change_amount', 'change_percent'], batch_size=1000)
                
            print(f"[{i+1}/{total}] {t_obj.symbol}: Updated {len(updates)} records.", end='\r')
            
        except Exception as e:
            print(f"\n❌ Error {t_obj.symbol}: {e}")

    print("\n" + "="*50)
    print("      COMPLETED      ")
    print("="*50 + "\n")

if __name__ == '__main__':
    fix_price_changes()
