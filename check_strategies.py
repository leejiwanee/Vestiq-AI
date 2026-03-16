import os
import django
import sys

# Setup Django environment
sys.path.append('/Users/jiwanlee/Code/stockweb')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'stockweb.settings')
django.setup()

from scanner.models import DailyPick

# Get all unique strategy names
strategies = DailyPick.objects.values_list('strategy', flat=True).distinct()

print("Existing Strategies in Database:")
for s in strategies:
    print(f"- '{s}'")
