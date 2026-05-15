
import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'stockweb.settings')
django.setup()

from insight.models import SectorPerformance
from datetime import date

print("Checking SectorPerformance for today...")
objs = SectorPerformance.objects.filter(date=date.today())
for o in objs:
    print(f"Sector: {o.sector}, Rank: {o.rank}")

