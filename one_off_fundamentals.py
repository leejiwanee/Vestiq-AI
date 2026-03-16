
import os
import django
import sys

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'stockweb.settings')
django.setup()

from updatedata.models import Ticker
from updatedata.tasks import _update_fundamentals
from django.db.models import Count

def run():
    print("--- ONE-OFF FUNDAMENTALS BACKFILL ---")
    
    # 1. Identify Target Tickers (Missing Fundamentals)
    # Note: 'fundamentals' is the related_name for FundamentalData
    targets = list(Ticker.objects.annotate(fc=Count('fundamentals')).filter(fc=0))
    total = len(targets)
    print(f"Target Count: {total} tickers missing fundamental data.")
    
    if total == 0:
        print("All tickers have fundamental data. Nothing to do.")
        return

    # 2. Execute existing logic
    # _update_fundamentals handles: 
    #   - FMP Key Metrics TTM fetch
    #   - Rate Limiting (MAX_REQ_PER_MIN = 270 inside tasks.py)
    #   - Saving to DB
    print("Starting background update process...")
    _update_fundamentals(targets)
    print("\nDONE.")

if __name__ == "__main__":
    run()
