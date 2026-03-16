
import os
import django
import logging
import sys
import datetime

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'stockweb.settings')
django.setup()

# Setup Logging
logger = logging.getLogger('insight')
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(levelname)s: %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.INFO)

from insight.services import update_daily_sector_performance
from insight.models import SectorPerformance
from django.utils import timezone

print("Running update_daily_sector_performance()...")
update_daily_sector_performance()

print("\n--- Verifying Database ---")
objs = SectorPerformance.objects.filter(date=datetime.date.today())
if not objs.exists():
    print("No records for today. Checking yesterday/prev msg...")
    objs = SectorPerformance.objects.order_by('-updated_at')[:5]

for obj in objs:
    print(f"Sector: {obj.sector}, PE: {obj.pe_ratio} (Updated: {obj.updated_at})")
