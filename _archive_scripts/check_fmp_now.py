import os
import requests
from dotenv import load_dotenv

load_dotenv()

FMP_API_KEY = os.getenv("FMP_API_KEY")

def test_fmp(symbol="AAPL"):
    if not FMP_API_KEY:
        print("❌ FMP_API_KEY not found in environment.")
        return

    print(f"Testing FMP API for {symbol}...")
    
    # URL being used in services.py
    url = f"https://financialmodelingprep.com/api/v3/historical-price-full/{symbol}?from=2023-01-01&apikey={FMP_API_KEY}"
    
    # Obscure key for print
    safe_url = url.replace(FMP_API_KEY, "HIDDEN_KEY")
    print(f"URL: {safe_url}")
    
    try:
        r = requests.get(url, timeout=10)
        print(f"Status Code: {r.status_code}")
        
        try:
            data = r.json()
            if 'historical' in data:
                print(f"✅ Success! Found {len(data['historical'])} records.")
                print(f"Sample: {data['historical'][0]}")
            elif 'Error Message' in data:
                print(f"❌ API Error Message: {data['Error Message']}")
            else:
                print(f"⚠️ Unexpected Response: {data}")
        except:
            print(f"❌ Response Text (Non-JSON): {r.text[:200]}")
            
    except Exception as e:
        print(f"❌ Request Problem: {e}")

    print("\nAttempting Alternative: historical-chart/1day ...")
    url2 = f"https://financialmodelingprep.com/api/v3/historical-chart/1day/{symbol}?from=2023-01-01&apikey={FMP_API_KEY}"
    try:
        r2 = requests.get(url2, timeout=10)
        print(f"Status: {r2.status_code}")
        if r2.status_code == 200:
             d2 = r2.json()
             if isinstance(d2, list) and len(d2) > 0:
                 print(f"✅ Success (Chart)! Found {len(d2)} records.")
                 print(f"Sample: {d2[0]}")
             else:
                 print(f"⚠️ Empty/Dict: {d2}")
        else:
             print(f"❌ Failed: {r2.text}")
    except Exception as e:
        print(f"❌ Error: {e}")

    # Test 3: serietype=line
    print("\nAttempting Alternative 3: serietype=line ...")
    url3 = f"https://financialmodelingprep.com/api/v3/historical-price-full/{symbol}?serietype=line&from=2023-01-01&apikey={FMP_API_KEY}"
    try:
        r = requests.get(url3, timeout=10)
        print(f"Status: {r.status_code}")
        if r.status_code == 200:
             print("✅ Success (Line)!")
        else:
             print(f"❌ Failed: {r.text[:100]}")
    except: pass

    # Test 4: historical-price-eod/full (as hinted)
    print("\nAttempting Alternative 4: historical-price-eod/full ...")
    url4 = f"https://financialmodelingprep.com/api/v3/historical-price-eod/full/{symbol}?from=2023-01-01&apikey={FMP_API_KEY}"
    try:
        r = requests.get(url4, timeout=10)
        print(f"Status: {r.status_code}")
        if r.status_code == 200:
             print("✅ Success (EOD/Full)!")
        else:
             print(f"❌ Failed: {r.text[:100]}")
    except: pass
    
    # Test 5: v4 bulk?
    print("\nAttempting Alternative 5: v4/historical-price/AAPL/1day ...")
    # v4 standard is often different.
    url5 = f"https://financialmodelingprep.com/api/v4/historical-price/{symbol}/1/day/{'2023-01-01'}/{'2023-12-31'}?apikey={FMP_API_KEY}"
    # or v4/historical-price-bulk?
    try:
        r = requests.get(url5, timeout=10)
        print(f"Status: {r.status_code}")
        if r.status_code == 200:
             print("✅ Success (v4)!")
        else:
             print(f"❌ Failed: {r.text[:100]}")
    except: pass

    # Test 6: Quote (Is key valid at all?)
    print("\nAttempting Quote (Validity Check) ...")
    url6 = f"https://financialmodelingprep.com/api/v3/quote/{symbol}?apikey={FMP_API_KEY}"
    try:
        r = requests.get(url6, timeout=10)
        print(f"Status: {r.status_code}")
        if r.status_code == 200:
             print("✅ Success (Quote)! Key is valid for basic data.")
        else:
             print(f"❌ Fake Key? {r.text}")
    except: pass
    
if __name__ == "__main__":
    test_fmp()
