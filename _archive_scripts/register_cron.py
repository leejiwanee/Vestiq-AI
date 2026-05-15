
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'stockweb.settings')
django.setup()

from updatedata.models import CronJob

def register_jobs():
    jobs = [
        'update-sector-leaders-daily',
        'update-fundamentals-daily',
        'update-price-history-daily',
        'intraday-prices',
        'news-collection'
    ]
    
    for job_name in jobs:
        obj, created = CronJob.objects.get_or_create(name=job_name)
        if created:
            print(f"Created CronJob: {job_name}")
        else:
            print(f"CronJob exists: {job_name}")

if __name__ == '__main__':
    register_jobs()
