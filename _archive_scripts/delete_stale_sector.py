
import os
import django
from datetime import date
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'stockweb.settings')
django.setup()

from insight.models import SectorPerformance

target = "Theme: Quantum Computing"
print(f"Deleting '{target}' for today...")
count, _ = SectorPerformance.objects.filter(date=date.today(), sector=target).delete()
print(f"Deleted {count} entries.")
