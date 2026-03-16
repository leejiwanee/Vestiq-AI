
import os
import sys
import django

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'stockweb.settings')
django.setup()

from updatedata.models import FundamentalData

print("Truncating FundamentalData table...")
count = FundamentalData.objects.count()
FundamentalData.objects.all().delete()
print(f"Deleted {count} records.")
print("Done.")
