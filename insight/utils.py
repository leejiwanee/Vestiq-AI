import time
import yfinance as yf
import pandas as pd
import random

def safe_yf_download(tickers, max_retries=5, initial_delay=1, **kwargs):
    """
    Robust wrapper for yf.download with exponential backoff for rate limits.
    """
    delay = initial_delay
    for attempt in range(max_retries):
        try:
            data = yf.download(tickers, **kwargs)
            if data is not None and not data.empty:
                return data
            # If empty, it might be valid (no data) or an error. 
            # yfinance usually prints errors but returns empty df.
            # We'll assume empty is valid but if it's a transient error we can't easily know.
            # However, if it throws an exception, we catch it.
            return data
        except Exception as e:
            print(f"[safe_yf_download] Attempt {attempt+1}/{max_retries} failed: {e}")
            if "Too Many Requests" in str(e) or "429" in str(e):
                # Rate limit hit
                sleep_time = delay + random.uniform(0, 1)
                print(f"   -> Rate limit hit. Sleeping {sleep_time:.2f}s...")
                time.sleep(sleep_time)
                delay *= 2 # Exponential backoff
            else:
                # Other error, might be transient
                time.sleep(delay)
                
    print(f"[safe_yf_download] All {max_retries} attempts failed.")
    return pd.DataFrame()

def safe_get_fast_info(ticker_obj, key):
    """
    Safely access fast_info with error handling.
    """
    try:
        fi = getattr(ticker_obj, "fast_info", None)
        if fi is None: return None
        return getattr(fi, key, None)
    except Exception:
        return None
