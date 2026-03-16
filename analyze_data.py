import os, sys
import django
from django.db.models import Count

# Helper to setup Django env
sys.path.append(os.getcwd())
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "stockweb.settings")
django.setup()

from updatedata.models import Ticker

print("--- Data Analysis ---")

# 1. Unique Sectors
print("[Sectors]")
sectors = Ticker.objects.values('sector').annotate(count=Count('id')).order_by('-count')
for s in sectors:
    print(f"{s['sector']}: {s['count']}")

# 2. Search for "Quantum"
print("\n[Search: Quantum]")
q_tickers = Ticker.objects.filter(name__icontains="Quantum") | Ticker.objects.filter(industry__icontains="Quantum")
print(f"Found {q_tickers.count()} tickers related to 'Quantum'.")
for t in q_tickers[:10]:
    print(f"[{t.symbol}] Sector: {t.sector} | Industry: {t.industry} | Name: {t.name}")

# 3. Top Industries (by count)
print("\n[Top 10 Industries]")
inds = Ticker.objects.values('industry').annotate(count=Count('id')).order_by('-count')[:10]
for i in inds:
    print(f"{i['industry']}: {i['count']}")
