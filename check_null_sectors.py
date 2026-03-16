
import os
import django
import sys

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'stockweb.settings')
django.setup()

from insight.models import SectorPerformance
from datetime import date

today = date.today()
print(f"Checking Null PE for date: {today}")

null_sectors = SectorPerformance.objects.filter(date=today, pe_ratio__isnull=True)
if not null_sectors.exists():
    print("No NULL PE sectors found for today (maybe previous dates have them?).")
    # Check latest entry for each sector
    all_sectors = SectorPerformance.objects.values('sector').distinct()
    for s in all_sectors:
        sec_name = s['sector']
        latest = SectorPerformance.objects.filter(sector=sec_name).order_by('-date').first()
        if latest and latest.pe_ratio is None:
             print(f"Sector: {sec_name} (Latest Date: {latest.date}) => PE is NULL")
else:
    for obj in null_sectors:
        print(f"Sector: {obj.sector} => PE is NULL")
