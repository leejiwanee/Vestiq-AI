
import os
import django
import datetime

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "stockweb.settings")
django.setup()

from updatedata.models import PriceHistory
from insight.models import SectorPerformance

def verify():
    # 1. Check Ticker Data (MSTR)
    today = datetime.date.today()
    start_date = today - datetime.timedelta(days=14)
    
    mstr_count = PriceHistory.objects.filter(
        symbol__symbol='MSTR', 
        date__gte=start_date
    ).count()
    
    # 2. Check Sector Performance (Bitcoin & Crypto)
    sector_count = SectorPerformance.objects.filter(
        sector='Bitcoin & Crypto',
        date__gte=start_date
    ).count()
    
    with open("verification_result.txt", "w") as f:
        f.write(f"MSTR_COUNT:{mstr_count}\n")
        f.write(f"SECTOR_COUNT:{sector_count}\n")
        
        if mstr_count >= 8 and sector_count >= 8:
            f.write("STATUS:COMPLETE\n")
        else:
            f.write("STATUS:INCOMPLETE\n")

if __name__ == "__main__":
    verify()
