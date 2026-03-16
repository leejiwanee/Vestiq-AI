
import requests
import os
import django
# from django.conf import settings # Can't use settings easily in standalone script if not setup, but I can just hardcode or read env for testing.
# Or better, just modify check_fmp_now.py or similar.

def check_fmp():
    # Hardcoded or Env API Key for testing
    api_key = os.environ.get('FMP_API_KEY', '7cac1d115e5b3260cbed723708304d9c') # Using a placeholder or I should fetch from settings if possible
    # Wait, I shouldn't hardcode keys if I can avoid it.
    
    # Try to load from settings
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'stockweb.settings')
    django.setup()
    from django.conf import settings
    api_key = settings.FMP_API_KEY
    
    # Try v3 with correct format
    symbol = 'MSFT'
    # https://financialmodelingprep.com/v3/key-metrics-ttm/MSFT?apikey=...
    url = f"https://financialmodelingprep.com/v3/key-metrics-ttm/{symbol}?apikey={api_key}"
    print(f"Fetching: {url.replace(api_key, '***')}")
    
    try:
        r = requests.get(url)
        # Check text first
        if r.status_code != 200:
            print(f"Error {r.status_code}: {r.text}")
            return
            
        data = r.json()
        data = r.json()
        import json
        
        if isinstance(data, list) and len(data) > 0:
            rec = data[0]
            print(f"Keys found: {list(rec.keys())}")
            print(f"EPS: {rec.get('netIncomePerShareTTM')}")
            print(f"BVPS: {rec.get('bookValuePerShareTTM')}")
            print(f"PE TTM (FMP): {rec.get('peRatioTTM')}")
        else:
            print("No data or empty list.")
            print(json.dumps(data, indent=2))
        
        # Also check profile/quote for price?
        # User wants us to calculate based on returned values ??
        # "PER PBR these data calculate in our code and put into table"
        # Implies we calculate PE = Price / EPS.
        
    except Exception as e:
        print(e)
        
if __name__ == '__main__':
    check_fmp()
