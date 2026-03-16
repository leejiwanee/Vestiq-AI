import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'stockweb.settings')
django.setup()

from updatedata.models import Ticker

def check_ko():
    print("--- Checking for Coca-Cola (KO) ---")
    try:
        t = Ticker.objects.get(symbol='KO')
        print(f"Found: {t.symbol} - {t.name} (Sector: {t.sector})")
        
        # Check Price
        latest_price = t.price_history.order_by('-date').first()
        if latest_price:
            print(f"Latest Price: {latest_price.date} - Close: {latest_price.close}")
        else:
            print("No Price History found.")

        # Check Fund
        latest_fund = t.fundamental_data.order_by('-date').first()
        if latest_fund:
            print(f"Latest Fund: {latest_fund.date} - Market Cap: {latest_fund.market_cap}")
        else:
            print("No Fundamental Data found.")

    except Ticker.DoesNotExist:
        print("KO not found in database.")

if __name__ == '__main__':
    check_ko()
