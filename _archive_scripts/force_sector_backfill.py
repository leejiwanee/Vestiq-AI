
import os
import django
import datetime
import sys

# Django Setup
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "stockweb.settings")
django.setup()

from insight.services import update_daily_sector_performance
from insight.models import SectorPerformance

def run_backfill(days=14):
    today = datetime.date.today()
    print(f"🚀 Starting Forced Backfill for past {days} days...")
    print("=" * 60)
    
    success_count = 0
    
    for i in range(days, 0, -1):
        target_date = today - datetime.timedelta(days=i)
        
        # 주말 체크 (토, 일) - 5:Sat, 6:Sun
        if target_date.weekday() >= 5:
            # print(f"⏭️  Skipping Weekend: {target_date}")
            continue
            
        print(f"🔄 Processing {target_date}...", end="", flush=True)
        try:
            update_daily_sector_performance(target_date=target_date)
            
            # 검증
            count = SectorPerformance.objects.filter(date=target_date).count()
            print(f" ✅ Done. (Sectors: {count})")
            success_count += 1
        except Exception as e:
            print(f" ❌ Error: {e}")

    print("=" * 60)
    print(f"✨ Backfill Complete! Processed {success_count} trading days.")
    
    # 최종 결과 확인 - Bitcoin 섹터
    btc_perf = SectorPerformance.objects.filter(sector="Bitcoin & Crypto").order_by('-date')[:5]
    print("\n[Verification] Recent 'Bitcoin & Crypto' Performance:")
    if btc_perf:
        for p in btc_perf:
            print(f"  📅 {p.date}: {p.change_percent}%")
    else:
        print("  ⚠️ No data found for Bitcoin & Crypto. (Check underlying PriceHistory data)")

if __name__ == "__main__":
    run_backfill()
