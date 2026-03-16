
import os
import sys
import django
import datetime

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'stockweb.settings')
django.setup()

from updatedata.models import PriceHistory, FundamentalData

target_date = datetime.date(2025, 12, 8)
print(f"Deleting data for target date: {target_date}")

ph_count = PriceHistory.objects.filter(date=target_date).count()
PriceHistory.objects.filter(date=target_date).delete()
print(f"Deleted {ph_count} PriceHistory records.")

fd_count = FundamentalData.objects.filter(date=target_date).count()
FundamentalData.objects.filter(date=target_date).delete()
print(f"Deleted {fd_count} FundamentalData records.")

print("Done.")
