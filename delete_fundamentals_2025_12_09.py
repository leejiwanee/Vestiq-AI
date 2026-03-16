
import os
import django
import sys
from datetime import date

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'stockweb.settings')
django.setup()

from updatedata.models import FundamentalData

def delete_data():
    target_date = date(2025, 12, 9)
    print(f"Checking for FundamentalData on {target_date}...")
    qs = FundamentalData.objects.filter(date=target_date)
    count = qs.count()
    
    if count > 0:
        deleted_count, _ = qs.delete()
        print(f"✅ Successfully deleted {deleted_count} records for {target_date}.")
    else:
        print(f"ℹ️ No records found for {target_date}.")

if __name__ == "__main__":
    delete_data()
