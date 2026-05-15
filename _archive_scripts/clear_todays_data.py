
import os
import sys
import django
import datetime

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'stockweb.settings')
django.setup()

from updatedata.models import PriceHistory, FundamentalData

today = datetime.date.today()
print(f"Deleting data for today: {today}")

ph_count = PriceHistory.objects.filter(date=today).count()
PriceHistory.objects.filter(date=today).delete()
print(f"Deleted {ph_count} PriceHistory records.")

fd_count = FundamentalData.objects.filter(date=today).count()
FundamentalData.objects.filter(date=today).delete()
print(f"Deleted {fd_count} FundamentalData records.")

print("Done.")
