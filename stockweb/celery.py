# stockweb/celery.py
import os
from celery import Celery
from celery.schedules import crontab

# Set default Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'stockweb.settings')

app = Celery('stockweb')

# Load config from Django settings with CELERY namespace
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks in all installed apps
app.autodiscover_tasks()

# Celery Beat Schedule
# Note: All market tasks check is_trading_day() inside the task
app.conf.beat_schedule = {
    'update_sector_leaders': {
        'task': 'insight.tasks.celery_update_sector_leaders',
        'schedule': crontab(hour=16, minute=5, day_of_week='mon-fri'),
    },
    'update_price_history': {
        'task': 'updatedata.tasks.celery_update_daily_close',
        'schedule': crontab(hour=16, minute=10, day_of_week='mon-fri'),
    },
    'update_fundamental_data': {
        'task': 'updatedata.tasks.celery_update_fundamentals',
        'schedule': crontab(hour=16, minute=30, day_of_week='mon-fri'),
    },
    

}

# Timezone (EST)
app.conf.timezone = 'America/New_York'

@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')

