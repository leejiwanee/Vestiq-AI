
from insight.models import SectorPerformance
from datetime import date, timedelta

today = date.today()
start_date = today - timedelta(days=14)

print(f"Checking data from {start_date} to {today}...")

# 1. Check for old "AI & Robotics"
old_sector = SectorPerformance.objects.filter(date__gte=start_date, sector="AI & Robotics")
print(f"Old 'AI & Robotics' count: {old_sector.count()}")

# 2. Check for new sectors
ai_sector = SectorPerformance.objects.filter(date__gte=start_date, sector="Artificial Intelligence")
robotics_sector = SectorPerformance.objects.filter(date__gte=start_date, sector="Robotics")
print(f"New 'Artificial Intelligence' count: {ai_sector.count()}")
print(f"New 'Robotics' count: {robotics_sector.count()}")

# 3. List all distinct sectors for today
todays_sectors = SectorPerformance.objects.filter(date=today).values_list('sector', flat=True)
print(f"\nSectors for Today ({today}):")
for s in todays_sectors:
    print(f"- {s}")
