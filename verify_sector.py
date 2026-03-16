import os, sys
import django
import time

# Helper to setup Django env
sys.path.append(os.getcwd())
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "stockweb.settings")
django.setup()

from insight.services import update_daily_sector_performance
from insight.models import SectorPerformance
from datetime import date

print("--- Starting Verification Script ---")

# 1. Run Update
print("Running update_daily_sector_performance()...")
start = time.time()
update_daily_sector_performance()
end = time.time()
print(f"Update finished in {end - start:.2f} seconds.")

# 2. Check Database
today = date.today()
sectors = SectorPerformance.objects.filter(date=today)
count = sectors.count()
print(f"Found {count} SectorPerformance records for today {today}.")

if count > 0:
    print("\nSample Data:")
    for s in sectors[:3]:
        print(f"[{s.sector}] Change: {s.change_percent}%")
        print(f"  Leaders Count: {len(s.leaders_data)}")
        if s.leaders_data:
            top = s.leaders_data[0]
            print(f"  Top Leader: {top.get('symbol')} ({top.get('company_name')}) Cap: {top.get('mkt_cap')}")
else:
    print("WARNING: No data found.")

print("--- Verification Complete ---")
