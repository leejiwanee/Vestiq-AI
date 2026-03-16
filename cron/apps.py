# cron/apps.py

import os
from django.apps import AppConfig

class CronConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "cron"

    def ready(self):
        # runserver의 실제 서버 프로세스에서만 실행 (재로딩 방지)
        if os.environ.get("RUN_MAIN") != "true":
            return

        print("[cron] CronConfig.ready() → starting background scheduler")

        from apscheduler.schedulers.background import BackgroundScheduler
        # from .daily import maybe_run_daily_update # Removed

        from .universe import maybe_run_universe_update

        # 스케줄러 생성
        scheduler = BackgroundScheduler()

        # 1분마다 실행 여부 체크 (내부적으로 시간과 날짜를 확인하므로 부하 없음)
        # 1. Daily Schedule: Run exactly at 16:15 EST
        import pytz
        from datetime import timedelta
        from django.utils import timezone as django_timezone
        
        est = pytz.timezone('US/Eastern')


        
        # 2. Daily Price History (16:15 EST, Mon-Fri)
        from .daily_jobs import ensure_price_history_update
        scheduler.add_job(ensure_price_history_update, 'cron', day_of_week='mon-fri', hour=16, minute=15, timezone=est, id='daily_price_history')

        # 3. Daily Fundamentals (16:30 EST, Mon-Fri)
        from .daily_jobs import ensure_fundamentals_update
        scheduler.add_job(ensure_fundamentals_update, 'cron', day_of_week='mon-fri', hour=17, minute=0, timezone=est, id='daily_fundamentals')


        
        # 4. News Collection (Hourly)
        from .news_jobs import run_news_collection_job
        scheduler.add_job(run_news_collection_job, 'cron', minute=0, timezone=est, id='news_collection_job')

        scheduler.start()