
import requests
import os
import django
from django.conf import settings

def debug_fmp_adbe():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'stockweb.settings')
    django.setup()
    api_key = settings.FMP_API_KEY
    
    symbol = 'ADBE'
    # Exact URL used in tasks.py
    url = f"https://financialmodelingprep.com/stable/key-metrics-ttm?symbol={symbol}&apikey={api_key}"
    print(f"Fetching: {url.replace(api_key, '***')}")
    
    try:
        r = requests.get(url)
        print(f"Status Code: {r.status_code}")
        print(f"Response: {r.text[:500]}...") # Print first 500 chars
        
        if r.status_code == 200:
            data = r.json()
            print(f"Data Type: {type(data)}")
            if isinstance(data, list):
                print(f"List Length: {len(data)}")
    except Exception as e:
        print(f"Exception: {e}")

if __name__ == "__main__":
    debug_fmp_adbe()
