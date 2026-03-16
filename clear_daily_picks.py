#!/usr/bin/env python
"""
Script to delete all DailyPick records from the database.
This clears old signals generated with the previous logic.
"""

import os
import sys
import django

# Setup Django environment
sys.path.insert(0, '/Users/jiwanlee/Code/stockweb')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from scanner.models import DailyPick

def main():
    count = DailyPick.objects.count()
    print(f"Found {count} DailyPick records in database.")
    
    if count > 0:
        DailyPick.objects.all().delete()
        print(f"✅ Deleted all {count} DailyPick records.")
    else:
        print("No records to delete.")
    
    # Verify
    remaining = DailyPick.objects.count()
    print(f"Remaining records: {remaining}")

if __name__ == "__main__":
    main()
