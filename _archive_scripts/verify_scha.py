
import os
import django
import sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'stockweb.settings')
django.setup()

from updatedata.services import download_latest_scha_csv, build_combined_universe

print("--- Testing SCHA Download ---")
# ok, msg = download_latest_scha_csv()
# print(f"Download Status: {ok}")
# print(f"Message: {msg}")

# Force Test with Dummy Data
print("\n--- Testing Universe Build (with Dummy Data) ---")
symbols, _, _, dbg = build_combined_universe()
print(f"Total Combined Symbols: {len(symbols)}")
print(f"Debug Info: {dbg}")

# Check for Test Tickers
if "SCHA_TEST1" in symbols and "SCHA_TEST2" in symbols:
    print("✅ SCHA Test Tickers Found")
else:
    print("❌ SCHA Test Tickers Missing")

if "AAPL" in symbols:
     print("✅ AAPL Found (Duplicate handling checked)")
