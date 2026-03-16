# updatedata/views.py
import datetime
import pandas as pd
import yfinance as yf
from django.contrib import messages
from django.db import transaction
from django.shortcuts import render, redirect

# ★ 1. Ticker 모델을 임포트합니다.
from .models import Ticker 
from scanner.models import DailyPrice

# Import ALL relevant tasks
from .tasks import (
    run_update_ticker_list, 
    run_update_fundamentals, 
    update_todays_close, 
    run_backfill_missing_data,
    update_daily_close
)
from .services import download_latest_iwm_csv, download_latest_scha_csv

def index(request):
    qs = Ticker.objects.all()

    count = qs.count()   # = 현재 universe 전체

    by_market = {
        "sp500": qs.filter(market__icontains="sp500").count(),
        "nasdaq100": qs.filter(market__icontains="nasdaq100").count(),
        "russell1000": qs.filter(market__icontains="russell1000").count(),
    }

    latest = qs.order_by("-created_at")[:50]

    context = {
        "count": count,
        "by_market": by_market,
        "latest": latest,
    }
    return render(request, "updatedata/index.html", context)


def update_universe(request):
    """
    Universe 업데이트 버튼.
    (실제 로직은 tasks.run_update_universe()에 있음)
    """
    if request.method not in ("GET", "POST"):
        return redirect("updatedata:index")

    try:
        # [수정] 사용자가 버튼을 눌렀을 때는 강제로 펀더멘탈(시가총액 등)을 최신화합니다.
        stats = run_update_ticker_list(force_update=True)

        # ★ 3. stats 딕셔너리가 정상인지 확인
        if not isinstance(stats, dict) or 'total' not in stats:
             raise Exception("The task function did not return valid statistics.")

        messages.success(
            request,
            (
                "Universe updated: "
                # ★ tasks.py에서 반환하는 키(nasdaq100, russell1000)와 맞춤
                f"total={stats.get('total', 0)} · "
                f"SP={stats.get('sp500', 0)} · "
                f"NAS={stats.get('nasdaq100', 0)} · " 
                f"RUS={stats.get('russell1000', 0)} "
                f"(Failed: {stats.get('failed', 0)})"
            ),
        )
    except Exception as e:
        messages.error(request, f"Update failed: {e}")

    return redirect("updatedata:index") # ★ 앱 이름 'updatedata'로 변경

def refresh_iwm(request):
    """
    Refresh Russell 2000 (IWM) Excel 버튼:
      - IWM holdings XLS만 다운로드해서 로컬 파일로 저장
      - DB는 건드리지 않음
      - [Async] Threaded with Progress
    """
    if request.method != "POST":
        return redirect("admin:index")

    from .tasks import _set_progress
    import threading

    def _run_task():
        cache_key = 'progress_iwb' # Using IWB as key (mapped in check_task_progress)
        _set_progress(cache_key, 0, "Starting IWM Download...")
        
        def _cb(pct, msg):
            _set_progress(cache_key, pct, msg)
            
        ok, msg = download_latest_iwm_csv(progress_callback=_cb)
        
        final_msg = f"[IWM CSV] {msg}" if ok else f"Failed: {msg}"
        _set_progress(cache_key, 100, final_msg, is_finished=True)

    t = threading.Thread(target=_run_task)
    t.daemon = True
    t.start()

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        from django.http import JsonResponse
        return JsonResponse({
            "status": "success", 
            "message": "Downloading IWM CSV in background..."
        })

    messages.success(request, "[IWM] Download started in background.")
    return redirect("admin:index")

def refresh_scha(request):
    """
    Redirects user to Schwab's SCHA CSV download link.
    User manual workflow: Download -> Save as updatedata/data/scha.csv -> Update Universe
    """
    import datetime
    from django.http import HttpResponseRedirect
    
    if request.method != "POST":
        return redirect("admin:index")

    # Dynamic date: Yesterday (User request: Today's data might be missing, so use T-1)
    yesterday_str = (datetime.date.today() - datetime.timedelta(days=1)).strftime('%Y-%m-%d')
    url = f"https://www.schwabassetmanagement.com/sites/g/files/eyrktu361/files/product_files/SCHA/SCHA_FundHoldings_{yesterday_str}.CSV"
    
    # Simple Redirect
    return HttpResponseRedirect(url)

def check_task_progress(request):
    """
    API to poll progress.
    GET /updatedata/progress/?task_name=ticker_list
    Returns: {'status': 'running'|'finished'|'error', 'progress': int, 'message': str}
    """
    task_name = request.GET.get('task_name')
    if not task_name:
        from django.http import JsonResponse
        return JsonResponse({'status': 'error', 'message': 'No task name provided'})
    
    # Map frontend names to cache keys
    key_map = {
        'ticker_list': 'progress_ticker_list',
        'fundamentals': 'progress_fundamentals',
        'prices': 'progress_price_history',
        'iwb': 'progress_iwb',
        'sector_leaders': 'progress_sector_leaders',
        'ah_update': 'progress_ah_update',
        'backfill': 'progress_backfill'
    }
    cache_key = key_map.get(task_name)
    if not cache_key:
        from django.http import JsonResponse
        return JsonResponse({'status': 'error', 'message': 'Invalid task name'})
        
    from django.core.cache import cache
    from django.http import JsonResponse
    progress_data = cache.get(cache_key)
    
    if not progress_data:
        return JsonResponse({'status': 'idle', 'progress': 0, 'message': 'Waiting...'})
    
    # Transform backend format to frontend format
    # Backend: {'percent': int, 'message': str, 'finished': bool}
    # Frontend expects: {'status': str, 'progress': int, 'message': str}
    status = 'finished' if progress_data.get('finished') else 'running'
    
    return JsonResponse({
        'status': status,
        'progress': progress_data.get('percent', 0),
        'message': progress_data.get('message', '')
    })


def update_ah_prices_view(request):
    """
    [Admin Button] Update current day's Close Price with After-Hours Trade Price.
    Running in Thread (Async) to allow Progress Bar polling.
    """
    from .utils_ah import update_aftermarket_prices
    import threading
    
    if request.method != "POST":
        return redirect("admin:index")
        
    def _run():
        try:
            update_aftermarket_prices()
        except Exception as e:
            print(f"Error in AH Thread: {e}")

    # Start Thread
    t = threading.Thread(target=_run)
    t.daemon = True
    t.start()
    
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        from django.http import JsonResponse
        return JsonResponse({'status': 'success', 'message': 'Background task started.'})

    messages.success(request, "[AH Update] Task started in background. Check logs.")
    return redirect("admin:index")

def check_missing_history(request):
    """
    Returns JSON list of tickers with insufficient price history (< 1000 days).
    Used by Admin 'Check Data Health' button.
    """
    from django.http import JsonResponse
    from django.db.models import Count
    
    # Threshold: ~4 years (approx 1000 trading days)
    threshold = 1000
    
    bad_tickers = []
    # Identify tickers with low price history count
    qs = Ticker.objects.annotate(cnt=Count('price_history')).filter(cnt__lt=threshold).order_by('cnt')
    
    for t in qs:
        bad_tickers.append({
            'symbol': t.symbol,
            'count': t.cnt,
            'market': t.market or 'Unknown'
        })
        
    return JsonResponse({
        'status': 'success',
        'count': len(bad_tickers),
        'data': bad_tickers
    })

def backfill_history_view(request):
    """
    [Admin Button] Trigger Backfill Task (Repair).
    """
    from .tasks import run_backfill_missing_data
    import threading
    
    if request.method != "POST":
        return redirect("admin:index")
        
    def _run():
        try:
            run_backfill_missing_data()
        except Exception as e:
            print(f"Error in Backfill Thread: {e}")

    # Start Thread
    t = threading.Thread(target=_run)
    t.daemon = True
    t.start()
    
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        from django.http import JsonResponse
        return JsonResponse({'status': 'success', 'message': 'Backfill started.'})

    messages.success(request, "[Repair] Backfill task started.")
    return redirect("admin:index")


# ==========================================
# New Admin Button Wrappers (For Progress UI)
# ==========================================

def update_ticker_list(request):
    """
    [Admin Button] Update Ticker List (Wikipedia).
    Progress Key: 'progress_ticker_list'
    """
    import threading
    if request.method != "POST": return redirect("admin:index")
    
    def _run():
        try:
            # Task updates 'progress_ticker_list' internally?
            # tasks.py run_update_ticker_list docstring says Key: 'progress_ticker_list'
            run_update_ticker_list(force_update=True)
        except Exception as e:
            print(f"Error in Ticker List Thread: {e}")

    t = threading.Thread(target=_run)
    t.daemon = True
    t.start()
    
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        from django.http import JsonResponse
        return JsonResponse({'status': 'success', 'message': 'Ticker Index update started.'})
    
    messages.success(request, "Ticker Index update started.")
    return redirect("admin:index")

def update_fundamentals(request):
    """
    [Admin Button] Update Fundamentals (FMP).
    Progress Key: 'progress_fundamentals'
    """
    import threading
    if request.method != "POST": return redirect("admin:index")
    
    def _run():
        try:
            run_update_fundamentals()
        except Exception as e:
             print(f"Error in Fundamentals Thread: {e}")

    t = threading.Thread(target=_run)
    t.daemon = True
    t.start()
    
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        from django.http import JsonResponse
        return JsonResponse({'status': 'success', 'message': 'Fundamentals update started.'})
        
    messages.success(request, "Fundamentals update started.")
    return redirect("admin:index")

def update_daily_price(request):
    """
    [Admin Button] Update Daily Prices (FMP Quote).
    Progress Key: 'progress_price_history'
    """
    import threading
    if request.method != "POST": return redirect("admin:index")
    
    def _run():
        try:
            # Calls update_daily_close with None (All tickers)
            update_todays_close() 
        except Exception as e:
             print(f"Error in Price Update Thread: {e}")

    t = threading.Thread(target=_run)
    t.daemon = True
    t.start()
    
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        from django.http import JsonResponse
        return JsonResponse({'status': 'success', 'message': 'Daily Price update started.'})
        
    messages.success(request, "Daily Price update started.")
    return redirect("admin:index")

def data_download_scha_csv(request):
    """
    [Admin Button] Download SCHA CSV.
    Same as refresh_scha but using the services.download_latest_scha_csv logic?
    Wait, user wants 'Download' button to download file to server or to client?
    Template says: 'Save as: updatedata/data/scha.csv' and form target='_blank'.
    Original 'refresh_scha' redirected to Schwab URL.
    The new button triggers 'download_latest_scha_csv' which saves to Server.
    User might strictly want explicit download to server.
    
    If saving to server, we should run it in background and show progress?
    The template form has `target="_blank"`... which implies a client download?
    But the description says "Save as: .../scha.csv".
    Let's make it a background task that saves to server (like IWM Refresh).
    And remove target="_blank" from template if it's a background task. 
    However I already edited template.
    If I keep target="_blank", it expects a response.
    
    If I use local download function `services.download_latest_scha_csv` it returns (bool, msg).
    Let's align with IWM Refresh style. Run in background, check progress.
    I should assume template modification might be needed if I change behavior.
    But let's implement server-side download here.
    """
    import threading
    # If request is AJAX, run in background.
    # If not (e.g. form submit w/ target blank), maybe just run it?
    # But current form sets X-Requested-With for AJAX fetch? 
    # Yes, my JS handler adds X-Requested-With.
    
    if request.method != "POST": return redirect("admin:index")

    def _run():
        from .tasks import _set_progress
        cache_key = 'progress_scha' # Need to map this in check_task_progress?
        # Map: Template uses 'scha_csv'? No, I didn't set a data-task for SCHA?
        # Template: <button ...>Download</button>. No data-task.
        # Wait, the template SCHA button DOES NOT HAVE data-task?
        # Let's check template replacement.
        # Line ~237: <button type="submit" ...>Download</button>.
        # No data-task="...".
        # So my JS 'Unified Task Handler' (lines 664+) will NOT pick it up.
        # It will just submit the form normally (with target="_blank").
        # So it expects a file response or redirect.
        # Original logic was redirect to Schwab.
        # BUT `download_latest_scha_csv` saves to server.
        # I should probably just Redirect to Schwab as before if intent is client download.
        # BUT 'Save as: updatedata/data/scha.csv' implies server side.
        
        # Reverting to original logic: Redirect to Schwab.
        # User downloads it manually?
        pass

    # Use original refresh_scha logic but named data_download_scha_csv
    return refresh_scha(request)