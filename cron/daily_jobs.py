# cron/daily_jobs.py

import logging
import pytz
from django.utils import timezone
from updatedata.models import CronJob
from updatedata.tasks import update_daily_close, run_update_fundamentals, run_update_ticker_list
from insight.services import update_daily_sector_performance
from utils.market_calendar import is_trading_day

logger = logging.getLogger('cron.daily_jobs')

def ensure_price_history_update(force=False):
    """
    [CRON] Price History Update
    Schedule: 16:05 EST, Mon-Fri
    Logic: Checks if trading day, updates if active.
    """
    return _run_daily_job('update_price_history', update_daily_close, force=force)

def ensure_sector_leaders_update(force=False):
    """
    [CRON] Sector Leaders Update
    Schedule: 16:15 EST, Mon-Fri
    Logic: Checks if trading day, updates if active.
    """
    return _run_daily_job('update_sector_leaders', update_daily_sector_performance, force=force)

def ensure_fundamentals_update(force=False):
    """
    [CRON] Fundamentals Update
    Schedule: 16:20 EST, Mon-Fri
    Logic: Checks if trading day, updates if active.
    """
    return _run_daily_job('update_fundamental_data', run_update_fundamentals, force=force)


def _run_daily_job(job_name, task_func, force=False):
    # Check Time & Trading Day
    est = pytz.timezone('US/Eastern')
    now_est = timezone.now().astimezone(est)
    today = now_est.date()

    if not force and not is_trading_day(today):
        logger.info(f"[{job_name}] Skipping: Not a trading day ({today}).")
        # print(f"DEBUG: [{job_name}] Skipping: Not a trading day ({today})")
        return False

    # Check Locking (Session Dedup)
    # -----------------------------
    from django.db import transaction
    
    # print(f"DEBUG: [{job_name}] Entering transaction block...")
    try:
        with transaction.atomic():
            # Lock row immediately
            job, created = CronJob.objects.select_for_update().get_or_create(name=job_name)
            # print(f"DEBUG: [{job_name}] Lock acquired. Active={job.is_active}, Running={job.is_running}, LastRun={job.last_run}")
            
            # Check Enabled
            if not force and not job.is_active:
                logger.info(f"[{job_name}] Skipping: Disabled.")
                return False

            # Check Already Run
            if not force and job.last_run:
                last_run_date = job.last_run.astimezone(est).date()
                if last_run_date == today:
                    logger.info(f"[{job_name}] Skipping: Already ran today.")
                    return False

            # Check Is Running
            if job.is_running:
                # Check Timeout (1 Hour Safety)
                if job.locked_at:
                    locked_time = job.locked_at
                    
                    # Ensure both are consistent
                    now = timezone.now()
                    if timezone.is_aware(now) and timezone.is_naive(locked_time):
                        locked_time = timezone.make_aware(locked_time)
                    elif timezone.is_naive(now) and timezone.is_aware(locked_time):
                        locked_time = timezone.make_naive(locked_time)
                    
                    elapsed = (now - locked_time).total_seconds()
                    if elapsed < 3600: # 60 mins
                        logger.warning(f"[{job_name}] Skipping: Currently RUNNING (Locked at {locked_time.strftime('%H:%M:%S')})")
                        print(f"DEBUG: [{job_name}] Skipping: Currently RUNNING (Locked at {locked_time.strftime('%H:%M:%S')})")
                        return
                    else:
                        logger.warning(f"[{job_name}] Lock Stalled (>60m). Resetting lock and proceeding.")
                else:
                    logger.warning(f"[{job_name}] Lock Stalled (No time). Resetting lock.")

            # 2. SET LOCK
            job.is_running = True
            job.locked_at = timezone.now()
            job.save()

    except Exception as e:
        logger.error(f"Error checking lock for {job_name}: {e}")
        print(f"Error checking lock for {job_name}: {e}")
        return

    try:
        # Run Task
        logger.info(f"[{job_name}] Starting...")
        print(f"[{job_name}] Starting... (Time: {timezone.now()})")
        task_func()
        
        # Update Status (Success)
        job.last_run = timezone.now()
        job.save()
        logger.info(f"[{job_name}] Completed successfully.")
        print(f"[{job_name}] Completed successfully.")
        
        
    finally:
        # 3. RELEASE LOCK
        # Re-fetch job to be safe (though not strictly necessary if no concurrency)
        # But we are outside transaction now.
        try:
            job = CronJob.objects.get(name=job_name)
            job.is_running = False
            job.locked_at = None
            job.save()
        except:
            pass
    return True

def wait_for_lock(job_name, timeout=3600):
    """
    Helper to wait for a specific job to finish.
    """
    from updatedata.models import CronJob
    import time
    start = time.time()
    while time.time() - start < timeout:
        try:
            # Refresh from DB
            job = CronJob.objects.get(name=job_name)
            if not job.is_running:
                return True
            # If running, wait
            logger.info(f"[WaitLock] Waiting for {job_name} to finish...")
            time.sleep(10)
        except CronJob.DoesNotExist:
            return True # Not running
    return False
