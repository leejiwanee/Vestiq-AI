import os
import django
import sys

# Setup Django environment
sys.path.append('/Users/jiwanlee/Code/stockweb')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'stockweb.settings')
django.setup()

from scanner.models import DailyPick

# Filter for any strategy containing "Kumo" (case-insensitive)
kumo_picks = DailyPick.objects.filter(strategy__icontains='kumo')
count = kumo_picks.count()

print(f"Found {count} records containing 'Kumo'. Deleting...")

# Delete them
kumo_picks.delete()

print("Deletion complete.")

# Verify
remaining = DailyPick.objects.filter(strategy__icontains='kumo').count()
print(f"Remaining 'Kumo' records: {remaining}")
