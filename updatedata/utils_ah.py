
import requests
import json
import os
from datetime import datetime, timedelta
from django.utils import timezone
from django.db.models import Max
from .models import Ticker, PriceHistory
from dotenv import load_dotenv

load_dotenv()
FMP_API_KEY = os.getenv("FMP_API_KEY")

def update_aftermarket_prices():
    """
    Fetches After-Market Trade Price from FMP for ALL Tickers 
    and updates the 'close' price of the latest PriceHistory record.
    
    Endpoint: https://financialmodelingprep.com/stable/aftermarket-trade?symbol=AAPL
    Note: Stable endpoint usually supports single ticker. 
    Ideally we need batch. If no batch, we use v4/pre-post-market-trade-batch if available, 
    or just iterate (slow).
    
    Actually, FMP has: v4/batch-pre-post-market-trade/{symbol1,symbol2,...}
    Let's try to use batching for performance.
    """
    if not FMP_API_KEY:
        return 0, "No API Key"

    # 1. Identify Target Date (Latest in PriceHistory)
    # Because we are updating "Today's Close" to "After Hours Close".
    max_date_obj = PriceHistory.objects.aggregate(Max('date'))
    target_date = max_date_obj['date__max']
    
    if not target_date:
        return 0, "No PriceHistory data to update."

    print(f"Update AH: Target Date is {target_date}")

    # 2. Get Tickers involved in that date
    # Optimization: Filter PriceHistory for that date directly
    # ph_qs = PriceHistory.objects.filter(date=target_date).select_related('symbol')
    # Actually, we rely on Ticker objects.
    # Let's get list of symbols.
    ph_qs = PriceHistory.objects.filter(date=target_date)
    symbol_map = {ph.symbol.symbol: ph for ph in ph_qs}
    all_symbols = list(symbol_map.keys())
    
    if not all_symbols:
        return 0, "No symbols found for target date."

    print(f"Update AH: Updating {len(all_symbols)} symbols...")
    
    # Setup Logging
    log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, 'after_hour.log')
    
    import logging
    logger = logging.getLogger('after_hour_logger')
    logger.setLevel(logging.INFO)
    # Avoid duplicate handlers
    if not logger.handlers:
        fh = logging.FileHandler(log_file)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        fh.setFormatter(formatter)
        logger.addHandler(fh)

    from django.core.cache import cache
    cache_key = 'progress_ah_update'
    
    logger.info(f"START: Updating After-Hours Prices for Target Date: {target_date}")
    logger.info(f"Target count: {len(all_symbols)} symbols")

    # 3. Serial Fetch (User Requested: One by One)
    # Target: Max 290 requests per minute.
    # 60s / 290 = ~0.206s per request.
    # We use 0.21s sleep to be safe.
    BATCH_SIZE = 1
    updated_count = 0
    errors = []
    
    # Session for keep-alive
    session = requests.Session()
    
    import time 
    
    total_batches = (len(all_symbols) + BATCH_SIZE - 1) // BATCH_SIZE
    
    for i in range(0, len(all_symbols), BATCH_SIZE):
        time.sleep(0.21) # ~285 req/min
        idx = i // BATCH_SIZE
        progress_pct = int((idx / total_batches) * 100)
        cache.set(cache_key, {'percent': progress_pct, 'message': f'Updating batch {idx+1}/{total_batches}...', 'finished': False}, timeout=300)
        
        batch_syms = all_symbols[i:i+BATCH_SIZE]
        sym_str = ",".join(batch_syms)
        
        url = f"https://financialmodelingprep.com/stable/aftermarket-trade?symbol={sym_str}&apikey={FMP_API_KEY}"
        
        # Retry Logic for Robustness
        max_retries = 5
        success = False
        
        for attempt in range(max_retries):
            try:
                resp = session.get(url, timeout=10)
                
                # Handle Rate Limit (429) explicitly
                if resp.status_code == 429:
                    logger.warning(f"RATE LIMIT (429) for {sym_str}. Sleeping 65s before retry {attempt+1}/{max_retries}...")
                    time.sleep(65) # Wait for minute quota to reset
                    continue
                
                # Handle other server errors (5xx)
                if resp.status_code >= 500:
                    time.sleep(2)
                    continue

                if resp.status_code != 200:
                    logger.error(f"HTTP Error {resp.status_code} for {sym_str}")
                    break # Skip if client error (e.g. 404)

                data = resp.json()
                
                if isinstance(data, list):
                    # ... [Process Data Logic Copied] ...
                    result_map = {item['symbol']: item['price'] for item in data if 'price' in item}
                    rows_to_update = []
                    for sym, price in result_map.items():
                        if sym in symbol_map:
                            ph = symbol_map[sym]
                            if price and price > 0:
                                old_price = ph.close
                                ph.close = price
                                rows_to_update.append(ph)
                                if abs((price - old_price)/old_price) > 0.05: 
                                    logger.info(f"CHANGE: {sym} {old_price} -> {price}")
                    
                    if rows_to_update:
                        PriceHistory.objects.bulk_update(rows_to_update, ['close'])
                        updated_count += len(rows_to_update)
                elif 'Error Message' in data: 
                    # specific FMP error
                    logger.warning(f"API Error for {sym_str}: {data}")
                
                success = True
                break # Exit retry loop on success

            except Exception as e:
                logger.error(f"Connection Error for {sym_str} (Attempt {attempt+1}): {e}")
                time.sleep(2) # Short sleep before retry
        
        if not success:
            errors.append(f"{sym_str} Failed after retries")
            
    # Finalize
    cache.set(cache_key, {'percent': 100, 'message': f'Done! Updated {updated_count} symbols.', 'finished': True}, timeout=300)
    logger.info(f"COMPLETE: Updated {updated_count} symbols. Errors: {len(errors)}")

    return updated_count, f"Updated {updated_count} symbols to AH Prices."
