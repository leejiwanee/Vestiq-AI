from updatedata.tasks import update_intraday_prices, update_todays_close
from scanner.services import scan_symbols, save_scan_results
import logging
import pytz
from django.utils import timezone
from updatedata.models import Ticker, CronJob

logger = logging.getLogger('cron.intraday')

def _check_cron_enabled(job_name):
    try:
        job, created = CronJob.objects.get_or_create(name=job_name)
        if not job.is_active:
            print(f"{job_name} is disabled via Admin.")
            return False
        job.last_run = timezone.now()
        job.save()
        return True
    except Exception as e:
        print(f"Error checking CronJob status: {e}")
        return False

def run_unified_intraday_job():
    """
    [09:00 - 20:00] Unified Intraday Job
    - Runs from 9am to 8pm EST.
    - Always updates 'PriceHistory' with latest data.
    """
    est = pytz.timezone('US/Eastern')
    now_est = timezone.now().astimezone(est)
    
    # Check Market Open (Weekend/Holiday)
    from utils.market_calendar import is_trading_day
    if not is_trading_day(now_est.date()):
        return

    # 09:30 AM to 16:00 PM (4:00 PM) EST
    
    # Check Hour Range
    if not (9 <= now_est.hour <= 16):
        return

    # Start Edge: If 9 AM, run only if >= 9:30
    if now_est.hour == 9 and now_est.minute < 30:
        return

    # End Edge: If 16 PM, run only strictly at 16:00 or earlier (though >16 check handles earlier)
    # Allows 16:00. Skips 16:01+.
    if now_est.hour == 16 and now_est.minute > 0:
        return
    # Enforce 30-minute interval using Last Run Delta
    # User requested: "Every 30 mins" (Change from 15)
    
    try:
        job, created = CronJob.objects.get_or_create(name='update_intraday_candle')
        if not job.is_active:
            # print(f"update_intraday_candle is disabled via Admin.")
            return

        # Check Frequency (30 mins)
        # We allow a small buffer (e.g. 28 mins) to avoid skipping if cron is 1 second fast
        if job.last_run:
            diff = now_est - job.last_run.astimezone(est)
            if diff.total_seconds() < 28 * 60:
                # Less than 28 mins since last run -> Skip
                # print(f"[Intraday] Skipping (Last run {diff.total_seconds()/60:.1f}m ago. Target: 30m).")
                return
        
        # Determine we are going to run
        print(f"[{now_est.strftime('%H:%M')}] [Unified Intraday] Running Scan (30-min)...")
        
        # Update Last Run
        job.last_run = timezone.now()
        job.save()
        
        # Run Task
        from updatedata.tasks import update_intraday_data
        update_intraday_data()
        
    except Exception as e:
        logger.error(f"[Unified Intraday] Error: {e}")

