import os
import django
import sys
from django.conf import settings

sys.path.append('/Users/jiwanlee/Code/stockweb')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'stockweb.settings')
django.setup()

from updatedata.models import Ticker
from updatedata.tasks import _update_fundamentals

print("Starting Full Fundamental Update (Repairing Data)...")
tickers = Ticker.objects.all()
_update_fundamentals(tickers)
print("Full Update Complete.")
