
# cron/news_jobs.py

import logging
from django.utils import timezone
from news.tasks import fetch_and_analyze_news

logger = logging.getLogger('cron.news')

def run_news_collection_job():
    """
    뉴스 수집 Cron Job
    - DB 저장 및 감성 분석 자동 수행
    """
    logger.info(f"[Cron-News] Starting news collection at {timezone.now()}...")

    # Check Market Open (Weekend/Holiday)
    from utils.market_calendar import is_trading_day
    if not is_trading_day(timezone.now().date()):
        logger.info("[Cron-News] Skipping (Weekend/Holiday).")
        return
    
    # Check Toggle
    from updatedata.models import CronJob
    try:
        job, created = CronJob.objects.get_or_create(name='update_news')
        if not job.is_active:
             print("[Cron-News] Disabled via Admin.")
             return
        job.last_run = timezone.now()
        job.save()
    except Exception as e:
        print(f"Error checking CronJob: {e}")
    
    try:
        # Import here to avoid circular dependency
        from news.services import fetch_and_analyze_news
        
        # 뉴스 fetch + 분석 + 저장 (services.py에 모든 로직 포함)
        fetch_and_analyze_news()
        
        print(f"[Cron-News] News collection completed successfully!")
        
    except Exception as e:
        print(f"[Cron-News] Error: {e}")
        logger.error(f"News collection failed: {e}", exc_info=True)
