
import os
import django
import datetime
from collections import defaultdict

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "stockweb.settings")
django.setup()

from insight.models import SectorPerformance

def audit_sectors():
    today = datetime.date.today()
    start_date = today - datetime.timedelta(days=14)
    
    all_data = SectorPerformance.objects.filter(date__gte=start_date, date__lte=today)
    
    sector_stats = defaultdict(lambda: {'count': 0, 'total_return': 0.0})
    
    for d in all_data:
        sector_stats[d.sector]['count'] += 1
        sector_stats[d.sector]['total_return'] += d.change_percent
        
    sorted_stats = sorted(sector_stats.items(), key=lambda x: x[1]['total_return'], reverse=True)
    
    print(f"Start Date: {start_date}")
    print(f"End Date: {today}")
    
    with open("sector_audit_result.txt", "w") as f:
        f.write(f"Audit Period: {start_date} ~ {today}\n")
        f.write("="*70 + "\n")
        f.write(f"{'Sector':<30} {'Count':<10} {'2-Week Return'}\n")
        f.write("-" * 70 + "\n")
        for sector, stats in sorted_stats:
             f.write(f"{sector:<30} {stats['count']:<10} {stats['total_return']:.2f}%\n")
        f.write("="*70 + "\n")

if __name__ == "__main__":
    audit_sectors()
