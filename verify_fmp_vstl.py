import os
import django
from decimal import Decimal
import requests
from django.conf import settings

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'stockweb.settings')
django.setup()

ticker = "VSTL"
fmp_key = getattr(settings, 'FMP_API_KEY', None)

print(f"Checking FMP for {ticker} with key ending in ...{str(fmp_key)[-4:]}")

if fmp_key:
    try:
        url = f"https://financialmodelingprep.com/api/v3/quote/{ticker}?apikey={fmp_key}"
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            data = r.json()
            if data and isinstance(data, list) and 'price' in data[0]:
                print(f"SUCCESS: Price is {data[0]['price']}")
            else:
                print(f"FAILED: Data format unexpected: {data}")
        else:
             print(f"FAILED: Status {r.status_code}")
    except Exception as e:
        print(f"ERROR: {e}")
else:
    print("SKIPPED: No API Key")
