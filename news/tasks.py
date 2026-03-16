import logging
from celery import shared_task
from .services import fetch_general_news, update_daily_summary

logger = logging.getLogger('cron.news')

def fetch_and_analyze_news():
    """
    Orchestrator for News Collection & Analysis.
    1. Fetches General News (Tiingo) -> Saves to DB
    2. Updates Daily Summary (Keywords, etc.)
    """
    try:
        logger.info("[News Task] Fetching General News...")
        count = fetch_general_news()
        logger.info(f"[News Task] Saved {count} new general articles.")
        
        logger.info("[News Task] Updating Daily Summary...")
        update_daily_summary()
        logger.info("[News Task] Daily Summary Updated.")
        
    except Exception as e:
        logger.error(f"[News Task] Failed: {e}")


@shared_task(name='news.tasks.celery_collect_news')
def celery_collect_news():
    """
    Celery task for scheduled news collection.
    Runs hourly during business hours (9-20 EST, Mon-Fri).
    """
    from utils.market_calendar import is_trading_day
    import datetime as dt
    
    # News can run on non-trading days too, but weekends are skipped
    # via Celery beat schedule (mon-fri)
    
    print("[Celery] Running news collection...")
    fetch_and_analyze_news()
    print("[Celery] News collection complete.")

