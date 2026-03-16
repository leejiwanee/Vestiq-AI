
from insight.models import SectorPerformance
from datetime import date, timedelta
import sys

today = date.today()
start_date = today - timedelta(days=14)

print(f"--- Verification Report ({start_date} -> {today}) ---")

# Check counts
ai_count = SectorPerformance.objects.filter(date__gte=start_date, sector="Artificial Intelligence").count()
robo_count = SectorPerformance.objects.filter(date__gte=start_date, sector="Robotics").count()
old_count = SectorPerformance.objects.filter(date__gte=start_date, sector="AI & Robotics").count()

print(f"Artificial Intelligence Records: {ai_count}")
print(f"Robotics Records: {robo_count}")
print(f"Old 'AI & Robotics' Records: {old_count}")

# Check if we have enough data (approx 5-10 trading days in 2 weeks)
if ai_count > 0 and robo_count > 0:
    print("✅ SUCCESS: Data found for new sectors.")
else:
    print("❌ WARNING: No data found for new sectors.")

if old_count == 0:
    print("✅ SUCCESS: Old sector cleaned up.")
else:
    print(f"⚠️ WARNING: {old_count} records still exist for old sector.")

# Show latest distinct dates for AI
dates = SectorPerformance.objects.filter(sector="Artificial Intelligence").order_by('-date').values_list('date', flat=True)[:5]
print(f"Latest Dates for AI: {[d.strftime('%Y-%m-%d') for d in dates]}")
