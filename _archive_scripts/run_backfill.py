
import os
import django
import sys
import logging

# Setup Django Environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'stockweb.settings')
django.setup()

# Configure Logging to show progress
logging.basicConfig(level=logging.INFO)

from updatedata.tasks import run_manual_backfill_5y

def main():
    print("Starting Manual 5-Year Backfill...")
    try:
        run_manual_backfill_5y()
        print("Backfill Complete.")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    main()
