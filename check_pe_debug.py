
import os
import django
from datetime import date
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'stockweb.settings')
django.setup()

from insight.models import SectorPerformance

print("Checking PE for 'Communication'...")
try:
    obj = SectorPerformance.objects.get(date=date.today(), sector="Communication")
    print(f"Sector: {obj.sector}")
    print(f"PE Ratio (raw): {repr(obj.pe_ratio)}")
    print(f"Type: {type(obj.pe_ratio)}")
except SectorPerformance.DoesNotExist:
    print("Sector not found.")
