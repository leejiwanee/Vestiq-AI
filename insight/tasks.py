import logging
import datetime
from celery import shared_task
from django.utils import timezone
from .services import update_daily_sector_performance
from utils.market_calendar import is_trading_day

logger = logging.getLogger('insight')

@shared_task(name='insight.tasks.celery_update_sector_leaders')
def celery_update_sector_leaders():
    """
    Daily Task (16:05 EST) to update Sector Leaders & Performance.
    Only runs on valid trading days.
    """
    if not is_trading_day():
        logger.info("[Sector Leaders] Market closed today. Skipping update.")
        return

    from cron.daily_jobs import ensure_sector_leaders_update
    ensure_sector_leaders_update()
