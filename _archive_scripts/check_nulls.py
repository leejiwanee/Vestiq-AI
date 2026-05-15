
import os
import django
from django.conf import settings

# Setup Django
import sys
sys.path.append('/Users/jiwanlee/Code/stockweb')
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "stockweb.settings")
django.setup()

from updatedata.models import Ticker
from django.db.models import Q

def check_nulls():
    print("Checking Ticker table for Null/Empty values...")
    
    # Fields to check
    fields = ['symbol', 'name', 'sector', 'industry', 'market']
    
    issues = []
    
    for field in fields:
        # Check for Null
        null_count = Ticker.objects.filter(**{f"{field}__isnull": True}).count()
        # Check for Empty String
        empty_count = Ticker.objects.filter(**{f"{field}": ""}).count()
        
        if null_count > 0 or empty_count > 0:
            issues.append(f"{field}: {null_count} Nulls, {empty_count} Empty strings")
            
            # Print sample
            if null_count > 0:
                print(f"  Sample Null {field}:", Ticker.objects.filter(**{f"{field}__isnull": True}).values_list('id', flat=True)[:5])
            if empty_count > 0:
                print(f"  Sample Empty {field}:", Ticker.objects.filter(**{f"{field}": ""}).values_list('id', flat=True)[:5])

    if not issues:
        print("No null or empty values found in key fields.")
    else:
        print("Issues found:")
        for i in issues:
            print(" - " + i)

if __name__ == "__main__":
    check_nulls()
