
import requests
import os
import django
from django.conf import settings
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'stockweb.settings')
django.setup()

api_key = settings.FMP_API_KEY

symbols = ['AAPL', 'MSFT', 'NVDA']

for s in symbols:
    print(f"\n--- Checking {s} ---")
    
    # 1. Quote (v3) - often has 'pe'
    url_q = f"https://financialmodelingprep.com/api/v3/quote/{s}?apikey={api_key}"
    try:
        res_q = requests.get(url_q, timeout=10)
        if res_q.status_code == 200 and res_q.json():
             q = res_q.json()[0]
             print(f"[Quote V3] PE: {q.get('pe')}, EPS: {q.get('eps')}, MktCap: {q.get('marketCap')}")
        else:
            print(f"[Quote V3] Error/Empty: {res_q.status_code}")
    except Exception as e:
        print(f"[Quote V3] Exception: {e}")

    # 2. Key Metrics TTM (Stable)
    url_km = f"https://financialmodelingprep.com/stable/key-metrics-ttm?symbol={s}&apikey={api_key}"
    try:
        res_km = requests.get(url_km, timeout=10)
        if res_km.status_code == 200 and res_km.json():
            km = res_km.json()[0]
            print(f"[Key Metrics TTM] PE: {km.get('peRatioTTM')}, PB: {km.get('pbRatioTTM')}")
    except Exception as e:
         print(f"[Key Metrics] Exception: {e}")

    # 4. Profile (Stable)
    url_p = f"https://financialmodelingprep.com/stable/profile?symbol={s}&apikey={api_key}"
    try:
        res_p = requests.get(url_p, timeout=10)
        if res_p.status_code == 200 and res_p.json():
             p = res_p.json()[0]
             print(f"[Profile] MktCap: {p.get('mktCap')}, {p.get('marketCap')}")
             print(f"[Profile] Keys: {list(p.keys())}")
    except Exception as e:
        print(f"[Profile] Exception: {e}")


