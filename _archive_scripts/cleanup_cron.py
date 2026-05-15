
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'stockweb.settings')
django.setup()

from updatedata.models import CronJob

def clean_jobs():
    # Names to DELETE
    to_delete = [
        'update-fundamentals-daily',
        'update-price-history-daily',
        'intraday-prices',
        'news-collection'
    ]
    
    deleted_count, _ = CronJob.objects.filter(name__in=to_delete).delete()
    print(f"Deleted {deleted_count} duplicate jobs.")
    
    # Rename Sector Leaders
    try:
        job = CronJob.objects.get(name='update-sector-leaders-daily')
        job.name = 'update_sector_leaders'
        job.save()
        print("Renamed 'update-sector-leaders-daily' to 'update_sector_leaders'")
    except CronJob.DoesNotExist:
        # Create if missing (using correct name)
        CronJob.objects.get_or_create(name='update_sector_leaders')
        print("Created 'update_sector_leaders'")

if __name__ == '__main__':
    clean_jobs()
