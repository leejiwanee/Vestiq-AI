
import os
import sys
import django
import requests
from django.conf import settings

# 1. Setup Django for settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'stockweb.settings')
django.setup()

api_key = settings.FMP_API_KEY
symbol = "GLXY"

def test_endpoint(endpoint):
    url = f"https://financialmodelingprep.com/stable/{endpoint}?symbol={symbol}&period=annual&limit=10&apikey={api_key}"
    print(f"Testing: {url.replace(api_key, 'HIDDEN')}")
    try:
        r = requests.get(url, timeout=10)
        print(f"Status: {r.status_code}")
        if r.status_code == 200:
            data = r.json()
            if not data:
                print("Result: EMPTY LIST []")
            else:
                print(f"Result: Found {len(data)} records.")
                print(f"Date: {data[0].get('date')}, Revenue: {data[0].get('revenue')}")
        else:
            print(f"Error Body: {r.text}")
    except Exception as e:
        print(f"Exception: {e}")

print("--- Testing Income Statement (Stable) ---")
test_endpoint("income-statement")

print("\n--- Testing Balance Sheet (Stable) ---")
test_endpoint("balance-sheet-statement")
