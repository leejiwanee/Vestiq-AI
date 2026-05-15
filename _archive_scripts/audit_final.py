
import os
import django
import datetime
from collections import defaultdict

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "stockweb.settings")
django.setup()

from insight.models import SectorPerformance

def audit():
    today = datetime.date.today()
    start_date = today - datetime.timedelta(days=14)
    # Check if we have data
    qs = SectorPerformance.objects.filter(date__gte=start_date)
    count = qs.count()
    
    with open("audit_final_report.txt", "w") as f:
        f.write(f"Total Records: {count}\n")
        if count == 0:
            f.write("NO DATA FOUND\n")
            return

        stats = defaultdict(float)
        for obj in qs:
            stats[obj.sector] += obj.change_percent
            
        sorted_sectors = sorted(stats.items(), key=lambda x: x[1], reverse=True)
        
        f.write("--- TOP SECTORS (Last 14 Days) ---\n")
        for i, (sec, score) in enumerate(sorted_sectors[:10], 1):
            f.write(f"{i}. {sec}: {score:.2f}%\n")

if __name__ == "__main__":
    audit()
