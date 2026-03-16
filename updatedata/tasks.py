
import logging
import time
import pytz
import pandas as pd
from .services import (
    download_latest_iwm_csv,
    build_combined_universe,
    fetch_fmp_prices
)
from datetime import datetime, timedelta
import datetime as dt_module
from django.utils import timezone
from updatedata.models import Ticker, PriceHistory, FundamentalData
from insight.services import themes  # Import custom sector themes
from utils.tiingo_client import TiingoClient
import yfinance as yf

# Optional Celery import
try:
    from celery import shared_task
except ImportError:
    # Fallback: no-op decorator if Celery not installed
    def shared_task(**kwargs):
        def decorator(func):
            return func
        return decorator

# --- Admin / Cron Compatibility Wrappers ---

def update_todays_close(symbols=None):
    """Alias for Daily Close Update"""
    update_daily_close()



def update_prices_tiingo(symbols):
    """Deprecated: Was used for historical sync."""
    pass

def run_update_fundamentals():
    """Wrapper for manual trigger."""
    symbols = list(Ticker.objects.values_list('symbol', flat=True))
    
    # 1. Console Output
    print(f"[Fundamentals] Starting update for {len(symbols)} tickers...")
    
        
    logger = logging.getLogger('cron')
    logger.info(f"[Fundamentals] Starting update for {len(symbols)} tickers from Ticker table")
    
    _update_fundamentals(symbols)

@shared_task(name='updatedata.tasks.celery_update_fundamentals')
def celery_update_fundamentals():
    """Celery task for scheduled fundamentals update (16:30 EST)."""
    # Use unified job runner to track execution/prevent duplicates
    from cron.daily_jobs import ensure_fundamentals_update
    print("[Celery] Triggering ensure_fundamentals_update...")
    ensure_fundamentals_update()

@shared_task(name='updatedata.tasks.celery_update_daily_close')
def celery_update_daily_close():
    """Celery task for scheduled price update."""
    from cron.daily_jobs import ensure_price_history_update
    ensure_price_history_update()

def reset_stale_jobs():
    """
    [Startup] Cleans up zombies (tasks that were running when server died).
    Only resets jobs locked > 2 hours ago to prevent resetting active jobs from other workers.
    """
    from updatedata.models import CronJob
    from datetime import timedelta
    
    # Safety margin: Only reset locks older than 2 hours
    threshold = timezone.now() - timedelta(hours=2)
    
    stales = CronJob.objects.filter(is_running=True, locked_at__lt=threshold)
    count = stales.count()
    if count > 0:
        logger.warning(f"[Startup] Found {count} OLD stale locks (< {threshold}). Resetting them.")
        stales.update(is_running=False, locked_at=None)
    else:
        logger.info("[Startup] No stale locks found.")

def run_startup_recovery():
    """
    [Startup Check]
    Checks for stale data and recovers daily scheduled jobs strictly sequentially.
    Enforces a system-wide lock to prevent multiple workers from running this simultaneously.
    Adds a 1-minute delay between tasks to reduce load.
    """
    import os
    import fcntl
    import datetime as dt
    
    # 1. System-wide Startup Lock (File Lock)
    lock_file_path = "/tmp/vestiq_startup_recovery.lock"
    lock_file = open(lock_file_path, 'w')
    
    try:
        # Try to acquire an exclusive non-blocking lock
        fcntl.lockf(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except IOError:
        # Another instance is already running
        logger.info(f"[Startup] Another instance is running recovery (Lock held: {lock_file_path}). Exiting this thread.")
        return

    # Startup Log File
    startup_log = "logs/startup.log"
    def log_startup(msg):
        print(msg) # Verify console output
        logger.info(msg)
        try:
            with open(startup_log, "a") as f:
                f.write(f"[{dt.datetime.now()}] {msg}\n")
        except: pass

    # Initialize Log (Truncate)
    try:
        with open(startup_log, "w") as f:
            f.write(f"[{dt.datetime.now()}] === Startup Recovery Started (PID: {os.getpid()}) ===\n")
    except: pass

    try:
        log_startup(f"=== [Startup] Beginning Data Recovery Check (PID: {os.getpid()}) ===")
        
        # 0. Cleanup Stale Locks
        try:
            reset_stale_jobs()
            log_startup("[Startup] Stale locks reset checked.")
        except Exception as e:
            log_startup(f"[Startup] Stale reset failed: {e}")
            logger.error(f"[Startup] Stale reset failed: {e}")
    
        # 1. Check History Gap (Backfill)
        try:
            from django.db.models import Max
            last_date = PriceHistory.objects.aggregate(Max('date'))['date__max']
            today = dt_module.date.today()
            
            # If no history, or gap > 1 day
            if not last_date:
                start_date = today - timedelta(days=365*5) # 5 Years
            else:
                start_date = last_date + timedelta(days=1)
                
            if start_date < today:
                log_startup(f"[Startup] Found history gap from {start_date} to {today}. Auto-backfill disabled to save Tiingo quota.")
                # _backfill_history() 
            else:
                log_startup("[Startup] Price History is up to date.")
                
        except Exception as e:
            log_startup(f"[Startup] History check failed: {e}")
            logger.error(f"[Startup] History check failed: {e}")
    
        # 2. Check Daily Scheduled Jobs (Missed Run Recovery) - DISABLED BY USER REQUEST
        # User prefers to manually trigger updates if server starts late.
        # Celery beat will still trigger future jobs if server is up.
        log_startup("[Startup] Automatic recovery of missed daily jobs is DISABLED. Please check/run updates manually if needed.")
        
        # try:
        #     from utils.market_calendar import is_trading_day
        #     from cron.daily_jobs import ensure_price_history_update, ensure_fundamentals_update, ensure_sector_leaders_update, wait_for_lock
        #     
        #     # Use Django Timezone for consistency and easier mocking
        #     est = pytz.timezone('US/Eastern')
        #     now_est = timezone.now().astimezone(est)
        #     today = now_est.date()
        #
        #     if is_trading_day(today):
        #          log_startup(f"[Startup] Trading Day Detected ({today}). Checking missed schedules...")
        #          
        #          # Helper to sleep with logging
        #          def sleep_with_limit(seconds, reason):
        #              log_startup(f"[Startup] Sleeping {seconds}s ({reason})...")
        #              time.sleep(seconds)
        #
        #          # A. Sector Leaders (Target: 16:05)
        #          if now_est.hour > 16 or (now_est.hour == 16 and now_est.minute >= 5):
        #               log_startup("[Startup] Checking Sector Leaders...")
        #               updated = ensure_sector_leaders_update()
        #               
        #               # Wait for it to finish if it started (though 'ensure' usually returns None, checking lock is safer)
        #               wait_for_lock('update_sector_leaders')
        #               
        #               if updated: # Only sleep if we actually ran something? Or always for safety? User said "1 min wait".
        #                   sleep_with_limit(60, "Spacing between tasks")
        #               else:
        #                   # If it was already done, maybe we don't need to sleep 60s, but let's be safe if user wants strict separation.
        #                   # Check if it *just* finished or verified as done.
        #                   # Just sleep 60s to be compliant with "process 1 task at a time ... 1 min rest"
        #                   sleep_with_limit(60, "Spacing just in case")
        #
        #          # B. Price History (Target: 16:10)
        #          if now_est.hour > 16 or (now_est.hour == 16 and now_est.minute >= 10):
        #               log_startup("[Startup] Checking Price History set...")
        #               ensure_price_history_update()
        #               wait_for_lock('update_price_history')
        #               sleep_with_limit(60, "Spacing between tasks")
        #               
        #          # C. Fundamentals (Target: 16:30)
        #          if now_est.hour > 16 or (now_est.hour == 16 and now_est.minute >= 30):
        #               log_startup("[Startup] Checking Fundamentals set...")
        #               ensure_fundamentals_update()
        #     
        #     else:
        #          log_startup(f"[Startup] Today ({today}) is NOT a trading day. Skipping daily jobs.")
    
        # except Exception as e:
        #     log_startup(f"[Startup] Daily Job Recovery failed: {e}")
        #     logger.error(f"[Startup] Daily Job Recovery failed: {e}")
    
        log_startup("=== [Startup] Recovery Check Completed ===")

    finally:
        # Release Lock
        fcntl.lockf(lock_file, fcntl.LOCK_UN)
        lock_file.close()


def _backfill_history(ticker=None, force=False):
    """
    Backfills 5 Years of Price Data via Tiingo API (Serial).
    URL: https://api.tiingo.com/tiingo/daily/{ticker}/prices?startDate=...
    """
    import requests
    from django.conf import settings
    
    API_KEY = settings.TIINGO_API_KEY
    if not API_KEY:
        logger.error("TIINGO_API_KEY missing.")
        return

    today = dt_module.date.today()
    start_date = today - timedelta(days=365*5) # 5 Years
    
    if ticker: 
        tickers_qs = [ticker]
        total = 1
    else:
        # If full backfill requested
        tickers_qs = Ticker.objects.all()
        total = tickers_qs.count()

    logger.info(f"=== [Backfill History] Started (Tiingo) for {total} tickers ===")
    _set_progress('progress_price_history', 0, "Initializing Backfill (Tiingo)...")

    headers = {'Content-Type': 'application/json'}
    batch_size = 10
    updated_count = 0

    # Robust Symbol Helper (Local def or import if refactored)
    def get_tiingo_symbol(sym):
        map_fix = {
            'LENB': 'LEN.B', 'LEN-B': 'LEN.B',
            'CWENA': 'CWEN.A', 'CWEN-A': 'CWEN.A',
            'BFA': 'BF.A', 'BF-A': 'BF.A',
            'BFB': 'BF.B', 'BF-B': 'BF.B',
            'BRKB': 'BRK.B', 'BRK-B': 'BRK.B',
            'BRK/B': 'BRK.B'
        }
        if sym in map_fix: return map_fix[sym]
        return sym

    # Iterate
    # If qs is list (single ticker), check logic
    iterable = tickers_qs if isinstance(tickers_qs, list) else tickers_qs

    for i, t_obj in enumerate(iterable):
        try:
            req_sym = get_tiingo_symbol(t_obj.symbol)
            s_str = start_date.strftime('%Y-%m-%d')
            
            url = f"https://api.tiingo.com/tiingo/daily/{req_sym}/prices?startDate={s_str}&token={API_KEY}"
            
            resp = requests.get(url, headers=headers, timeout=15) # slightly longer timeout for big history
            
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    # Bulk insert usually faster, but update_or_create safer for backfill overlap
                    # Let's stick to update_or_create for safety unless speed critical
                    # Tiingo returns sorted usually.
                    
                    for row in data:
                        d_str = row.get('date')
                        if not d_str: continue
                        r_date = pd.to_datetime(d_str).date()
                        
                        PriceHistory.objects.update_or_create(
                            symbol=t_obj,
                            date=r_date,
                            defaults={
                                'open': float(row.get('open', 0)),
                                'high': float(row.get('high', 0)),
                                'low': float(row.get('low', 0)),
                                'close': float(row.get('close', 0)),
                                'volume': int(row.get('volume', 0)),
                                'adj_close': float(row.get('adjClose', 0)) if row.get('adjClose') else None,
                                'updated_at': timezone.now()
                            }
                        )
                    updated_count += 1
                else:
                    logger.warning(f"Tiingo Rate Limit on {t_obj.symbol}")
                
        except Exception as e:
            # Handle Foreign Key failure (Case: Ticker List updated while this ran)
            # 1452: Cannot add or update a child row: a foreign key constraint fails
            if "1452" in str(e) or "foreign key constraint" in str(e):
                try:
                    # Retry with fresh Ticker object
                    new_ticker = Ticker.objects.get(symbol=t_obj.symbol)
                    # Use recursion or loop for retry? Just duplicate logic for simplicity here or set t_obj?
                    # Since we are inside loop, we can just continue but we lose this data.
                    # Best effort: Try one more time loop for this data.
                    if 'data' in locals() and isinstance(data, list):
                        for row in data:
                            d_str = row.get('date')
                            if not d_str: continue
                            r_date = pd.to_datetime(d_str).date()
                            
                            PriceHistory.objects.update_or_create(
                                symbol=new_ticker,
                                date=r_date,
                                defaults={
                                    'open': float(row.get('open', 0)),
                                    'high': float(row.get('high', 0)),
                                    'low': float(row.get('low', 0)),
                                    'close': float(row.get('close', 0)),
                                    'volume': int(row.get('volume', 0)),
                                    'adj_close': float(row.get('adjClose', 0)) if row.get('adjClose') else None,
                                    'updated_at': timezone.now()
                                }
                            )
                        updated_count += 1
                        logger.info(f"Recovered FK Error for {t_obj.symbol}")
                except Ticker.DoesNotExist:
                        # Ticker deleted and not yet recreated. Skip.
                        # logger.debug(f"Skipping {t_obj.symbol} (Not found in DB)")
                        pass
                except Exception as retry_e:
                    logger.error(f"Failed recovery for {t_obj.symbol}: {retry_e}")
            else:
                logger.error(f"Error backfilling {t_obj.symbol}: {e}")
            pass
            
        # Progress
        if (i + 1) % batch_size == 0 or (i + 1) == total:
             pct = int(((i+1) / total) * 100)
             msg = f"Backfilling {i+1}/{total}"
             _set_progress('progress_price_history', pct, msg)
             print(f"[Backfill] {msg}", end='\r')

    print("")
    logger.info(f"=== [Backfill] Completed. Updated {updated_count}/{total} tickers. ===")
    if not ticker:
        _set_progress('progress_price_history', 100, f"Completed. Backfilled {updated_count} tickers.", is_finished=True)
            



# --- Helper for Progress Tracking ---
from django.core.cache import cache

def _set_progress(msg_key, percent, message, is_finished=False):
    """
    Sets progress in cache for 5 minutes.
    Data: {'percent': int, 'message': str, 'finished': bool}
    """
    # 0 <= percent <= 100
    cache.set(msg_key, {
        'percent': percent, 
        'message': message, 
        'finished': is_finished
    }, timeout=300)

# ------------------------------------

def run_update_ticker_list(force_update=False):
    """
    Refactored Ticker Update:
    1. Collects symbols from S&P500, Nasdaq100, Russell1000.
    2. Batches them to FMP Profile API.
    3. Updates Ticker table with full metadata.
    4. Removes obsolete tickers (Soft Truncate).
    
    Progress Key: 'progress_ticker_list'
    """
    _set_progress('progress_ticker_list', 0, "Starting Ticker List Update (FMP Profile)...")
    logger.info("Starting Ticker Update via FMP Profile...")
    
    import requests
    from io import StringIO
    import ssl
    import os
    from django.conf import settings
    
    # [SSL Fix]
    try:
        ssl._create_default_https_context = ssl._create_unverified_context
    except AttributeError:
        pass

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36"
    }
    
    # 1. Collect Symbols
    collected_symbols = set()
    
    # --- S&P 500 ---
    _set_progress('progress_ticker_list', 5, "Fetching S&P 500...")
    try:
        url_sp = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
        r_sp = requests.get(url_sp, headers=headers)
        sp_df = pd.read_html(StringIO(r_sp.text))[0]
        sp_symbols = sp_df['Symbol'].tolist()
        collected_symbols.update(sp_symbols)
        logger.info(f"S&P 500: Added {len(sp_symbols)} symbols")
    except Exception as e:
        logger.error(f"S&P 500 Fetch failed: {e}")

    # --- Nasdaq 100 ---
    _set_progress('progress_ticker_list', 10, "Fetching Nasdaq 100...")
    try:
        url_nd = 'https://en.wikipedia.org/wiki/Nasdaq-100'
        r_nd = requests.get(url_nd, headers=headers)
        nd_dfs = pd.read_html(StringIO(r_nd.text))
        nd_count = 0
        for df in nd_dfs:
            if 'Ticker' in df.columns:
                nd_syms = df['Ticker'].tolist()
                collected_symbols.update(nd_syms)
                nd_count = len(nd_syms)
                break
            elif 'Symbol' in df.columns:
                nd_syms = df['Symbol'].tolist()
                collected_symbols.update(nd_syms)
                nd_count = len(nd_syms)
                break
        if nd_count > 0:
            logger.info(f"Nasdaq 100: Added {nd_count} symbols")
    except Exception as e:
        logger.error(f"Nasdaq 100 Fetch failed: {e}")

    # --- Russell 1000 ---
    _set_progress('progress_ticker_list', 15, "Fetching Russell 2000...")
    try:
        from updatedata.services import fetch_russell2000_df
        rus_df = fetch_russell2000_df()
        if rus_df is not None and not rus_df.empty:
            # Find symbol column
            cols = rus_df.columns
            sym_col = next((c for c in cols if 'ticker' in c.lower() or 'symbol' in c.lower()), None)
            if sym_col:
                # Clean strings
                rus_syms = rus_df[sym_col].astype(str).str.strip().str.upper().tolist()
                rus_syms = [s for s in rus_syms if s != 'NAN']
                collected_symbols.update(rus_syms)
                logger.info(f"Russell: Added {len(rus_syms)} symbols")
    except Exception as e:
        logger.error(f"Russell 2000 Fetch failed: {e}")

    # --- SCHA (Schwab Small Cap) ---
    _set_progress('progress_ticker_list', 18, "Fetching SCHA Small Cap...")
    try:
        from updatedata.services import fetch_scha_df
        scha_df = fetch_scha_df()
        if scha_df is not None and not scha_df.empty:
            # Find symbol column
            cols = scha_df.columns
            sym_col = next((c for c in cols if 'ticker' in c.lower() or 'symbol' in c.lower()), None)
            if sym_col:
                # Clean strings and filter out invalid
                scha_syms = scha_df[sym_col].astype(str).str.strip().str.upper().tolist()
                scha_syms = [s for s in scha_syms if s != 'NAN' and s and not any(char.isdigit() for char in s) and len(s) <= 10]
                collected_symbols.update(scha_syms)
                logger.info(f"SCHA: Added {len(scha_syms)} symbols")
    except Exception as e:
        logger.error(f"SCHA Fetch failed: {e}")

    # --- Custom Sector Preservation (Vestiq Picks) ---
    # Ensure symbols used in Custom Sectors (Bitcoin, Cloud, etc.) are NEVER deleted
    # and are included in the update cycle.
    _set_progress('progress_ticker_list', 19, "Adding Custom Sector Tickers...")
    try:
        custom_count = 0
        for theme_name, symbols in themes.items():
            for s in symbols:
                collected_symbols.add(s)
                custom_count += 1
        logger.info(f"Custom Sectors: Preserved {custom_count} symbols from insight.services.themes")
    except Exception as e:
        logger.error(f"Custom Sector Preservation failed: {e}")

    # 2. Process Symbols (Map & Filter)
    _set_progress('progress_ticker_list', 20, "Processing Symbols...")
    
    final_symbols = set()
    BLACKLIST = {'MSFUT', 'FAZ5', 'XTSLA', 'ESZ5', 'ETD_USD', 'HEIA', 'MOGA'}
    
    for s in collected_symbols:
        s = s.strip().upper()
        
        # Mapping Logic
        # BRK.B -> BRK-B
        s = s.replace('.', '-') 
        
        # Explicit Fixes (Just in case replace all dots was too aggressive? No, FMP uses dashes mostly)
        # But 'BRK.B' specifically requested as 'BRK-B'.
        # Previous logic: 'BFA' -> 'BF-A'.
        
        # If it was BFA/BFB in source, map it
        if s == 'BFA': s = 'BF-A'
        if s == 'BFB': s = 'BF-B'
        if s == 'BRKB': s = 'BRK-B'
        
        if s in BLACKLIST:
            continue
        if not s:
            continue
            
        final_symbols.add(s)

    sorted_ticker_list = sorted(list(final_symbols))
    total_tickers = len(sorted_ticker_list)
    logger.info(f"Total Unique Tickers to Update: {total_tickers}")
    
    # 3. Batch Fetch FMP Profile
    api_key = os.environ.get("FMP_API_KEY", "")
    
    # Debug log removed as per user request (legacy: debug_ticker.log)
    
    
    if not api_key:
        logger.error("No FMP API Key found!")
        _set_progress('progress_ticker_list', 100, "Error: No API Key", is_finished=True)
        return
        
    batch_size = 100 # FMP allows bulk
    updated_count = 0
    
    import time
    
    # Switch to Sequential Processing (User constraints / API limitations)
    
    # Init Log
    log_file = "logs/tickers.log"
    with open(log_file, "w") as f:
        f.write(f"[{timezone.now()}] Starting Sequential Update for {total_tickers} tickers.\n")
    
    for i, sym in enumerate(sorted_ticker_list):
        # Rate Limit: Max 300 req/min => 1 req every 0.2s.
        # Use 0.23s to be very safe (~260 req/min) to prevent ANY data loss.
        time.sleep(0.23)
        
        # Progress Update (Every 50)
        if i % 50 == 0:
             progress_pct = 20 + int((i / total_tickers) * 75)
             msg = f"Updating {sym} ({i}/{total_tickers})..."
             _set_progress('progress_ticker_list', progress_pct, msg)
             print(f"[Ticker List] {msg}") # Console Output
             with open(log_file, "a") as f:
                 f.write(f"[{timezone.now()}] Progress: {i}/{total_tickers} ({sym})\n")
        
        try:
            url_prof = f"https://financialmodelingprep.com/stable/profile?symbol={sym}&apikey={api_key}"
            res = requests.get(url_prof, timeout=10)
            
            # --- 429 Retry Logic ---
            if res.status_code == 429:
                logger.warning(f"Rate Limit Hit (429) on {sym}. Sleeping 60s...")
                print(f"⚠️ [Ticker List] Rate Limit 429 Hit on {sym}. Sleeping 60s...")
                with open(log_file, "a") as f: f.write(f"[{timezone.now()}] WARN: Rate Limit 429 Hit on {sym}. Sleeping 60s...\n")
                time.sleep(61)
                try:
                    res = requests.get(url_prof, timeout=10) # Retry once
                except: pass
            # -----------------------
            
            if res.status_code == 200:
                try:
                    data = res.json()
                    # Response is [ {profile...} ]
                    if data and isinstance(data, list) and len(data) > 0:
                        prof = data[0]
                        
                        # Update DB
                        Ticker.objects.update_or_create(
                            symbol=sym,
                            defaults={
                                'name': prof.get('companyName'),
                                'sector': prof.get('sector'),
                                'industry': prof.get('industry'),
                                'market': prof.get('exchange'), # User requested 'exchange' (not ShortName)
                                'beta': _safe_float(prof.get('beta')),
                                'last_dividend': _safe_float(prof.get('lastDiv')),
                                'price_range': prof.get('range'),
                                'ceo': prof.get('ceo'),
                                'full_time_employees': str(prof.get('fullTimeEmployees') or ''),
                                'description': prof.get('description'),
                                'image': prof.get('image'),
                                'ipo_date': _parse_date(prof.get('ipoDate')),
                                'is_etf': bool(prof.get('isEtf')),
                                'is_actively_trading': bool(prof.get('isActivelyTrading')),
                                'dcf': _safe_float(prof.get('dcf')),
                                'updated_at': timezone.now()
                            }
                        )
                        updated_count += 1
                        print(f"✅ {sym}", end='\r')

                        # Log unexpected empty fields for monitoring
                        if not prof.get('ipoDate'):
                             with open(log_file, "a") as f:
                                f.write(f"[{timezone.now()}] Info: {sym} has no ipoDate.\n")

                    else:
                        # Empty list or error dict
                        print(f"❌ {sym}: Empty/Invalid Data")
                        with open(log_file, "a") as f:
                            f.write(f"[{timezone.now()}] Error: {sym} returned empty/invalid data: {data}\n")
                            
                except Exception as parse_err:
                    print(f"❌ {sym}: JSON Parse Error")
                    with open(log_file, "a") as f:
                        f.write(f"[{timezone.now()}] Error: {sym} JSON Parse Failed: {parse_err}\n")
            else:
                print(f"❌ {sym}: API {res.status_code}")
                with open(log_file, "a") as f:
                    f.write(f"[{timezone.now()}] Error: {sym} API Status {res.status_code} - {res.text[:100]}\n")
                
        except Exception as conn_err:
            logger.error(f"Req Error {sym}: {conn_err}")
            print(f"❌ {sym}: Network Error")
            with open(log_file, "a") as f:
                f.write(f"[{timezone.now()}] Error: {sym} Network Error: {conn_err}\n")
            
    # 4. cleanup (Soft Truncate)
    if not final_symbols or len(final_symbols) < 100:
        logger.error(f"Sanity Check Failed: Only {len(final_symbols)} symbols found. Skipping cleanup to prevent data loss.")
        print(f"❌ [Ticker List] Sanity Check Failed: Only {len(final_symbols)} symbols found. Aborting cleanup.")
        _set_progress('progress_ticker_list', 100, "Error: Failed to collect ticker list (Wiki/Russell). Aborting cleanup.", is_finished=True)
        return {'total': updated_count, 'deleted': 0}

    # 4. Fetch Price Target Consensus (New)
    _set_progress('progress_ticker_list', 95, "Fetching Price Targets...")
    logger.info("Starting Price Target Consensus Update...")
    
    with open(log_file, "a") as f:
        f.write(f"[{timezone.now()}] Starting Price Target Update for {updated_count} updated tickers.\n")
    
    # We iterate over the list we just confirmed exists
    pt_update_count = 0
    
    for i, sym in enumerate(sorted_ticker_list):
        # Rate Limit: 290 req/min => ~0.207s
        # Use 0.22s for safety
        time.sleep(0.22)
        
        # Progress for this phase
        if i % 50 == 0:
             # Scale progress from 95% to 99% (it's the last step) - actually better to just show activity
             msg = f"Price Target: {sym} ({i}/{total_tickers})"
             _set_progress('progress_ticker_list', 95, msg)
             print(f"[Price Target] {msg}")

        try:
            url_pt = f"https://financialmodelingprep.com/stable/price-target-consensus?symbol={sym}&apikey={api_key}"
            res = requests.get(url_pt, timeout=10)
            
            if res.status_code == 429:
                logger.warning(f"Rate Limit 429 on PT {sym}. Sleeping 60s...")
                time.sleep(61)
                try: res = requests.get(url_pt, timeout=10)
                except: pass

            if res.status_code == 200:
                data = res.json()
                # Example: { "symbol": "AAPL", "targetHigh": 300, "targetLow": 200, "targetConsensus": 251.7, "targetMedian": 258 }
                # Or sometimes a list? The endpoint implies single object if symbol is singular? 
                # Docs say: [ { ... } ] usually for FMP. Check response type.
                
                pt_data = None
                if isinstance(data, list) and len(data) > 0:
                    pt_data = data[0]
                elif isinstance(data, dict) and data.get('symbol'):
                    pt_data = data
                
                if pt_data:
                    Ticker.objects.filter(symbol=sym).update(
                        price_target_consensus=_safe_float(pt_data.get('targetConsensus')),
                        target_high=_safe_float(pt_data.get('targetHigh')),
                        target_low=_safe_float(pt_data.get('targetLow')),
                        target_median=_safe_float(pt_data.get('targetMedian'))
                    )
                    pt_update_count += 1
            else:
                 with open(log_file, "a") as f:
                    f.write(f"[{timezone.now()}] PT Error: {sym} Status {res.status_code}\n")

        except Exception as e:
            logger.error(f"PT Fetch Error {sym}: {e}")
            with open(log_file, "a") as f:
                    f.write(f"[{timezone.now()}] PT Exception: {sym} - {e}\n")


    # 5. Soft Truncate (Deactivate old instead of Delete)
    _set_progress('progress_ticker_list', 99, "Cleaning up...")
    
    print(f"\n[Ticker List] Updating active status for {len(final_symbols)} tickers...")
    
    # 1. Activate current list
    Ticker.objects.filter(symbol__in=final_symbols).update(is_actively_trading=True)
    
    # 2. Deactivate obsolete (Soft Delete)
    deactivated_count = Ticker.objects.exclude(symbol__in=final_symbols).update(is_actively_trading=False)
    
    logger.info(f"Cleanup: Deactivated {deactivated_count} tickers (is_actively_trading=False). Kept data.")
    print(f"[Ticker List] Cleanup: Deactivated {deactivated_count} tickers (kept data).")
    
    # 6. Finish
    _set_progress('progress_ticker_list', 100, f"Complete! Updated {updated_count}/{total_tickers} tickers.", is_finished=True)
    return {'total': updated_count, 'deactivated': deactivated_count}

def _parse_date(date_str):
    if not date_str: return None
    try:
        return dt.datetime.strptime(date_str, "%Y-%m-%d").date()
    except:
        return None

def _fill_missing_sectors(progress_callback=None, max_retries=3):
    """
    [Post-Process]
    Finds tickers with missing Industry/Sector and attempts to fill them using YFinance.
    Retries up to max_retries times for symbols that still have missing data.
    Args:
        progress_callback: function(percent: int) -> void
        max_retries: number of retry passes (default: 3)
    """
    from django.db.models import Q
    
    CHUNK_SIZE = 50
    CHUNK_DELAY = 2
    
    for retry_pass in range(max_retries):
        # 1. Identify targets (Industry or Sector is None or Empty)
        targets = list(Ticker.objects.filter(
            Q(industry__isnull=True) | Q(industry='') | 
            Q(sector__isnull=True) | Q(sector='')
        ))
        target_count = len(targets)
        
        if target_count == 0:
            logger.info(f"[YFinance Fill] Pass {retry_pass + 1}: No tickers missing sector/industry.")
            if progress_callback: progress_callback(100)
            return
        
        pass_label = f"Pass {retry_pass + 1}/{max_retries}"
        logger.info(f"[YFinance Fill] {pass_label}: Found {target_count} tickers with missing info...")
        print(f"\n[YFinance Fill] {pass_label}: {target_count} missing sector/industry")
        
        updated = 0
        num_chunks = (target_count + CHUNK_SIZE - 1) // CHUNK_SIZE
        
        for chunk_idx in range(num_chunks):
            start_idx = chunk_idx * CHUNK_SIZE
            end_idx = min(start_idx + CHUNK_SIZE, target_count)
            chunk = targets[start_idx:end_idx]
            
            for ticker in chunk:
                try:
                    sym_req = ticker.symbol
                    # Handle special symbols
                    if ticker.symbol in ['BF.B', 'BRK.B', 'BF.A', 'LEN.B']:
                        sym_req = ticker.symbol
                    else:
                        sym_req = ticker.symbol.replace('.', '-')
                    
                    yf_ticker = yf.Ticker(sym_req)
                    info = yf_ticker.info
                    
                    sec = info.get('sector')
                    ind = info.get('industry')
                    
                    changed = False
                    if sec and not ticker.sector:
                        ticker.sector = sec
                        changed = True
                    
                    if ind and not ticker.industry:
                        ticker.industry = ind
                        changed = True
                        
                    if changed:
                        ticker.save()
                        updated += 1
                        
                except Exception:
                    continue
            
            # Progress update
            processed = end_idx
            if progress_callback:
                pct = int((processed / target_count) * 100)
                progress_callback(pct)
            print(f"[YFinance Fill] {pass_label}: {processed}/{target_count} (✅{updated})", end='\r')
            
            # Delay between chunks
            if chunk_idx < num_chunks - 1:
                time.sleep(CHUNK_DELAY)
        
        print(f"\n[YFinance Fill] {pass_label} Complete: Updated {updated}/{target_count}")
        logger.info(f"[YFinance Fill] {pass_label} Complete: Updated {updated}/{target_count}")
        
        # If no updates were made in this pass, no point retrying
        if updated == 0:
            print(f"[YFinance Fill] No progress in {pass_label}, stopping retries.")
            break
        
        # Small delay before next retry pass
        if retry_pass < max_retries - 1:
            remaining = Ticker.objects.filter(
                Q(industry__isnull=True) | Q(industry='') | 
                Q(sector__isnull=True) | Q(sector='')
            ).count()
            if remaining > 0:
                print(f"[YFinance Fill] {remaining} still missing, retrying in 5s...")
                time.sleep(5)
            else:
                break
    
    # Final count
    final_missing = Ticker.objects.filter(
        Q(industry__isnull=True) | Q(industry='') | 
        Q(sector__isnull=True) | Q(sector='')
    ).count()
    print(f"[YFinance Fill] Done. {final_missing} still missing.")
    logger.info(f"[YFinance Fill] Done. {final_missing} still missing.")

# --- End Wrappers ---

logger = logging.getLogger('cron')

def _safe_float(val):
    try:
        if val is None: return 0.0
        return float(val)
    except:
        return 0.0




def run_manual_backfill_5y():
    """
    [Manual Trigger] Force Backfill 5 Years of History from FMP (Official Paid API).
    """
    logger.info("=== [Manual Backfill] Starting 5-Year Deep Backfill (FMP) ===")
    _backfill_history_fmp(period_days=365*5)

def _backfill_history_fmp(period_days=365*5):
    """
    Backfills Price History using FMP API.
    """
    tickers_qs = Ticker.objects.all()
    total = tickers_qs.count()
    
    logger.info(f"=== [Backfill FMP] Started for {total} tickers (days={period_days}) ===")
    _set_progress('progress_price_history', 0, "Initializing Backfill (FMP)...")
    
    updated_count = 0
    batch_size = 10
    
    for i, t_obj in enumerate(tickers_qs):
        try:
            hist_data = fetch_fmp_prices(t_obj.symbol, days=period_days)
            
            if not hist_data:
                logger.warning(f"No FMP data for {t_obj.symbol}")
                continue
                
            batch = []
            for row in hist_data:
                # FMP row: {'date': '2023-01-01', 'open': 100, ...}
                d_str = row.get('date')
                if not d_str: continue
                r_date = pd.to_datetime(d_str).date()
                
                # FMP gives 'adjClose'
                # Also gives 'change' and 'changePercent' usually
                
                ph = PriceHistory(
                    symbol=t_obj,
                    date=r_date,
                    open=float(row.get('open', 0)),
                    high=float(row.get('high', 0)),
                    low=float(row.get('low', 0)),
                    close=float(row.get('close', 0)),
                    volume=int(row.get('volume', 0)),
                    
                    adj_close=float(row.get('adjClose')) if row.get('adjClose') else None,
                    # FMP 'change' is change amount, 'changePercent' is % (e.g. 1.25)
                    change_amount=float(row.get('change')) if row.get('change') is not None else None,
                    change_percent=float(row.get('changePercent')) if row.get('changePercent') is not None else None,
                    
                    # FMP v3/historical-price-full doesn't always have div/split in same object
                    # We accept NULL for div/split for now
                    
                    updated_at=timezone.now()
                )
                batch.append(ph)
            
            if batch:
                PriceHistory.objects.bulk_create(batch, ignore_conflicts=True)
                # If ignore_conflicts=True, it skips existing.
                # If we want to UPSERT, we should use update_or_create loop or bulk_update.
                # For Backfill, bulk_create ignore_conflicts is fast and safe assuming we want to fill gaps.
                # But if we want to overwrite, we should delete first or use update_or_create.
                # User said "Backfill/History". Bulk Create is fine for initial fill. 
                # Be careful if data exists.
                # Let's use update_or_create loop for safety or simple bulk_create if empty.
                # Given user asked for "Switch to FMP", likely for daily updates too.
                # For speed in backfill, Bulk Create is best.
            
            updated_count += 1
            
        except Exception as e:
            logger.error(f"Error FMP Backfill {t_obj.symbol}: {e}")
            
        # Progress
        if (i + 1) % batch_size == 0 or (i + 1) == total:
             pct = int(((i+1) / total) * 100)
             msg = f"Backfilling (FMP) {i+1}/{total}"
             _set_progress('progress_price_history', pct, msg)
             print(f"[Backfill FMP] {msg} (✅{updated_count})", end='\r')

    print("")
    logger.info(f"=== [Backfill FMP] Completed. Updated {updated_count}/{total} tickers. ===")
    _set_progress('progress_price_history', 100, f"Completed. Backfilled {updated_count} tickers.", is_finished=True)

# Deprecate old YF function logic by overwriting it or just leaving it unused.
# I replaced 'run_manual_backfill_5y' content.


def _backfill_history_yfinance(period="5y"):
    """
    Backfills Price History using YFinance (Bulk/Fast).
    """
    import yfinance as yf
    from django.utils import timezone
    
    tickers_qs = Ticker.objects.all()
    total = tickers_qs.count()
    
    # This function is now replaced by _backfill_history_fmp above.
    pass
    
    updated_count = 0
    batch_size = 10
    
    for i, t_obj in enumerate(tickers_qs):
        try:
            # Handle symbols (BF.B, etc.)
            sym = t_obj.symbol
            if sym in ['BF.B', 'BRK.B', 'LEN.B']:
                pass # YF standard
            else:
                sym = sym.replace('.', '-')
                
            tik = yf.Ticker(sym)
            # Fetch history with auto_adjust=False to get 'Adj Close' separately
            # actions=True gives Dividends, Stock Splits
            hist = tik.history(period=period, auto_adjust=False, actions=True)
            
            if hist.empty:
                logger.warning(f"No YF data for {sym}")
                continue
                
            entries = []
            for ts, row in hist.iterrows():
                # Timestamp to Date
                d_date = ts.date()
                
                # Check for NaNs
                close_val = row.get('Close', 0)
                if pd.isna(close_val): continue
                
                adj_close_val = row.get('Adj Close', 0)
                if pd.isna(adj_close_val): adj_close_val = close_val # Fallback
                
                # Div/Split
                div = row.get('Dividends', 0.0)
                split = row.get('Stock Splits', 0.0)
                
                PriceHistory.objects.update_or_create(
                    symbol=t_obj,
                    date=d_date,
                    defaults={
                        'open': float(row['Open']) if not pd.isna(row['Open']) else 0,
                        'high': float(row['High']) if not pd.isna(row['High']) else 0,
                        'low': float(row['Low']) if not pd.isna(row['Low']) else 0,
                        'close': float(close_val),
                        'volume': int(row['Volume']) if not pd.isna(row['Volume']) else 0,
                        'adj_close': float(adj_close_val),
                        'div_cash': float(div) if div else 0.0,
                        'split_factor': float(split) if split else 1.0, # Default split 1.0 (no split) or 0.0? DB nullable. Let's send 1.0 if not 0? No, usually 0 or Null. 
                                                                        # FMP logic we discussed: default 1.0? 
                                                                        # Actually YF returns 0 if no split.
                                                                        # Let's use 0.0 based on Tiingo logic above (float default).
                        'updated_at': timezone.now()
                    }
                )
            updated_count += 1
            
        except Exception as e:
            logger.error(f"Error YF Backfill {t_obj.symbol}: {e}")
            
        # Progress
        if (i + 1) % batch_size == 0 or (i + 1) == total:
             pct = int(((i+1) / total) * 100)
             msg = f"Backfilling (YF) {i+1}/{total}"
             _set_progress('progress_price_history', pct, msg)
             print(f"[Backfill YF] {msg} (✅{updated_count})", end='\r')

    print("")
    logger.info(f"=== [Backfill YF] Completed. Updated {updated_count}/{total} tickers. ===")
    _set_progress('progress_price_history', 100, f"Completed. Backfilled {updated_count} tickers.", is_finished=True)

def verify_and_repair_data():
    """
    [Verification] Checks for tickers with low data count (< 1000 days for 5 years)
    and attempts to repair them with alternative symbol formats.
    """
    from django.db.models import Count
    import yfinance as yf
    
    logger.info("=== [Verification] Checking Data Integrity... ===")
    print("\n=== [Verification] Scanning for missing data... ===")
    
    # 1. Identify tickers with low data (assuming 5 years ~= 1250 days; trigger < 1000)
    low_data_tickers = Ticker.objects.annotate(cnt=Count('pricehistory')).filter(cnt__lt=1000)
    total_low = low_data_tickers.count()
    
    if total_low == 0:
        logger.info("Values look good! All tickers have sufficient data.")
        print("✅ Data Integrity Check Passed: All tickers have > 1000 records.")
        return
        
    print(f"⚠️ Found {total_low} tickers with insufficient data. Attempting Repair...")
    
    repaired_count = 0
    failed_list = []
    
    for t_obj in low_data_tickers:
        original_sym = t_obj.symbol
        # Try finding alternative strategies
        # Standard YF is usually dash: BRK-B
        # If DB has BRK.B, we might have skipped replacement.
        
        # Strategy: Try both formats
        formats = [
            original_sym.replace('.', '-'),  # BRK-B
            original_sym.replace('-', '.'),  # BRK.B
            original_sym                     # Raw
        ]
        formats = list(set(formats)) # Dedup
        
        success = False
        for fmt in formats:
            try:
                msg = f"Reparing {original_sym} using {fmt}..."
                print(msg, end='\r')
                
                tik = yf.Ticker(fmt)
                hist = tik.history(period="5y", auto_adjust=False, actions=True)
                
                if not hist.empty and len(hist) > 500: # If we got a decent chunk
                    # Save it
                    for ts, row in hist.iterrows():
                        d_date = ts.date()
                        close_val = row.get('Close', 0)
                        if pd.isna(close_val): continue
                        
                        # (Reuse save logic - simplifying for minimal code dupe, ideally shared func)
                        adj_close_val = row.get('Adj Close', 0)
                        if pd.isna(adj_close_val): adj_close_val = close_val
                        div = row.get('Dividends', 0.0)
                        split = row.get('Stock Splits', 0.0)
                        
                        PriceHistory.objects.update_or_create(
                            symbol=t_obj,
                            date=d_date,
                            defaults={
                                'open': float(row['Open']) if not pd.isna(row['Open']) else 0,
                                'high': float(row['High']) if not pd.isna(row['High']) else 0,
                                'low': float(row['Low']) if not pd.isna(row['Low']) else 0,
                                'close': float(close_val),
                                'volume': int(row['Volume']) if not pd.isna(row['Volume']) else 0,
                                'adj_close': float(adj_close_val),
                                'div_cash': float(div) if div else 0.0,
                                'split_factor': float(split) if split else 1.0,
                                'updated_at': timezone.now()
                            }
                        )
                    success = True
                    repaired_count += 1
                    break # Stop trying other formats if one worked
            except:
                continue
        
        if not success:
            failed_list.append(original_sym)
            
    print(f"\n[Verification] Repair Complete. Fixed {repaired_count}/{total_low} tickers.")
    if failed_list:
        print(f"❌ Failed to repair {len(failed_list)} tickers: {', '.join(failed_list[:20])}...")


def update_daily_close(symbols=None):
    """
    [CRON 16:05] Daily Close Update - FMP Quote API (Serial)
    Fetches latest price and Market Cap from FMP '/stable/quote' endpoint.
    Updates PriceHistory AND FundamentalData (marketCap).
    """
    import requests
    from django.conf import settings
    from django.utils import timezone
    import datetime as dt_module

    logger.info("=== [Daily Close] Starting Update (FMP Quote API - Serial) ===")
    _set_progress('progress_price_history', 0, "Initializing Quote Update...")

    # 1. Get Tickers
    if symbols:
        if isinstance(symbols, list):
            tickers_qs = Ticker.objects.filter(symbol__in=symbols)
        else:
            tickers_qs = Ticker.objects.filter(symbol=symbols)
    else:
        tickers_qs = Ticker.objects.all()

    # Init Log - Truncate Log File at Start of Task
    log_file = "logs/price_history.log"
    with open(log_file, "w") as f:
        f.write(f"[{dt_module.datetime.now()}] Starting Daily Price Update (FMP Quote). Target: {tickers_qs.count() if hasattr(tickers_qs, 'count') else 'Unknown'}\n")

    # Check API Key
    API_KEY = settings.FMP_API_KEY
    if not API_KEY:
        logger.error("FMP_API_KEY missing.")
        with open(log_file, "a") as f: f.write(f"[{dt_module.datetime.now()}] Error: FMP_API_KEY missing.\n")
        return

    total = tickers_qs.count()
    updated_count = 0
    updated_fund_count = 0
    failed_tickers = []

    logger.info(f"[Daily Close] Target: {total} tickers for daily price update.")
    print(f"[Daily Close] Target: {total} tickers.")

    print(f"[Daily Close] Target: {total} tickers.")

    # 2. Iterate Serially (User Request: Strict 295 req/min limit)
    req_count = 0
    window_start = time.time()
    MAX_REQ_PER_MIN = 295

    # Detailed Failure Tracking
    failed_tickers = []   # General failures (No Data, 404, 500, etc)
    retry_tickers = []    # Tickers that hit 429 (Rate Limit) -> Retry Later

    for i, t_obj in enumerate(tickers_qs):
        # ... (Rate Limit Check) ...
        # 1. Check Window Expiry
        if time.time() - window_start >= 60:
            req_count = 0
            window_start = time.time()
            
        # 2. Check Limit Saturation
        if req_count >= MAX_REQ_PER_MIN:
            elapsed = time.time() - window_start
            sleep_needed = 60 - elapsed + 1
            if sleep_needed > 0:
                print(f"⏳ Limit ({MAX_REQ_PER_MIN}) Hit. Sleeping {sleep_needed:.1f}s...")
                time.sleep(sleep_needed)
            
            req_count = 0
            window_start = time.time()

        sym = t_obj.symbol
        req_sym = sym.replace('.', '-') 
        url = f"https://financialmodelingprep.com/stable/quote?symbol={req_sym}&apikey={API_KEY}"
        
        try:
            req_count += 1
            r = requests.get(url, timeout=10)
            
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list) and len(data) > 0:
                    row = data[0]
                    # ... (Processing Logic - Same as before) ...\n                    # 1. Price History Update
                    # CRITICAL: Use correct trading day (not future dates!)
                    est = pytz.timezone('US/Eastern')
                    now_est = timezone.now().astimezone(est)
                    
                    # Market hours: 9:30 AM - 4:00 PM ET
                    # If current time is before 4:00 PM ET today, use previous trading day
                    # If after 4:00 PM ET, use today
                    is_weekend = now_est.weekday() >= 5  # Saturday=5, Sunday=6
                    is_before_close = now_est.hour < 16  # Before 4:00 PM
                    
                    if is_weekend or is_before_close:
                        # Use previous trading day
                        r_date = now_est.date()
                        days_back = 1
                        if is_weekend:
                            # Go back to Friday
                            days_back = now_est.weekday() - 4  # Mon=0, Fri=4
                            if days_back <= 0:
                                days_back = now_est.weekday() + 2  # Sat=1 day, Sun=2 days
                        r_date = r_date - dt_module.timedelta(days=days_back)
                    else:
                        # After market close, use today
                        r_date = now_est.date()

                    # Volume % Calculation
                    vol_percent = 0.0
                    curr_vol = int(row.get('volume') or 0)
                    try:
                        prev_ph = PriceHistory.objects.filter(symbol=t_obj, date__lt=r_date).order_by('-date').first()
                        if prev_ph and prev_ph.volume and curr_vol:
                            vol_percent = ((curr_vol - prev_ph.volume) / prev_ph.volume) * 100
                    except: pass

                    # Save Price
                    PriceHistory.objects.update_or_create(
                        symbol=t_obj,
                        date=r_date,
                        defaults={
                            'open': float(row.get('open') or 0),
                            'high': float(row.get('dayHigh') or 0),
                            'low': float(row.get('dayLow') or 0),
                            'close': float(row.get('price') or 0),
                            'volume': curr_vol,
                            'change_amount': float(row.get('change') or 0),
                            'change_percent': float(row.get('changePercentage') or 0),
                            'volume_percent': vol_percent,
                            'updated_at': timezone.now()
                        }
                    )
                    updated_count += 1
                    
                    # 2. FundamentalData Update (Market Cap)
                    m_cap = row.get('marketCap')
                    if m_cap:
                        FundamentalData.objects.update_or_create(
                            symbol=t_obj,
                            date=r_date,  # Use same trading day as PriceHistory
                            defaults={
                                'market_cap': float(m_cap),
                                'updated_at': timezone.now()
                            }
                        )
                        updated_fund_count += 1
                else:
                    # No data returned (Empty List) -> Just Warn, No Retry
                    with open(log_file, "a") as f:
                        f.write(f"[{dt_module.datetime.now()}] Warn: {sym} returned empty list.\n")
            
            elif r.status_code == 429:
                 print(f"⚠️ Rate Limit Hit (429) on {sym}. Adding to Retry List...")
                 time.sleep(60) # Backoff immediately
                 req_count = 0 # Reset counter after long sleep
                 window_start = time.time()
                 
                 retry_tickers.append(t_obj) # Queue for later retry
                 
                 with open(log_file, "a") as f:
                        f.write(f"[{dt_module.datetime.now()}] Warn: {sym} HTTP 429 (Queued for Retry)\n")
            else:
                 failed_tickers.append(f"{sym} (HTTP {r.status_code})")
                 with open(log_file, "a") as f:
                        f.write(f"[{dt_module.datetime.now()}] Error: {sym} HTTP {r.status_code}\n")
                
        except Exception as e:
            failed_tickers.append(f"{sym} (Ex: {str(e)})")
            with open(log_file, "a") as f:
                f.write(f"[{dt_module.datetime.now()}] Error: {sym} Exception: {e}\n")

        # Progress Log (Every 50)
        if (i + 1) % 50 == 0 or (i + 1) == total:
             # ... (Progress Logic) ...
             pct = int(((i+1) / total) * 100)
             msg = f"Updating Prices... {i+1}/{total}"
             _set_progress('progress_price_history', pct, msg)
             print(f"[FMP Serial] {i+1}/{total} (Price:{updated_count})", end='\r')
             try:
                 with open(log_file, "a") as f:
                     f.write(f"[{dt_module.datetime.now()}] Progress: {i+1}/{total} - Updated {updated_count}.\n")
             except: pass


    # --- RETRY LOOP for 429s ---
    if retry_tickers:
        print(f"\n🔄 Retrying {len(retry_tickers)} tickers that failed with 429...")
        with open(log_file, "a") as f:
            f.write(f"[{dt_module.datetime.now()}] Starting Retry for {len(retry_tickers)} tickers.\n")
        
        # Reset Limit Trackers
        req_count = 0
        window_start = time.time()
        
        for i, t_obj in enumerate(retry_tickers):
             # Rate Limit Check (Same Logic)
            if time.time() - window_start >= 60:
                req_count = 0
                window_start = time.time()
            if req_count >= MAX_REQ_PER_MIN:
                time.sleep(60 - (time.time() - window_start) + 1)
                req_count = 0
                window_start = time.time()

            sym = t_obj.symbol
            req_sym = sym.replace('.', '-')
            url = f"https://financialmodelingprep.com/stable/quote?symbol={req_sym}&apikey={API_KEY}"
            
            try:
                req_count += 1
                r = requests.get(url, timeout=10)
                if r.status_code == 200:
                    data = r.json()
                    if isinstance(data, list) and len(data) > 0:
                        row = data[0]
                        
                        # Process Data (Duplicated Logic - Functionize ideally but inline for safety here)
                        est = pytz.timezone('US/Eastern')
                        r_date = timezone.now().astimezone(est).date()
                        vol_percent = 0.0
                        curr_vol = int(row.get('volume') or 0)
                        try:
                            prev_ph = PriceHistory.objects.filter(symbol=t_obj, date__lt=r_date).order_by('-date').first()
                            if prev_ph and prev_ph.volume and curr_vol:
                                vol_percent = ((curr_vol - prev_ph.volume) / prev_ph.volume) * 100
                        except: pass

                        PriceHistory.objects.update_or_create(
                            symbol=t_obj,
                            date=r_date,
                            defaults={
                                'open': float(row.get('open') or 0),
                                'high': float(row.get('dayHigh') or 0),
                                'low': float(row.get('dayLow') or 0),
                                'close': float(row.get('price') or 0),
                                'volume': curr_vol,
                                'change_amount': float(row.get('change') or 0),
                                'change_percent': float(row.get('changePercentage') or 0),
                                'volume_percent': vol_percent,
                                'updated_at': timezone.now()
                            }
                        )
                        updated_count += 1
                        
                        m_cap = row.get('marketCap')
                        if m_cap:
                            FundamentalData.objects.update_or_create(
                                symbol=t_obj,
                                date=dt_module.date.today(),
                                defaults={'market_cap': float(m_cap), 'updated_at': timezone.now()}
                            )
                            updated_fund_count += 1
                        
                        print(f"   ✅ Retry Success: {sym}")
                        with open(log_file, "a") as f:
                             f.write(f"[{dt_module.datetime.now()}] Retry Success: {sym}\n")
                    else:
                        print(f"   ❌ Retry Failed (No Data): {sym}")
                        failed_tickers.append(f"{sym} (Retry: No Data)")
                else:
                    print(f"   ❌ Retry Failed (HTTP {r.status_code}): {sym}")
                    failed_tickers.append(f"{sym} (Retry: {r.status_code})")
                    
            except Exception as e:
                print(f"   ❌ Retry Failed (Ex): {sym}")
                failed_tickers.append(f"{sym} (Retry Ex: {e})")

    print("")

    # Completion Signal
    final_msg = f"Daily Close Update Complete. Updated {updated_count} prices, {updated_fund_count} market caps."
    logger.info(final_msg)
    with open(log_file, "a") as f:
         f.write(f"[{dt_module.datetime.now()}] {final_msg}\n")
    
    _set_progress('progress_price_history', 100, final_msg, is_finished=True)


def _update_fundamentals(symbols):
    """
    Updates FundamentalData using FMP 'key-metrics-ttm' endpoint and local calculations.
    Endpoint: https://financialmodelingprep.com/stable/key-metrics-ttm?symbol={}&apikey={}
    Calculations:
      - PE = 1 / Earnings Yield
      - EPS = Price * Earnings Yield
      - PBR = PE * ROE
    """
    import requests
    import time
    import datetime as dt
    from django.conf import settings
    
    logger.info("[Fundamentals] Updating via FMP Key Metrics TTM...")
    _set_progress('progress_fundamentals', 0, "Initializing FMP Update...")
    
    # Init Log
    log_file = "logs/fundamental.log"
    with open(log_file, "w") as f:
        f.write(f"[{dt.datetime.now()}] Starting Fundamentals Update.\n")
    
    api_key = settings.FMP_API_KEY
    if not api_key:
        logger.error("[Fundamentals] FMP_API_KEY not found.")
        with open(log_file, "a") as f: f.write(f"[{dt.datetime.now()}] Error: FMP_API_KEY missing.\n")
        return

    # User Request: Truncate table at start (Fresh Snapshot)
    print("🗑️ Truncating FundamentalData table...")
    FundamentalData.objects.all().delete()

    # 1. Prepare Data
    if symbols and isinstance(symbols[0], str):
        target_symbols = symbols
        tickers_qs = Ticker.objects.filter(symbol__in=target_symbols)
        tickers_map = {t.symbol: t for t in tickers_qs}
    else:
        target_symbols = [s.symbol for s in symbols]
        tickers_map = {t.symbol: t for t in symbols}

    # 2. BLACKLIST (Manually Excluded)
    # User requested to remove these specific tickers (2025-12-10)
    BLACKLIST = {'SCS', 'ODP', 'PRO', 'AKRO', 'HSII'}
    
    # Filter target_symbols based on BLACKLIST
    target_symbols = [sym for sym in target_symbols if sym not in BLACKLIST]
    # Rebuild tickers_map if necessary after filtering
    tickers_qs = Ticker.objects.filter(symbol__in=target_symbols)
    tickers_map = {t.symbol: t for t in tickers_qs}

    total = len(target_symbols)
    updated_count = 0
    failed_count = 0
    
    _set_progress('progress_fundamentals', 5, f"Starting update for {total} tickers...")

    def _safe_float(val):
        if val is None: return None
        try:
            return float(val)
        except:
            return None

    # ... (existing setup) ...

    # (Batch Logic Removed as per user request for strict serial processing)

    # Processing Loop
    req_count = 0
    window_start = time.time()
    MAX_REQ_PER_MIN = 295 
    
    # Detailed Failure Tracking
    failed_no_data = [] # Tickers with HTTP 200 but empty data
    failed_error = []   # Tickers with HTTP 4xx/5xx or Exceptions
    
    for i, sym in enumerate(target_symbols):
        # 1. Check Window Expiry
        if time.time() - window_start >= 60:
            req_count = 0
            window_start = time.time()
            
        # 2. Check Limit Saturation
        if req_count >= MAX_REQ_PER_MIN:
            elapsed = time.time() - window_start
            sleep_needed = 60 - elapsed + 1 
            if sleep_needed > 0:
                print(f"⏳ Limit ({MAX_REQ_PER_MIN}) Hit. Sleeping {sleep_needed:.1f}s...")
                time.sleep(sleep_needed)
            
            req_count = 0
            window_start = time.time()
            
        ticker = tickers_map.get(sym)
        if not ticker: continue
        
        try:
            # A. Fetch Quote (For USD Market Cap)
            q_url = f"https://financialmodelingprep.com/stable/quote?symbol={sym.replace('.', '-')}&apikey={api_key}"
            q_data = None
            try:
                # Check Lock before request
                if req_count >= MAX_REQ_PER_MIN:
                     # ... same sleep logic if needed, but simplistic check at top handles most cases.
                     # But since we do 2 requests, we should check again or just be okay with +1 overflow?
                     # Let's check again to be strict.
                     if time.time() - window_start >= 60:
                        req_count = 0
                        window_start = time.time()
                     elif req_count >= MAX_REQ_PER_MIN:
                        time.sleep(60 - (time.time() - window_start) + 1)
                        req_count = 0
                        window_start = time.time()

                req_count += 1
                r_q = requests.get(q_url, timeout=10)
                if r_q.status_code == 200:
                    q_json = r_q.json()
                    if q_json and isinstance(q_json, list):
                        q_data = q_json[0]
            except: pass

            usd_market_cap = None
            if q_data:
                usd_market_cap = _safe_float(q_data.get('marketCap'))

            # B. Fetch Key Metrics (For Ratios)
            url = f"https://financialmodelingprep.com/stable/key-metrics-ttm?symbol={sym}&apikey={api_key}"
            
            try:
                # Check Lock again
                if time.time() - window_start >= 60:
                    req_count = 0
                    window_start = time.time()
                elif req_count >= MAX_REQ_PER_MIN:
                    time.sleep(60 - (time.time() - window_start) + 1)
                    req_count = 0
                    window_start = time.time()

                req_count += 1
                res = requests.get(url, timeout=10)
            except requests.exceptions.RequestException as e:
                failed_error.append(f"{sym} (NetErr: {e})")
                continue

            if res.status_code == 429:
                print(f"⚠️ Rate Limit Hit (429) on {sym}. Sleeping 60s...")
                time.sleep(60)
                req_count = 0
                window_start = time.time()
                try:
                    res = requests.get(url, timeout=10)
                except: pass
            
            data = None
            if res.status_code == 200:
                json_data = res.json()
                if json_data and isinstance(json_data, list):
                    data = json_data[0]
                else:
                    # HTTP 200 but empty list -> No Data available
                    failed_no_data.append(sym)
                    
            else:
                failed_error.append(f"{sym} (HTTP {res.status_code})")
            
            if not data:
                continue

            # 2. Get Recent Price
            try:
                latest_ph = ticker.price_history.latest('date')
                price = latest_ph.close
            except PriceHistory.DoesNotExist:
                price = None

            # 3. Extract FMP Data
            # PRIORITY: USD Market Cap from Quote
            market_cap = usd_market_cap
            if not market_cap:
                # Fallback to key-metrics
                market_cap = _safe_float(data.get('marketCap')) or _safe_float(data.get('marketCapTTM'))

            enterprise_value_ttm = _safe_float(data.get('enterpriseValueTTM'))
            ev_to_sales_ttm = _safe_float(data.get('evToSalesTTM'))
            ev_to_operating_cash_flow_ttm = _safe_float(data.get('evToOperatingCashFlowTTM'))
            ev_to_free_cash_flow_ttm = _safe_float(data.get('evToFreeCashFlowTTM'))
            ev_to_ebitda_ttm = _safe_float(data.get('evToEBITDATTM'))
            net_debt_to_ebitda_ttm = _safe_float(data.get('netDebtToEBITDATTM'))
            current_ratio_ttm = _safe_float(data.get('currentRatioTTM'))
            
            income_quality_ttm = _safe_float(data.get('incomeQualityTTM'))
            graham_number_ttm = _safe_float(data.get('grahamNumberTTM'))
            graham_net_net_ttm = _safe_float(data.get('grahamNetNetTTM'))
            tax_burden_ttm = _safe_float(data.get('taxBurdenTTM'))
            interest_burden_ttm = _safe_float(data.get('interestBurdenTTM'))
            working_capital_ttm = _safe_float(data.get('workingCapitalTTM'))
            invested_capital_ttm = _safe_float(data.get('investedCapitalTTM'))
            
            return_on_assets_ttm = _safe_float(data.get('returnOnAssetsTTM'))
            operating_return_on_assets_ttm = _safe_float(data.get('operatingReturnOnAssetsTTM'))
            return_on_tangible_assets_ttm = _safe_float(data.get('returnOnTangibleAssetsTTM'))
            return_on_equity_ttm = _safe_float(data.get('returnOnEquityTTM'))
            return_on_invested_capital_ttm = _safe_float(data.get('returnOnInvestedCapitalTTM'))
            return_on_capital_employed_ttm = _safe_float(data.get('returnOnCapitalEmployedTTM'))
            
            earnings_yield_ttm = _safe_float(data.get('earningsYieldTTM'))
            free_cash_flow_yield_ttm = _safe_float(data.get('freeCashFlowYieldTTM'))
            
            capex_to_operating_cash_flow_ttm = _safe_float(data.get('capexToOperatingCashFlowTTM'))
            capex_to_depreciation_ttm = _safe_float(data.get('capexToDepreciationTTM'))
            capex_to_revenue_ttm = _safe_float(data.get('capexToRevenueTTM'))
            sales_general_and_administrative_to_revenue_ttm = _safe_float(data.get('salesGeneralAndAdministrativeToRevenueTTM'))
            research_and_developement_to_revenue_ttm = _safe_float(data.get('researchAndDevelopementToRevenueTTM'))
            stock_based_compensation_to_revenue_ttm = _safe_float(data.get('stockBasedCompensationToRevenueTTM'))
            intangibles_to_total_assets_ttm = _safe_float(data.get('intangiblesToTotalAssetsTTM'))
            
            average_receivables_ttm = _safe_float(data.get('averageReceivablesTTM'))
            average_payables_ttm = _safe_float(data.get('averagePayablesTTM'))
            average_inventory_ttm = _safe_float(data.get('averageInventoryTTM'))
            days_of_sales_outstanding_ttm = _safe_float(data.get('daysOfSalesOutstandingTTM'))
            days_of_payables_outstanding_ttm = _safe_float(data.get('daysOfPayablesOutstandingTTM'))
            days_of_inventory_outstanding_ttm = _safe_float(data.get('daysOfInventoryOutstandingTTM'))
            operating_cycle_ttm = _safe_float(data.get('operatingCycleTTM'))
            cash_conversion_cycle_ttm = _safe_float(data.get('cashConversionCycleTTM'))
            free_cash_flow_to_equity_ttm = _safe_float(data.get('freeCashFlowToEquityTTM'))
            free_cash_flow_to_firm_ttm = _safe_float(data.get('freeCashFlowToFirmTTM'))
            tangible_asset_value_ttm = _safe_float(data.get('tangibleAssetValueTTM'))
            net_current_asset_value_ttm = _safe_float(data.get('netCurrentAssetValueTTM'))

            # -- Calculated Metrics (Preserved) --
            pe_ratio = None
            eps_ttm = None
            pb_ratio = None
            
            # PE Ratio = 1 / earningsYieldTTM
            if earnings_yield_ttm and earnings_yield_ttm != 0:
                pe_ratio = 1 / earnings_yield_ttm
            
            # EPS TTM - Fetch from Income Statement (Legacy key-metrics-ttm is deprecated)
            # The stable key-metrics-ttm doesn't have netIncomePerShareTTM
            # Use /stable/income-statement instead
            try:
                inc_url = f"https://financialmodelingprep.com/stable/income-statement?symbol={sym}&period=annual&limit=1&apikey={api_key}"
                inc_res = requests.get(inc_url, timeout=10)
                if inc_res.status_code == 200:
                    inc_data = inc_res.json()
                    if inc_data and isinstance(inc_data, list) and len(inc_data) > 0:
                        # Use epsDiluted (more accurate) or fallback to eps
                        eps_ttm = _safe_float(inc_data[0].get('epsDiluted')) or _safe_float(inc_data[0].get('eps'))
            except Exception as e:
                logger.error(f"Failed to fetch EPS for {sym}: {e}")
            
            # PBR = PE * ROE
            if pe_ratio and return_on_equity_ttm:
                pb_ratio = pe_ratio * return_on_equity_ttm
                
            # If PE is None, PB is hard to calc this way.
            # Fallback: Price / BVPS
            bvps = _safe_float(data.get('bookValuePerShareTTM'))
            if not pb_ratio and bvps and price:
                 pb_ratio = price / bvps

            # 4. Save (Snapshot Mode: Keep Only Latest)
            fd, created = FundamentalData.objects.update_or_create(
                symbol=ticker,
                date=dt.date.today(),
                defaults={
                    'market_cap': market_cap,
                    'enterprise_value_ttm': enterprise_value_ttm,
                    'ev_to_sales_ttm': ev_to_sales_ttm,
                    'ev_to_operating_cash_flow_ttm': ev_to_operating_cash_flow_ttm,
                    'ev_to_free_cash_flow_ttm': ev_to_free_cash_flow_ttm,
                    'ev_to_ebitda_ttm': ev_to_ebitda_ttm,
                    'net_debt_to_ebitda_ttm': net_debt_to_ebitda_ttm,
                    'current_ratio_ttm': current_ratio_ttm,
                    'income_quality_ttm': income_quality_ttm,
                    'graham_number_ttm': graham_number_ttm,
                    'graham_net_net_ttm': graham_net_net_ttm,
                    'tax_burden_ttm': tax_burden_ttm,
                    'interest_burden_ttm': interest_burden_ttm,
                    'working_capital_ttm': working_capital_ttm,
                    'invested_capital_ttm': invested_capital_ttm,
                    'return_on_assets_ttm': return_on_assets_ttm,
                    'operating_return_on_assets_ttm': operating_return_on_assets_ttm,
                    'return_on_tangible_assets_ttm': return_on_tangible_assets_ttm,
                    'return_on_equity_ttm': return_on_equity_ttm,
                    'return_on_invested_capital_ttm': return_on_invested_capital_ttm,
                    'return_on_capital_employed_ttm': return_on_capital_employed_ttm,
                    'earnings_yield_ttm': earnings_yield_ttm,
                    'free_cash_flow_yield_ttm': free_cash_flow_yield_ttm,
                    'capex_to_operating_cash_flow_ttm': capex_to_operating_cash_flow_ttm,
                    'capex_to_depreciation_ttm': capex_to_depreciation_ttm,
                    'capex_to_revenue_ttm': capex_to_revenue_ttm,
                    'sales_general_and_administrative_to_revenue_ttm': sales_general_and_administrative_to_revenue_ttm,
                    'research_and_developement_to_revenue_ttm': research_and_developement_to_revenue_ttm,
                    'stock_based_compensation_to_revenue_ttm': stock_based_compensation_to_revenue_ttm,
                    'intangibles_to_total_assets_ttm': intangibles_to_total_assets_ttm,
                    'average_receivables_ttm': average_receivables_ttm,
                    'average_payables_ttm': average_payables_ttm,
                    'average_inventory_ttm': average_inventory_ttm,
                    'days_of_sales_outstanding_ttm': days_of_sales_outstanding_ttm,
                    'days_of_payables_outstanding_ttm': days_of_payables_outstanding_ttm,
                    'days_of_inventory_outstanding_ttm': days_of_inventory_outstanding_ttm,
                    'operating_cycle_ttm': operating_cycle_ttm,
                    'cash_conversion_cycle_ttm': cash_conversion_cycle_ttm,
                    'free_cash_flow_to_equity_ttm': free_cash_flow_to_equity_ttm,
                    'free_cash_flow_to_firm_ttm': free_cash_flow_to_firm_ttm,
                    'tangible_asset_value_ttm': tangible_asset_value_ttm,
                    'net_current_asset_value_ttm': net_current_asset_value_ttm,
                    
                    'pe_ratio': pe_ratio,
                    'pb_ratio': pb_ratio,
                    'eps_ttm': eps_ttm,
                    'book_value_per_share': bvps,

                    'updated_at': dt.datetime.now()
                }
            )
            
            # Cleanup: Historical data already truncated at start.
            # FundamentalData.objects.filter(symbol=ticker).exclude(pk=fd.pk).delete()
            
            updated_count += 1
            
            # Progress Log
            if i % 5 == 0 or (i + 1) == total:
                print(f"[FMP Update] {i}/{total} ({sym}) ✅{updated_count} ❌{len(failed_error)}", end='\r')
                
                # Formula: Start at 5%, scale up to 100%
                # pct = 5 + ((i / total) * 95)
                pct = 5 + int((i / total) * 95)
                
                _set_progress('progress_fundamentals', pct, f"Updating {i}/{total}...")
                
                # Detailed File Logging for Progress
                try:
                    with open("logs/fundamental.log", "a") as f:
                        f.write(f"[{dt.datetime.now()}] Progress: {i}/{total} ({sym}) - Success: {updated_count}, No Data: {len(failed_no_data)}, Error: {len(failed_error)}\n")
                except: pass
                
        except Exception as e:
            failed_error.append(f"{sym} (Ex: {e})")
            print(f"Error updating {sym}: {e}")
            logger.error(f"Error updating {sym}: {e}")

    final_msg = f"FMP Update Complete. Success: {updated_count}, No Data: {len(failed_no_data)}, Error: {len(failed_error)}"
    logger.info(final_msg)
    _set_progress('progress_fundamentals', 100, final_msg, is_finished=True)
    
    with open("logs/fundamental.log", "a") as f:
        f.write(f"[{dt.datetime.now()}] {final_msg}\n")
        f.write("=== Failures (No Data) ===\n")
        f.write(", ".join(failed_no_data) + "\n")
        f.write("=== Failures (Errors) ===\n")
        f.write(", ".join(failed_error) + "\n")
        
    print(f"\n{final_msg}")

def run_backfill_missing_data():
    """
    Backfill Task for 'Repair Data' button.
    Finds tickers with < 1000 price records and fills them using FMP.
    Progress Key: 'progress_backfill'
    """
    import os
    import time
    import requests
    import pandas as pd
    from django.conf import settings
    from django.db.models import Count
    from datetime import timedelta
    
    # 1. Init
    cache_key = 'progress_backfill'
    _set_progress(cache_key, 0, "Initializing Backfill...")
    
    api_key = os.environ.get("FMP_API_KEY", "")
    if not api_key:
        _set_progress(cache_key, 0, "Error: FMP API Key missing.", is_finished=True)
        return

    # 2. Identify Targets
    _set_progress(cache_key, 2, "Scanning for missing data...")
    threshold = 1000
    # Optimizing scan
    targets = Ticker.objects.annotate(cnt=Count('price_history')).filter(cnt__lt=threshold).order_by('cnt')
    target_list = list(targets)
    total = len(target_list)
    
    logger.info(f"[Backfill] Found {total} tickers to repair.")
    
    if total == 0:
        _set_progress(cache_key, 100, "No repair needed. All tickers have sufficient data.", is_finished=True)
        return

    # 3. Execution Loop
    updated_count = 0
    
    for i, ticker in enumerate(target_list):
        # Progress Calculation
        pct = int(((i) / total) * 100) # 0 to 99
        msg = f"Repairing {ticker.symbol} ({i+1}/{total})..."
        _set_progress(cache_key, pct, msg)
        
        try:
            # FMP Logic
            symbol = ticker.symbol
            req_sym = symbol.replace('.', '-')
            
            # Fetch 5 years
            from_date = (timezone.now().date() - timedelta(days=1825)).strftime('%Y-%m-%d')
            url = f"https://financialmodelingprep.com/stable/historical-price-eod/full?symbol={req_sym}&from={from_date}&apikey={api_key}"
            
            # Rate Limit (Safe 0.22s)
            time.sleep(0.22)
            
            resp = requests.get(url, timeout=10)
            
            if resp.status_code == 429:
                _set_progress(cache_key, pct, f"Rate Limit (429). Sleeping 60s...")
                time.sleep(61)
                resp = requests.get(url, timeout=10)
            
            if resp.status_code == 200:
                data = resp.json()
                
                # FMP list response
                if isinstance(data, list):
                    hist_list = data
                elif isinstance(data, dict) and 'historical' in data:
                    hist_list = data['historical']
                else:
                    hist_list = []

                if hist_list:
                     # Sort by date asc
                     hist_list.sort(key=lambda x: x.get('date'))
                     
                     for row in hist_list:
                         d_str = row.get('date')
                         if not d_str: continue
                         r_date = pd.to_datetime(d_str).date()
                         
                         PriceHistory.objects.update_or_create(
                             symbol=ticker,
                             date=r_date,
                             defaults={
                                 'open': row.get('open'),
                                 'high': row.get('high'),
                                 'low': row.get('low'),
                                 'close': row.get('close'),
                                 'volume': row.get('volume'),
                                 'adj_close': row.get('adjClose'), # Might be None
                                 'updated_at': timezone.now()
                             }
                         )
                     updated_count += 1
            
        except Exception as e:
            logger.error(f"[Backfill] Error {ticker.symbol}: {e}")
            pass
            
    # Finalize
    _set_progress(cache_key, 100, f"Repair Complete! Updated {updated_count}/{total} tickers.", is_finished=True)
