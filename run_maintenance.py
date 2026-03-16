
import os
import django
import sys
import logging

# Setup Django Environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'stockweb.settings')
django.setup()

logging.basicConfig(level=logging.INFO)
from updatedata.tasks import run_manual_backfill_5y, verify_and_repair_data

def main():
    print("\n" + "="*50)
    print("      VESTIQ DATA MAINTENANCE SCRIPT      ")
    print("="*50 + "\n")
    
    # 1. Main Backfill (Fast YFinance)
    print("[1/2] Executing Primary Backfill (YFinance)...")
    try:
        run_manual_backfill_5y()
    except KeyboardInterrupt:
        print("\n[!] Aborted by user.")
        return
    except Exception as e:
        print(f"\n[!] Error in primary backfill: {e}")

    # 2. Verify and Repair
    print("\n[2/2] Verifying Data & Attempting Repairs...")
    try:
        verify_and_repair_data()
    except Exception as e:
        print(f"\n[!] Error in verification: {e}")

    print("\n" + "="*50)
    print("      ALL TASKS COMPLETED      ")
    print("="*50 + "\n")

if __name__ == '__main__':
    main()
