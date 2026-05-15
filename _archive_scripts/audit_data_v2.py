
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
    
    # 1. Fetch Data
    all_data = SectorPerformance.objects.filter(date__gte=start_date, date__lte=today)
    
    sector_stats = defaultdict(lambda: {'count': 0, 'total_return': 0.0})
    
    for d in all_data:
        sector_stats[d.sector]['count'] += 1
        sector_stats[d.sector]['total_return'] += d.change_percent
        
    sorted_stats = sorted(sector_stats.items(), key=lambda x: x[1]['total_return'], reverse=True)
    
    # 2. Write Report
    with open("audit_result_v2.txt", "w") as f:
        f.write(f"AUDIT REPORT ({start_date} ~ {today})\n")
        f.write("="*60 + "\n")
        f.write(f"{'Sector':<25} {'Count':<6} {'Return'}\n")
        f.write("-" * 60 + "\n")
        
        has_bitcoin = False
        for sector, stats in sorted_stats:
            if "Bitcoin" in sector: has_bitcoin = True
            f.write(f"{sector:<25} {stats['count']:<6} {stats['total_return']:.2f}%\n")
            
        f.write("="*60 + "\n")
        if not has_bitcoin:
            f.write("⚠️ WARNING: Bitcoin sector NOT found in results.\n")
        else:
            f.write("✅ Bitcoin sector found.\n")

if __name__ == "__main__":
    audit_sectors()
