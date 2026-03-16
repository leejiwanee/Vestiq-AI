
import os
import django
import sys
from datetime import date
import pytz

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'stockweb.settings')
django.setup()

from django.utils import timezone
from updatedata.models import CronJob
from utils.market_calendar import is_trading_day

def check_status():
    est = pytz.timezone('US/Eastern')
    now_est = timezone.now().astimezone(est)
    today = now_est.date()

    print(f"Current Time (EST): {now_est}")
    print(f"Today (EST): {today}")
    print(f"Is Trading Day: {is_trading_day(today)}")
    
    print("\n--- CronJob Status ---")
    jobs = CronJob.objects.all()
    if not jobs:
        print("No CronJob records found.")
    
    for job in jobs:
        last_run_str = "None"
        if job.last_run:
            last_run_est = job.last_run.astimezone(est)
            last_run_str = last_run_est.strftime('%Y-%m-%d %H:%M:%S')
            
        locked_str = "None"
        if job.locked_at:
             locked_est = job.locked_at.astimezone(est)
             locked_str = locked_est.strftime('%Y-%m-%d %H:%M:%S')

        print(f"Job: {job.name}")
        print(f"  Active: {job.is_active}")
        print(f"  Running: {job.is_running}")
        print(f"  Last Run: {last_run_str}")
        print(f"  Locked At: {locked_str}")
        
        # Logic check
        if job.last_run:
             last_run_date = job.last_run.astimezone(est).date()
             if last_run_date == today:
                 print(f"  -> Would SKIP (Already ran today)")
             else:
                 print(f"  -> Would RUN (Last run was {last_run_date})")
        else:
             print(f"  -> Would RUN (Never ran)")
        
        if job.is_running:
             print(f"  -> Would SKIP (Currently Running/Locked)")

        print("-" * 20)

if __name__ == "__main__":
    check_status()
