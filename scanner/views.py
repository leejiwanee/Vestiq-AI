from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.core.paginator import Paginator
from django.contrib import messages
from django.utils import timezone
from django.db.models import Avg
from django.http import HttpResponse, JsonResponse
from django.utils.translation import gettext as _

import math
import csv
import yfinance as yf
import pandas as pd
import numpy as np
import numpy as np
from datetime import datetime, timedelta

from .models import DailyPick
from .models import ScanBatch, ScanRow, AiReport
from .models import ScanBatch, ScanRow, AiReport
from .services import scan_symbols
from .utils import get_options_chain # New import
from .company import get_company_profile, get_financials_for_ai
from updatedata.models import Ticker, PriceHistory
from insight.models import SectorPerformance  # Add missing import
from .email_utils import send_email_with_pdf
from .gemini_reports import generate_ai_report_structured, _normalize_conclusion
# from .news import fetch_company_news # Removed
from news.rss_service import GoogleNewsRSS
from django.template.loader import render_to_string
from django.utils.translation import get_language
from .backtest_service import BacktestEngine
import json


def _clean_float(v):
    try:
        if v is None:
            return None
        v = float(v)
        if math.isfinite(v):
            return v
    except Exception:
        pass
    return None


def format_volume(v):
    if v is None:
        return "-"
    v = float(v)
    if v >= 1_000_000_000:
        return f"{v/1_000_000_000:.1f}B"
    if v >= 1_000_000:
        return f"{v/1_000_000:.1f}M"
    if v >= 1000:
        return f"{v/1000:.1f}K"
    return str(int(v))




def dashboard_view(request):
    # 1. 최신 배치 가져오기
    batch = ScanBatch.objects.order_by("-started_at").first()
    
    active_filter = request.GET.get("f", "all")
    sort = request.GET.get("sort", "vol_desc")
    mode = request.GET.get("mode", "day") # 'day', 'swing', or 'long'

    if not batch:
        return render(request, "scanner/dashboard.html", {
            "batch": None, "total_count": 0, "triggered_count": 0, "filter_tabs": []
        })

    # 2. 전체 데이터셋 (Mode Based Filtering)
    from django.db.models import Q
    base_qs = ScanRow.objects.filter(batch=batch)
    
    has_value_field = hasattr(ScanRow, 'f_value')
    has_oversold_field = hasattr(ScanRow, 'f_oversold')

    # ▼▼▼ [Mode Logic] ▼▼▼
    # ▼▼▼ [Mode Logic] ▼▼▼
    # ▼▼▼ [Mode Logic] ▼▼▼
    if mode == 'long':
        # Long-term: Value + Oversold
        target_filters = ['value', 'oversold']
        page_title = _("Scanner (Long-term)")
        
        # In Long mode, we primarily look for Value OR Oversold
        # But for 'All' tab, we show Union.
        q_mode = Q(f_value=True) | Q(f_oversold=True)
        all_qs = base_qs.filter(q_mode)

    elif mode == 'swing':
        # Swing: Trend, Pattern, Lux, Oversold, Squeeze
        target_filters = ['trend', 'pattern', 'lux', 'oversold', 'squeeze']
        page_title = _("Scanner (Swing)")
        
        q_mode = Q(f_trend=True) | Q(f_pattern=True) | Q(f_lux=True) | Q(f_oversold=True) | Q(f_squeeze=True)
        all_qs = base_qs.filter(q_mode)

    else:
        # Day Trading: Volume, Volatility, Momentum, Gap, VCS
        target_filters = ['volume', 'volatility', 'momentum', 'gap', 'vcs']
        page_title = _("Scanner (Day Trading)")
        
        q_mode = Q(f_volume=True) | Q(f_volatility=True) | Q(f_momentum=True) | Q(f_gap=True) | Q(vcs__gte=65)
        all_qs = base_qs.filter(q_mode)

    # 3. 카운트 계산 (Robust Method: use base_qs for individual filters to ensure counts are accurate even if all_qs logic varies)
    # However, conventionally, tabs show counts WITHIN the current Mode's universe.
    # Since Mode Universe is Union of filters, Count(Filter X) inside Union is just Count(Filter X).
    # So using all_qs.filter(...) is logically equivalent to base_qs.filter(...) for the target filters.
    # But to prevent "0" paradox, we'll verify base_qs first.
    
    def _safe_count(qs, **kwargs):
        return qs.filter(**kwargs).count()

    counts = {
        'all': all_qs.count(),
        'volume': _safe_count(base_qs, f_volume=True),
        'volatility': _safe_count(base_qs, f_volatility=True),
        'trend': _safe_count(base_qs, f_trend=True),
        'pattern': _safe_count(base_qs, f_pattern=True),
        'momentum': _safe_count(base_qs, f_momentum=True),
        'value': _safe_count(base_qs, f_value=True),
        'oversold': _safe_count(base_qs, f_oversold=True),
        'lux': _safe_count(base_qs, f_lux=True),
        'gap': _safe_count(base_qs, f_gap=True),
        'squeeze': _safe_count(base_qs, f_squeeze=True),
        'vcs': _safe_count(base_qs, vcs__gte=65),
    }

    # ▼▼▼ [Configuration] Filter Config (Colors & Labels) ▼▼▼
    FILTER_CONFIG = {
        'volume': {'label': _("Volume"), 'color': '#f97316'},      # Orange
        'volatility': {'label': _("Volatility"), 'color': '#a855f7'}, # Purple
        'trend': {'label': _("Trend"), 'color': '#3b82f6'},        # Blue
        'pattern': {'label': _("Pattern"), 'color': '#6366f1'},    # Indigo
        'momentum': {'label': _("Momentum"), 'color': '#06b6d4'},  # Cyan
        'value': {'label': _("Value"), 'color': '#10b981'},        # Emerald
        'oversold': {'label': _("Oversold"), 'color': '#f43f5e'},  # Rose
        'lux': {'label': _("Smart Pattern"), 'color': '#ec4899'},       # Pink
        'gap': {'label': _("Gap Up"), 'color': '#8b5cf6'},         # Violet
        'squeeze': {'label': _("Squeeze"), 'color': '#f59e0b'},    # Amber
        'vcs': {'label': _("VCS High"), 'color': '#059669'},       # Emerald Dark
    }

    # Filter tabs based on mode
    # "All" is always first
    filter_tabs = [("all", _("All"), counts['all'])]
    
    for key in target_filters:
        cfg = FILTER_CONFIG.get(key, {})
        label = cfg.get('label', key.capitalize())
        filter_tabs.append((key, label, counts[key]))

    # ▼▼▼ [Restored] QS Definition & Filtering ▼▼▼
    qs = all_qs
    if active_filter == "volume": qs = all_qs.filter(f_volume=True)
    elif active_filter == "volatility": qs = all_qs.filter(f_volatility=True)
    elif active_filter == "trend": qs = all_qs.filter(f_trend=True)
    elif active_filter == "pattern": qs = all_qs.filter(f_pattern=True)
    elif active_filter == "momentum": qs = all_qs.filter(f_momentum=True)
    elif active_filter == "value": 
        qs = all_qs.filter(f_value=True) if has_value_field else all_qs.none()
    elif active_filter == "oversold":
        qs = all_qs.filter(f_oversold=True) if has_oversold_field else all_qs.none()
    elif active_filter == "lux":
        qs = all_qs.filter(f_lux=True)
    elif active_filter == "gap":
        qs = all_qs.filter(f_gap=True)
    elif active_filter == "squeeze":
        qs = all_qs.filter(f_squeeze=True)
    elif active_filter == "vcs":
        qs = all_qs.filter(vcs__gte=65)

    # [Fix for Sorting]
    # If there are rows with vcs=None in the current queryset (or batch), sorting by VCS won't work correctly.
    # We should calculate and save them before ordering.
    # To avoid performance hit on every load, we only do this if we detect nulls.
    if qs.filter(vcs__isnull=True).exists():
        # Fetch Market Score
        try:
            from ai_advisor.recommendation_service import check_macro_filter
            macro_data = check_macro_filter()
            market_score = macro_data.get('score', 50)
        except:
            market_score = 50
            
        # Fetch Tickers for P/E
        null_rows = qs.filter(vcs__isnull=True)
        # Limit to batch size to avoid timeout if too many? 
        # Usually scanner results are < 2000. Let's do all.
        
        # We need ticker map for these rows
        symbols = list(null_rows.values_list('symbol', flat=True))
        ticker_map = {t.symbol: t for t in Ticker.objects.filter(symbol__in=symbols)}
        
        rows_to_update = []
        for row in null_rows:
            # A. Tech
            tech_points = sum([
                row.f_trend, row.f_momentum, row.f_lux
            ])
            tech_score = (tech_points / 3) * 50
            
            # B. Value
            t = ticker_map.get(row.symbol)
            pe = getattr(t, 'pe_ratio', None) if t else None
            pe_score = 0.0
            if pe is not None:
                if 0 < pe < 25: pe_score = 1.0
                elif 25 <= pe < 50: pe_score = 0.5
            
            val_points = (1.0 if row.f_value else 0.0) + pe_score
            value_score = (val_points / 2) * 30
            
            # C. Market
            mkt_score = (market_score / 100) * 20
            
            row.vcs = int(tech_score + value_score + mkt_score)
            rows_to_update.append(row)
        
        if rows_to_update:
            ScanRow.objects.bulk_update(rows_to_update, ['vcs'])

    # 5. 정렬
    sort_map = {
        "price_desc": "-price_change_pct",
        "price_asc": "price_change_pct",
        "vol_asc": "vol_change_pct",
        "vol_desc": "-vol_change_pct",
        "vcs_desc": "-vcs",
        "vcs_asc": "vcs",
    }
    qs = qs.order_by(sort_map.get(sort, "-vol_change_pct"))

    # 6. 페이지네이션
    paginator = Paginator(qs, 50)
    page_obj = paginator.get_page(request.GET.get("page"))

    # 7. 통계
    avg_chg = qs.aggregate(Avg("price_change_pct"))["price_change_pct__avg"] or 0
    trigger_cnt = qs.filter(trigger=True).count()
    trigger_share = (trigger_cnt / counts['all'] * 100) if counts['all'] > 0 else 0
    
    # [New] Market Sentiment (Up/Down)
    up_count = qs.filter(price_change_pct__gt=0).count()
    down_count = qs.filter(price_change_pct__lt=0).count()

    # ▼▼▼ [Chart Data Logic] ▼▼▼
    chart_title = ""
    chart_data = []

    if active_filter == "all":
        # [All Tab] Show "Filter Distribution"
        chart_title = _("Filter Distribution")
        for key in target_filters:
            cnt = counts.get(key, 0)
            if cnt > 0:
                cfg = FILTER_CONFIG.get(key, {})
                chart_data.append({
                    'label': cfg.get('label', key.capitalize()),
                    'count': cnt,
                    'color': cfg.get('color', '#22c55e'),
                    'key': key
                })
    else:
        # [Specific Filter Tab] Show "Cross Filter Analysis"
        chart_title = _("Cross Filter Analysis")
        if qs.exists():
            subset_ids = list(qs.values_list('id', flat=True))
            subset = ScanRow.objects.filter(id__in=subset_ids)
            
            for key in target_filters:
                if key == active_filter: continue
                try:
                    c = subset.filter(**{f"f_{key}": True}).count()
                    if c > 0:
                        cfg = FILTER_CONFIG.get(key, {})
                        chart_data.append({
                            'label': cfg.get('label', key.capitalize()),
                            'count': c,
                            'color': cfg.get('color', '#22c55e'),
                            'key': key
                        })
                except: pass

    # VCS is now stored in DB, but for old records (None), we calculate on the fly for display.
    # Fetch Market Score
    try:
        from ai_advisor.recommendation_service import check_macro_filter
        macro_data = check_macro_filter()
        market_score = macro_data.get('score', 50)
        
        # [Error Handling]
        if macro_data.get('error'):
            messages.warning(request, "시장 데이터를 가져오는데 실패했습니다. 새로고침 하거나 5~10초 뒤에 다시 시도해주세요.")
    except:
        market_score = 50

    # Fetch Tickers for P/E Ratio (needed for fallback calculation)
    page_symbols = [r.symbol for r in page_obj]
    ticker_map = {t.symbol: t for t in Ticker.objects.filter(symbol__in=page_symbols)}

    for row in page_obj:
        if row.vcs is None:
            # Fallback Calculation
            # A. Tech (50%)
            tech_points = sum([
                getattr(row, 'f_trend', False),
                getattr(row, 'f_momentum', False),
                getattr(row, 'f_lux', False)
            ])
            tech_score = (tech_points / 3) * 50
            
            # B. Value (30%)
            t = ticker_map.get(row.symbol)
            pe_ratio = getattr(t, 'pe_ratio', None) if t else None
            
            pe_score = 0.0
            if pe_ratio is not None:
                if 0 < pe_ratio < 25: pe_score = 1.0
                elif 25 <= pe_ratio < 50: pe_score = 0.5
            
            val_points = (1.0 if getattr(row, 'f_value', False) else 0.0) + pe_score
            value_score = (val_points / 2) * 30
            
            # C. Market (20%)
            mkt_score = (market_score / 100) * 20
            
            row.vcs = int(tech_score + value_score + mkt_score)
            
            # Save to DB so sorting works next time
            row.save(update_fields=['vcs'])

    context = {
        "batch": batch,
        "page_obj": page_obj,
        "active_filter": active_filter,
        "sort": sort,
        "mode": mode,
        "page_title": page_title,
        "total_count": qs.count(),
        "triggered_count": trigger_cnt,
        "avg_price_change": avg_chg,
        "trigger_share": trigger_share,
        "filter_tabs": filter_tabs,
        "counts": counts,
        "chart_title": chart_title, 
        "chart_data": chart_data,   
        "base_label": active_filter.capitalize(),
        "up_count": up_count,       
        "down_count": down_count,   
        "market_score": market_score,
    }
    return render(request, "scanner/dashboard.html", context)




# scanner/views.py

# ... (상단 import 유지) ...

def run_scan_view(request):
    if request.method != "POST":
        return redirect("scanner:dashboard")
    
    # ▼▼▼ [수정] is_active=True 필터 제거 -> .all() 사용 ▼▼▼
    tickers = list(
        Ticker.objects.all()
        .order_by("symbol")
        .values_list("symbol", flat=True)
    )
    # ▲▲▲ 수정 완료 ▲▲▲
    
    if not tickers:
        messages.warning(request, "Active universe가 비어 있습니다. 먼저 'Update Universe'를 실행해주세요.")
        return redirect("scanner:dashboard")
        
    # 2. 스캔 실행 (계산)
    df, metrics = scan_symbols(tickers)
    
    if df is None or df.empty:
        messages.warning(request, "스캔 결과가 없습니다. (DailyPrice 데이터가 비어있을 수 있습니다.)")
        return redirect("scanner:dashboard")

    # 3. 결과 저장 (Refactored to use service)
    from .services import save_scan_results
    batch = save_scan_results(df, metrics)
    
    messages.success(request, f"Scan 완료: {metrics.get('scanned', 0)}개 종목 분석됨. (Triggered: {metrics.get('triggers', 0)})")
    
    # Redirect back to the same mode
    mode = request.POST.get("mode", "short")
    return redirect(f"{reverse('scanner:dashboard')}?mode={mode}")





def export_scan_csv(request):
    """
    선택한 종목 CSV 다운로드 (POST 요청 처리)
    """
    if request.method != "POST":
        return redirect("scanner:dashboard")

    symbols = request.POST.getlist("symbols")
    if not symbols:
        messages.warning(request, "다운로드할 종목을 하나 이상 선택해주세요.")
        return redirect("scanner:dashboard")

    batch = ScanBatch.objects.order_by("-started_at").first()
    if not batch:
        return redirect("scanner:dashboard")

    rows = ScanRow.objects.filter(batch=batch, symbol__in=symbols).order_by('symbol')

    # CSV 생성
    response = HttpResponse(
        content_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="scan_results.csv"'},
    )

    writer.writerow([
        "Ticker", "Company", "Industry", 
        "Close", "Volume", "Prev Vol", 
        "Price Chg%", "Vol Chg%", 
        "Vol", "Vola", "Trend", "Pat", "Mom", "Val", "Smart Pattern", "Gap", "Sqz", "Trigger"
    ])

    for r in rows:
        # f_value 필드 안전하게 가져오기
        is_val = getattr(r, 'f_value', False)
        is_lux = getattr(r, 'f_lux', False)
        is_gap = getattr(r, 'f_gap', False)
        is_sqz = getattr(r, 'f_squeeze', False)
        
        writer.writerow([
            r.symbol, r.company, r.industry,
            r.close, r.volume, r.prev_volume,
            r.price_change_pct, r.vol_change_pct,
            "O" if r.f_volume else "",
            "O" if r.f_volatility else "",
            "O" if r.f_trend else "",
            "O" if r.f_pattern else "",
            "O" if r.f_momentum else "",
            "O" if is_val else "",
            "O" if is_lux else "",
            "O" if is_gap else "",
            "O" if is_sqz else "",
            "YES" if r.trigger else "NO"
        ])

    return response




def report_view(request, symbol):
    # 가장 최근 배치에서 해당 심볼 1개 가져오기 (너가 쓰는 방식에 맞게 조정 가능)
    batch = ScanBatch.objects.order_by("-started_at").first()
    row = get_object_or_404(ScanRow, batch=batch, symbol=symbol)

    # ----- 기본 값 꺼내기 -----
    close = getattr(row, "close", None)
    volume = getattr(row, "volume", None)
    prev_volume = getattr(row, "prev_volume", None)

    # 이미 모델에 price_change_pct / vol_change_pct 같은 필드가 있으면 우선 사용
    price_change_pct = getattr(row, "price_change_pct", None)
    vol_change_pct = getattr(row, "vol_change_pct", None)

    # 없으면 직접 계산 (prev_close / prev_volume 이 있을 때만)
    # prev_close 필드 이름은 프로젝트에 맞게 조정해도 됨
    if price_change_pct is None:
        prev_close = getattr(row, "prev_close", None)
        if close is not None and prev_close not in (None, 0):
            price_change_pct = (close - prev_close) / prev_close * 100.0

    if vol_change_pct is None:
        if volume not in (None,) and prev_volume not in (None, 0):
            vol_change_pct = (volume - prev_volume) / prev_volume * 100.0

    # ----- stats dict 만들기 (템플릿 + Gemini 둘 다 여기 값 사용) -----
    stats = {
        "close": close,
        "price_change_pct": price_change_pct,
        "vol_change_pct": vol_change_pct,
        "volume": volume,
        "prev_volume": prev_volume,
        # 아래 5개 필터는 있으면 True/False 값 넣어주고, 없으면 None
        "f_volume": getattr(row, "f_volume", None),
        "f_volatility": getattr(row, "f_volatility", None),
        "f_trend": getattr(row, "f_trend", None),
        "f_pattern": getattr(row, "f_pattern", None),
        "f_momentum": getattr(row, "f_momentum", None),
    }

    company = {
        "name": getattr(row, "company_name", "") or symbol,
        "sector": getattr(row, "sector", "") or "",
        "industry": getattr(row, "industry", "") or "",
    }

    # Detect user's language
    from django.utils.translation import get_language
    lang_code = get_language()
    language = 'en' if lang_code == 'en' else 'ko'

    # Fetch News immediately (Real-time) -> MOVED TO AJAX
    # news_items = fetch_company_news(company["name"] or symbol, days=7, max_items=5)
    news_items = [] # Load via AJAX

    # AI Report is now loaded via AJAX (api_ai_report)
    # We pass basic stats to the template so it can render the "Latest Scan" section immediately.

    context = {
        "symbol": symbol,
        "row": row,
        "stats": stats,
        "company_name": company["name"],
        "sector": company["sector"],
        "industry": company["industry"],
        "news_items": news_items,  # Empty initially
        "prev_filter": request.GET.get("f", ""),
        "prev_sort": request.GET.get("sort", ""),
    }
    return render(request, "scanner/report.html", context)


from django.views.decorators.cache import cache_page

@cache_page(60 * 5) # Cache for 5 minutes (News updates frequently)
def api_news(request):
    """
    AJAX endpoint to fetch news from FMP API.
    Expects 'symbol' as GET parameter.
    Uses endpoint: https://financialmodelingprep.com/stable/news/stock
    """
    from django.conf import settings
    import requests
    
    symbol = request.GET.get('symbol')
    if not symbol:
         return JsonResponse({'status': 'error', 'message': 'Symbol required'}, status=400)

    api_key = getattr(settings, 'FMP_API_KEY', None)
    if not api_key:
        return JsonResponse({'status': 'error', 'message': 'FMP API Key not configured'}, status=500)
        
    # User requested specific endpoint:
    # https://financialmodelingprep.com/stable/news/stock?symbols={symbol}&apikey={api_key}
    url = f"https://financialmodelingprep.com/stable/news/stock?symbols={symbol}&apikey={api_key}&limit=10"
    
    news_items = []
    try:
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            # FMP 'stable/news/stock' structure is array of objects
            # { "symbol": "AAPL", "publishedDate": "...", "title": "...", "image": "...", "site": "...", "text": "...", "url": "..." }
            for item in data:
                news_items.append({
                    "title": item.get('title'),
                    "url": item.get('url'),
                    "site": item.get('site'),
                    "publishedDate": item.get('publishedDate'),
                    "image": item.get('image'),
                    "text": item.get('text')
                })
        else:
             print(f"FMP Error: {resp.status_code} - {resp.text}")
             
    except Exception as e:
        print(f"News Fetch Error: {e}")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
        
    return JsonResponse({'status': 'ok', 'data': news_items})


@cache_page(60 * 5)
def vm_get_options(request, symbol):
    """
    API to fetch options chain for a symbol.
    """
    data = get_options_chain(symbol)
    if data:
        return JsonResponse({'status': 'ok', 'data': data})
    else:
        return JsonResponse({'status': 'error', 'message': 'No options data found'}, status=404)



def api_ai_report(request, symbol):
    """
    AJAX endpoint to generate/fetch AI Report HTML.
    Handles both Scanner symbols and general market tickers (via yfinance fallback).
    """
    try:
        # 1. Try to fetch ScanRow from latest batch
        batch = ScanBatch.objects.order_by("-started_at").first()
        row = None
        if batch:
            row = ScanRow.objects.filter(batch=batch, symbol=symbol).first()

        # 2. Reconstruct stats/company
        stats = {}
        company = {}
        
        if row:
            # --- CASE A: Found in Scanner ---
            close = getattr(row, "close", None)
            volume = getattr(row, "volume", None)
            prev_volume = getattr(row, "prev_volume", None)
            price_change_pct = getattr(row, "price_change_pct", None)
            vol_change_pct = getattr(row, "vol_change_pct", None)

            if price_change_pct is None:
                prev_close = getattr(row, "prev_close", None)
                if close is not None and prev_close not in (None, 0):
                    price_change_pct = (close - prev_close) / prev_close * 100.0

            if vol_change_pct is None:
                if volume not in (None,) and prev_volume not in (None, 0):
                    vol_change_pct = (volume - prev_volume) / prev_volume * 100.0

            stats = {
                "close": close,
                "price_change_pct": price_change_pct,
                "vol_change_pct": vol_change_pct,
                "volume": volume,
                "prev_volume": prev_volume,
                "f_volume": getattr(row, "f_volume", None),
                "f_volatility": getattr(row, "f_volatility", None),
                "f_trend": getattr(row, "f_trend", None),
                "f_pattern": getattr(row, "f_pattern", None),
                "f_momentum": getattr(row, "f_momentum", None),
            }

            company = {
                "name": getattr(row, "company_name", "") or symbol,
                "sector": getattr(row, "sector", "") or "",
                "industry": getattr(row, "industry", "") or "",
            }
        else:
            # --- CASE B: Fallback (Macro/General Ticker) ---
            # Fetch minimal data from YFinance for missing tickers
            try:
                ticker = yf.Ticker(symbol)
                hist = ticker.history(period="5d")
                
                if not hist.empty:
                    latest = hist.iloc[-1]
                    prev = hist.iloc[-2] if len(hist) > 1 else latest
                    
                    close = latest['Close']
                    prev_close = prev['Close']
                    
                    price_change_pct = ((close - prev_close) / prev_close * 100.0) if prev_close else 0.0
                    volume = latest['Volume']
                    
                    stats = {
                        "close": close,
                        "price_change_pct": price_change_pct,
                        "vol_change_pct": 0, # N/A
                        "volume": volume,
                        "prev_volume": 0,
                        "f_volume": False,
                        "f_volatility": False,
                        "f_trend": False, 
                        "f_pattern": False, 
                        "f_momentum": False,
                    }
                    
                    # Try to get company name from Ticker model or YF
                    db_ticker = Ticker.objects.filter(symbol=symbol).first()
                    company_name = db_ticker.company_name if db_ticker else symbol
                    sector = db_ticker.sector if db_ticker else "Macro/Index"
                    industry = db_ticker.industry if db_ticker else ""
                    
                    company = {
                        "name": company_name,
                        "sector": sector,
                        "industry": industry,
                    }
                    
                    # Create a dummy row object for the template
                    class DummyRow:
                        def __init__(self, s, c, p):
                            self.symbol = s
                            self.company = c
                            self.price_change_pct = p
                            self.flt_str = "" # Required by template often
                            self.vcs = 0
                    
                    row = DummyRow(symbol, company_name, price_change_pct)
                    
                else:
                    return JsonResponse({"error": f"No data found for {symbol}"}, status=404)
            except Exception as e:
                return JsonResponse({"error": f"Failed to fetch data for {symbol}: {str(e)}"}, status=500)

        # 3. Detect Language
        from django.utils.translation import get_language
        lang_code = get_language()
        language = 'en' if lang_code == 'en' else 'ko'

        # 4. Fetch Financials & Generate AI Report
        financials = get_financials_for_ai(symbol)
        ai_report, error = generate_ai_report_structured(
            symbol=symbol,
            stats=stats,
            company=company,
            financials=financials,
            language=language
        )

        if error:
            # If AI fails, we still might want to show the basic chart page
            # But specific error message is helpful
            pass # Continue to render what we have or return error?
            # return JsonResponse({"error": error}, status=500)

        # Extract fair value for separate display if available
        fair_value = ai_report.get("fair_value") if ai_report else None
        
        context = {
            "symbol": symbol,
            "row": row,
            "stats": stats,
            "ai_report": ai_report,
            "fair_value": fair_value,
            "ai_disabled": False # AI is enabled
        }
        
        html = render_to_string("scanner/partials/ai_report_content.html", context, request=request)
        
        return JsonResponse({"html": html})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({"error": f"Internal Server Error: {str(e)}"}, status=500)




def detail_view(request, symbol):
    """
    개별 종목 상세 페이지 — 기본적으로 ScanRow 하나를 그대로 보여줌.
    """
    row = get_object_or_404(ScanRow, symbol=symbol)
    return render(request, "scanner/detail.html", {"row": row})


def send_scan_email(request):
    """
    대시보드에서 선택한 종목들을 모아서 PDF 리포트 이메일 발송.
    - 오늘 배치가 있으면 오늘 배치들 ever-triggered 기준
    - 없으면 최신 배치 기준
    """
    if request.method != "POST":
        return redirect("scanner:dashboard")

    symbols = request.POST.getlist("symbols")
    if not symbols:
        messages.warning(request, "먼저 이메일로 보낼 종목을 선택해 주세요.")
        return redirect("scanner:dashboard")

    today = timezone.localdate()
    
    # ... (기존 로직 유지) ...
    # 여기서는 배치 기반 발송 로직이므로 그대로 둠

    return redirect("scanner:dashboard")

# --- Vestiq Pick Strategy Helpers ---

def calculate_heikin_ashi(df):
    """
    Calculate Heikin-Ashi candles.
    df must have 'Open', 'High', 'Low', 'Close'.
    Returns df with 'HA_Open', 'HA_High', 'HA_Low', 'HA_Close', 'HA_Color'.
    """
    df = df.copy()
    
    # Heikin-Ashi Close
    df['HA_Close'] = (df['Open'] + df['High'] + df['Low'] + df['Close']) / 4
    
    # Heikin-Ashi Open
    # HA_Open = (Prev HA_Open + Prev HA_Close) / 2
    # Initialize first value with regular Open
    ha_open = [df['Open'].iloc[0]]
    for i in range(1, len(df)):
        ha_open.append((ha_open[-1] + df['HA_Close'].iloc[i-1]) / 2)
    df['HA_Open'] = ha_open
    
    # Heikin-Ashi High/Low
    df['HA_High'] = df[['High', 'HA_Open', 'HA_Close']].max(axis=1)
    df['HA_Low'] = df[['Low', 'HA_Open', 'HA_Close']].min(axis=1)
    
    # Color (1=Green, -1=Red)
    df['HA_Color'] = 0
    df.loc[df['HA_Close'] > df['HA_Open'], 'HA_Color'] = 1
    df.loc[df['HA_Close'] < df['HA_Open'], 'HA_Color'] = -1
    
    return df

def calculate_smart_trail(df, atr_period=14, factor=3.0):
    """
    Calculate Smart Trail (similar to Supertrend).
    """
    df = df.copy()
    
    # ATR
    high_low = df['High'] - df['Low']
    high_close = (df['High'] - df['Close'].shift()).abs()
    low_close = (df['Low'] - df['Close'].shift()).abs()
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = ranges.max(axis=1)
    df['ATR'] = true_range.rolling(atr_period).mean()
    
    # Basic Bands
    df['Basic_Upper'] = (df['High'] + df['Low']) / 2 + (factor * df['ATR'])
    df['Basic_Lower'] = (df['High'] + df['Low']) / 2 - (factor * df['ATR'])
    
    # Final Bands
    df['Final_Upper'] = 0.0
    df['Final_Lower'] = 0.0
    df['Smart_Trail'] = 0.0
    
    # Iterative calculation for Trailing Stop logic
    # Using simple loop for clarity (vectorization is hard for state-dependent logic)
    curr_trend = 1 # 1=Uptrend, -1=Downtrend
    
    final_upper = [0.0] * len(df)
    final_lower = [0.0] * len(df)
    trend = [1] * len(df)
    smart_trail = [0.0] * len(df)
    
    close = df['Close'].values
    basic_upper = df['Basic_Upper'].values
    basic_lower = df['Basic_Lower'].values
    
    for i in range(1, len(df)):
        # Upper Band Logic
        if basic_upper[i] < final_upper[i-1] or close[i-1] > final_upper[i-1]:
            final_upper[i] = basic_upper[i]
        else:
            final_upper[i] = final_upper[i-1]
            
        # Lower Band Logic
        if basic_lower[i] > final_lower[i-1] or close[i-1] < final_lower[i-1]:
            final_lower[i] = basic_lower[i]
        else:
            final_lower[i] = final_lower[i-1]
            
        # Trend Logic
        if trend[i-1] == 1:
            if close[i] < final_lower[i-1]:
                trend[i] = -1
            else:
                trend[i] = 1
        else:
            if close[i] > final_upper[i-1]:
                trend[i] = 1
            else:
                trend[i] = -1
                
        smart_trail[i] = final_lower[i] if trend[i] == 1 else final_upper[i]
        
    df['Smart_Trail'] = smart_trail
    df['Trend'] = trend
    return df

    return list(set(signals))


def calculate_stoch_slow(df, n=14, m=3, t=3):
    """
    Calculate Stochastic Slow.
    Fast %K = ((Close - LowMin) / (HighMax - LowMin)) * 100
    Fast %D = SMA(Fast %K, m)  <- This is 'Slow %K'
    Slow %D = SMA(Fast %D, t)  <- This is 'Slow %D'
    Returns tuple (Slow %K, Slow %D)
    """
    low_min = df['Low'].rolling(window=n).min()
    high_max = df['High'].rolling(window=n).max()
    
    # Fast %K
    fast_k = 100 * ((df['Close'] - low_min) / (high_max - low_min))
    
    # Fast %D (which becomes Slow %K)
    slow_k = fast_k.rolling(window=m).mean()
    
    # Slow %D
    slow_d = slow_k.rolling(window=t).mean()
    
    return slow_k, slow_d


    return slow_k, slow_d


def get_kim_comment(df):
    """
    Generates analysis commentary in 'Kim's US Stock' style.
    Based on Stoch Triple Screen Status.
    """
    if len(df) < 60: return "데이터 부족 (Insufficient Data)"
    
    # Recalculate latest indicators needed for context
    k_short, d_short = calculate_stoch_slow(df, 5, 3, 3)
    k_long, d_long = calculate_stoch_slow(df, 20, 12, 12)
    
    curr = df.iloc[-1]
    
    l_k = k_long.iloc[-1]
    l_d = d_long.iloc[-1]
    
    s_k = k_short.iloc[-1]
    
    # 1. Trend Analysis
    trend_up = (l_k > l_d) or (l_k > k_long.iloc[-2])
    
    # 2. Support Analysis
    ma20 = curr['SMA20']
    ma60 = curr['SMA60']
    close = curr['Close']
    
    near_60 = abs(close - ma60) / ma60 < 0.03
    near_20 = abs(close - ma20) / ma20 < 0.03
    
    comment_parts = []
    
    # Trend Part
    if trend_up:
        comment_parts.append("장기 지표는 우상향으로 추세가 살아있습니다.")
    else:
        comment_parts.append("장기 추세가 다소 꺾여있어 주의가 필요합니다.")
        
    # Situational Part
    if s_k <= 25:
        comment_parts.append("단기 지표가 과매도 구간에서 쉬어가고 있으므로, 지금이 매집하기 좋은 기회(눌림목)입니다.")
    elif s_k >= 75:
        comment_parts.append("단기 지표가 과열 구간(과매수)에 진입했습니다. 힘이 빠질 수 있으니 무리하게 진입하기보다 조정 후 다시 타점을 잡는 게 좋습니다.")
    else:
        comment_parts.append("단기 흐름은 중립적입니다. 확실한 타점(과매도/과매수)을 기다리는 것이 좋습니다.")
        
    # Support Part
    if near_60:
        comment_parts.append("특히 초록색 선(60일선) 지지 라인을 지켜주는지 확인해야 합니다.")
    elif near_20:
        comment_parts.append("노란색 선(20일선) 지지를 받고 반등하는지 체크해보세요.")
        
    return " ".join(comment_parts)


def calculate_adx(df, period=14):
    """
    Calculate ADX (Average Directional Index).
    df requires: 'High', 'Low', 'Close'.
    Returns a Series for ADX.
    """
    if len(df) < period * 2:
        return pd.Series([0]*len(df), index=df.index)
        
    # 1. TR, +DM, -DM
    high = df['High']
    low = df['Low']
    close = df['Close']
    prev_close = close.shift(1)
    
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    up_move = high - high.shift(1)
    down_move = low.shift(1) - low
    
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    
    # 2. Smooth them (Wilder's Smoothing)
    # Wilder's Smoothing usually = EMA(alpha=1/n) or similar. 
    # Standard ADX uses alpha = 1/period.
    
    # Function to smooth
    def wilder_smooth(series, n):
        # Initialize with SMA
        first_valid = series.first_valid_index()
        if first_valid is None: return series
        
        # We can use ewm(alpha=1/n, adjust=False) for Wilder's
        return pd.Series(series).ewm(alpha=1/n, adjust=False).mean()

    # Note: Traditional ADX method (Wilder) often uses specific recursive smoothing.
    # Pandas EWM with adjust=False and alpha=1/n is very close or identical.
    
    tr_smooth = tr.ewm(alpha=1/period, adjust=False).mean()
    plus_dm_smooth = pd.Series(plus_dm, index=df.index).ewm(alpha=1/period, adjust=False).mean()
    minus_dm_smooth = pd.Series(minus_dm, index=df.index).ewm(alpha=1/period, adjust=False).mean()
    
    # 3. DX
    plus_di = 100 * (plus_dm_smooth / tr_smooth)
    minus_di = 100 * (minus_dm_smooth / tr_smooth)
    
    dx = 100 * (abs(plus_di - minus_di) / (plus_di + minus_di))
    
    # 4. ADX (Smooth DX)
    adx = dx.ewm(alpha=1/period, adjust=False).mean()
    
    return adx


def calculate_vestiq_strategies(df):
    """
    [Vestiq Pick 5.5 - Kim's Method Strict]
    Stochastic Triple Screen Logic.
    
    Logic:
    - ALPHA (Buy): Long Stoch Bullish + Short Stoch Entry (<=20 or GC near 20)
    - HEDGE (Sell): Short Stoch Overheat (>=80 or DC near 80)
    """
    if len(df) < 120:
        return []

    signals = []
    
    # --- 1. Indicators ---
    # MAs
    df['SMA20'] = df['Close'].rolling(20).mean()
    df['SMA60'] = df['Close'].rolling(60).mean()
    df['SMA120'] = df['Close'].rolling(120).mean()
    
    # Stochastics (K, D)
    k_short, d_short = calculate_stoch_slow(df, 5, 3, 3)
    k_mid, d_mid = calculate_stoch_slow(df, 10, 6, 6)
    k_long, d_long = calculate_stoch_slow(df, 20, 12, 12)
    
    # Values
    s_k = k_short.iloc[-1]
    s_d = d_short.iloc[-1]
    prev_s_k = k_short.iloc[-2]
    prev_s_d = d_short.iloc[-2]
    
    # Mid Stoch (Headroom Check)
    m_k = k_mid.iloc[-1]
    prev_m_k = k_mid.iloc[-2]
    
    # Long Stoch (Momentum)
    l_k = k_long.iloc[-1]
    prev_l_k = k_long.iloc[-2]
    l_d = d_long.iloc[-1]
    
    close = df['Close'].iloc[-1]
    prev_close = df['Close'].iloc[-2]
    
    sma20 = df['SMA20'].iloc[-1]
    prev_sma20 = df['SMA20'].iloc[-2]
    # sma60 = df['SMA60'].iloc[-1] # Not used in sophisticated logic
    sma120 = df['SMA120'].iloc[-1]
    
    # Stochastics (12, 5, 5) for Kumo Strategies (Shared)
    stoch_k_12, stoch_d_12 = calculate_stoch_slow(df, 12, 5, 5)
    
    # Volume Check
    vol = df['Volume'].iloc[-1]
    prev_vol = df['Volume'].iloc[-2]
    sma20_vol = df['Volume'].rolling(20).mean().iloc[-1]
    
    # ==========================================
    # ★ ALPHA (The "Perfect" Dip) - Relaxed
    # ==========================================
    # Logic:
    # 1. Macro Trend: Close > SMA60 (Mid-term Bull Market Context) - Relaxed from 120
    # 2. Momentum: Long Stoch K Rising (Triple Screen Support)
    # 3. Headroom: Mid Stoch K < 70 (Not already extended) - Relaxed from 60
    # 4. Trigger: Short Stoch Golden Cross < 30 (Precision Entry)
    
    # [Relaxation] Use SMA60 instead of SMA120 for Trend
    is_bull_market = (close > df['SMA60'].iloc[-1]) 
    
    # [Tightened] Use small threshold to avoid flat/noise trends
    is_momentum_up = l_k > (prev_l_k + 0.1)
    is_headroom_ok = m_k < 70 # Relaxed
    is_gold_cross_low = (prev_s_k < prev_s_d) and (s_k > s_d) and (s_k < 30)
    
    # [New] also allow if ALREADY crossed recently and still in oversold zone (Early Momentum)
    # i.e. K > D and K < 35. This catches the "day after" or "2 days after" entry.
    is_in_alpha_zone = (s_k > s_d) and (s_k < 35) 
    
    if is_bull_market and is_momentum_up and is_headroom_ok and (is_gold_cross_low or is_in_alpha_zone):
        signals.append("Alpha")
        
    # ==========================================
    # ▼ HEDGE (Technical Breakdown)
    # ==========================================
    # Logic:
    # 1. Trend Broken: Close < SMA20
    # 2. Momentum Weak: Long Stoch K Falling
    # 3. Confirmation: Mid Stoch K Falling
    # 4. Trigger: Short Stoch Dead Cross > 70 (Failing Rally)
    is_trend_broken = close < sma20
    # [Tightened] Use small threshold
    is_momentum_down = l_k < (prev_l_k - 0.1)
    is_mid_weak = m_k < prev_m_k
    is_dead_cross_high = (prev_s_k > prev_s_d) and (s_k < s_d) and (s_k > 70)
    
    # [New] also allow if ALREADY crossed and still in overbought zone
    is_in_hedge_zone = (s_k < s_d) and (s_k > 65)

    if is_trend_broken and is_momentum_down and is_mid_weak and (is_dead_cross_high or is_in_hedge_zone):
        signals.append("Hedge")

    # ==========================================
    # ★ PRIME (Volume Breakout) - Relaxed
    # ==========================================
    # Condition: 
    # 1. Price Crosses SMA20 Up (Validation of Support)
    # 2. Volume > SMA20 Volume (Demand Confirmation)
    # 3. [Removed] Volume > Prev Volume (Too strict for consolidation breakouts)
    is_crossing_sma20 = (prev_close < prev_sma20) and (close > sma20)
    is_volume_strong = (vol > sma20_vol) 
    
    if is_crossing_sma20 and is_volume_strong:
        signals.append("Prime")

    # ==========================================
    # ★ PHOENIX (Rising from Ashes)
    # ==========================================
    # Logic:
    # 1. Long Term Uptrend: Close > SMA200 (Primary Bull Trend)
    # 2. Deep Pullback: MACD < 0 (Oversold Area)
    # 3. Reversal: MACD > Signal (Golden Cross / Momentum Shift)
    
    # Need SMA200 & MACD first
    sma200 = df['Close'].rolling(200).mean().iloc[-1] if len(df) >= 200 else 0
    
    # MACD (12, 26, 9)
    k = df['Close'].ewm(span=12, adjust=False).mean()
    d = df['Close'].ewm(span=26, adjust=False).mean()
    macd_line = k - d
    macd_signal = macd_line.ewm(span=9, adjust=False).mean()
    
    curr_macd = macd_line.iloc[-1]
    curr_sig = macd_signal.iloc[-1]
    prev_macd = macd_line.iloc[-2]
    prev_sig = macd_signal.iloc[-2]
    
    is_long_uptrend = (close > sma200) if sma200 > 0 else False
    # Deep Pullback: MACD was below 0 during the cross or just before
    is_deep_pullback = (curr_macd < 0) or (prev_macd < 0) 
    
    # Reversal: GOLD CROSS ONLY (Fresh Cross)
    # Check if we just crossed up (Prev: MACD <= Signal, Curr: MACD > Signal)
    is_fresh_cross = (prev_macd <= prev_sig) and (curr_macd > curr_sig)
    
    if is_long_uptrend and is_deep_pullback and is_fresh_cross:
        signals.append("Phoenix")

    # ==========================================
    # ★ SECRET (The Best Combination)
    # ==========================================
    # Logic:
    # 1. Trend Alignment: Short, Mid, Long ALL Upside (Stoch %K > %D)
    # 2. Trigger: MACD Golden Cross (Fresh)
    
    # Stoch Trend Check
    is_short_up = s_k > s_d
    is_mid_up = m_k > (k_mid.rolling(3).mean().iloc[-1]) # Use MA of Stoch for smoother Mid trend
    is_long_up = l_k > l_d

    # Strict Triple Stoch Up
    is_triple_up = (s_k > s_d) and (m_k > k_mid.iloc[-1]) and (l_k > d_long.iloc[-1])
    # Actually let's stick to the simpler K > D for all
    # Re-eval:
    # Short: s_k > s_d
    # Mid: m_k > d_mid (calculated but not assigned to var above, let's assume k_mid, d_mid are series)
    is_mid_up = k_mid.iloc[-1] > d_mid.iloc[-1]
    is_long_up = k_long.iloc[-1] > d_long.iloc[-1]
    
    if is_short_up and is_mid_up and is_long_up and is_fresh_cross:
        signals.append("Secret")

    # ==========================================
    # ★ KUMO (Ichimoku Cloud Spec)
    # ==========================================
    # 1. Tenkan (9)
    high_9 = df['High'].rolling(9).max()
    low_9 = df['Low'].rolling(9).min()
    tenkan = (high_9 + low_9) / 2

    # 2. Kijun (26)
    high_26 = df['High'].rolling(26).max()
    low_26 = df['Low'].rolling(26).min()
    kijun = (high_26 + low_26) / 2

    # 3. Span A (26 ahead) -> Shifted +26
    # Note: For current time comparison, we look at the value projected TO today.
    # Typically Span A[t] = (Tenkan[t-26] + Kijun[t-26]) / 2
    # So we take the unshifted series and access idx -26.
    # OR simpler: df['SpanA'] = ((tenkan + kijun) / 2).shift(26)
    span_a_series = ((tenkan + kijun) / 2).shift(26)
    
    # 4. Span B (52) -> Shifted +26
    high_52 = df['High'].rolling(52).max()
    low_52 = df['Low'].rolling(52).min()
    span_b_series = ((high_52 + low_52) / 2).shift(26)
    
    # 5. Chikou Span (Lagging Span) -> Close shifted -26
    chikou_span = df['Close'].shift(-26)

    # Current Values
    curr_t = tenkan.iloc[-1]
    curr_k = kijun.iloc[-1]
    prev_t = tenkan.iloc[-2]
    prev_k = kijun.iloc[-2]
    
    # Kijun angle check (for uptrend confirmation)
    kijun_5_ago = kijun.iloc[-6] if len(kijun) >= 6 else kijun.iloc[-2]
    
    curr_span_a = span_a_series.iloc[-1]
    curr_span_b = span_b_series.iloc[-1]
    prev_span_a = span_a_series.iloc[-2]
    prev_span_b = span_b_series.iloc[-2]
    
    # Cloud Top/Bottom for current day
    curr_cloud_top = max(curr_span_a, curr_span_b)
    prev_cloud_top = max(prev_span_a, prev_span_b)
    # curr_cloud_bottom = min(curr_span_a, curr_span_b)
    
    # Get volume data for Break filter
    vol = df['Volume'].iloc[-1]
    vol_avg = df['Volume'].rolling(20).mean().iloc[-1] if len(df) >= 20 else vol
    
    # Get RSI for Cross filter
    rsi = df['RSI'].iloc[-1] if 'RSI' in df.columns else 50
    
    # --- A. Kumo Break (REMOVED) ---
    # User requested removal
    pass


    # --- B. Kumo Cross (Aggressive) ---
    # "Tenkan > Kijun (Golden Cross)" - Simple golden cross filter
    is_tk_cross_today = False
    
    if len(tenkan) >= 2:
        prev_t = tenkan.iloc[-2]
        prev_k = kijun.iloc[-2]
        # Golden Cross TODAY: prev Tenkan <= Kijun, curr Tenkan > Kijun
        if prev_t <= prev_k and curr_t > curr_k:
            is_tk_cross_today = True
    
    # Additional filters for Cross
    is_rsi_ok = rsi < 70  # Not overbought
    is_stoch_up = s_k > s_d  # Short stoch confirming uptrend
    
    # [NEW] Chikou Logic: Current Price (Chikou) > Price 26 days ago
    # [NEW] Kijun Logic: Slope >= 0
    is_chikou_ok = False
    is_kijun_slope_ok = False
    
    if len(df) >= 27:
        price_26_ago = df['Close'].iloc[-27]
        if close > price_26_ago:
            is_chikou_ok = True
            
    # Kijun must be Flat or Rising (Not falling)
    is_kijun_slope_ok = (curr_k >= prev_k)

    # [NEW] Volume Surge > 120%
    prev_vol = df['Volume'].iloc[-2] if len(df) >= 2 else vol
    is_vol_surge_cross = vol > (prev_vol * 1.2)

    # [NEW] Weekly Cloud Check (Trend Confirmation)
    is_weekly_ok_cross = False
    try:
        # Quick resampling for weekly check
        df_wk = df.resample('W-FRI').agg({'High':'max', 'Low':'min', 'Close':'last'}).dropna()
        if len(df_wk) >= 52:
            w_h9 = df_wk['High'].rolling(9).max()
            w_l9 = df_wk['Low'].rolling(9).min()
            w_tenkan = (w_h9 + w_l9) / 2
            
            w_h26 = df_wk['High'].rolling(26).max()
            w_l26 = df_wk['Low'].rolling(26).min()
            w_kijun = (w_h26 + w_l26) / 2
            
            w_span_a = ((w_tenkan + w_kijun) / 2).shift(26)
            
            w_h52 = df_wk['High'].rolling(52).max()
            w_l52 = df_wk['Low'].rolling(52).min()
            w_span_b = ((w_h52 + w_l52) / 2).shift(26)
            
            curr_w_close = df_wk['Close'].iloc[-1]
            curr_w_sa = w_span_a.iloc[-1]
            curr_w_sb = w_span_b.iloc[-1]
            
            # Condition: Weekly TK Golden Cross (Alignment)
            is_weekly_ok_cross = w_tenkan > w_kijun
    except Exception:
        is_weekly_ok_cross = True # Pass if fails

    # [Shared] Cross Logic Support
    is_above_cloud_cross = close > curr_span_a and close > curr_span_b

    if is_tk_cross_today and is_rsi_ok and is_stoch_up and is_chikou_ok and is_kijun_slope_ok and is_vol_surge_cross and is_weekly_ok_cross and is_above_cloud_cross:
        pass # signals.append("Kumo Cross") (REMOVED)
    
    # --- C. Kumo Perfect (User Updated) ---
    # 1. Core (Weekly): Price > Weekly Cloud (Prevent Crash)
    # 2. Location: Daily > Cloud & Within 15% (Avoid Overheated)
    # 3. Signal: Tenkan > Kijun (Alignment)
    # 4. Strength: Kijun Flat/Rising + ADX >= 18
    # 5. Volume: > 5-day Avg
    # 6. Confirmation: Chikou > Price & Cloud (at 26 ago)

    # 1. Weekly Cloud Check
    is_weekly_perfect = False
    try:
        # Resample for Weekly Cloud
        df_wk = df.resample('W-FRI').agg({'High':'max', 'Low':'min', 'Close':'last'}).dropna()
        if len(df_wk) >= 52:
            w_h9 = df_wk['High'].rolling(9).max()
            w_l9 = df_wk['Low'].rolling(9).min()
            w_tenkan = (w_h9 + w_l9) / 2
            
            w_h26 = df_wk['High'].rolling(26).max()
            w_l26 = df_wk['Low'].rolling(26).min()
            w_kijun = (w_h26 + w_l26) / 2
            
            w_span_a = ((w_tenkan + w_kijun) / 2).shift(26)
            
            w_h52 = df_wk['High'].rolling(52).max()
            w_l52 = df_wk['Low'].rolling(52).min()
            w_span_b = ((w_h52 + w_l52) / 2).shift(26)
            
            curr_w_close = df_wk['Close'].iloc[-1]
            curr_w_sa = w_span_a.iloc[-1]
            curr_w_sb = w_span_b.iloc[-1]
            w_cloud_top = max(curr_w_sa, curr_w_sb)
            
            # Condition: Weekly Close > Weekly Cloud
            if curr_w_close > w_cloud_top:
                is_weekly_perfect = True
    except:
        is_weekly_perfect = False # Conservative: Fail if no weekly data

    # 2. Daily Location (Above Cloud + Within 15%)
    is_above_cloud = close > curr_span_a and close > curr_span_b
    cloud_top = max(curr_span_a, curr_span_b)
    distance_pct = ((close - cloud_top) / cloud_top * 100) if cloud_top > 0 else 100
    is_within_range = distance_pct <= 15.0

    # 3. Alignment
    is_tk_optimal = curr_t > curr_k # Tenkan > Kijun
    
    # 4. Strength (Kijun Rising/Flat + ADX)
    is_kijun_ok = curr_k >= prev_k
    adx_series = calculate_adx(df)
    curr_adx = adx_series.iloc[-1] if not adx_series.empty else 0
    is_adx_valid = curr_adx >= 18

    # 5. Volume
    vol_5avg = df['Volume'].rolling(5).mean().iloc[-1] if len(df) >= 5 else vol
    is_vol_good = vol >= vol_5avg

    # 6. Chikou Confirmation
    is_chikou_perfect = False
    if len(df) >= 27:
        price_26_ago = df['Close'].iloc[-27]
        sa_26_ago = span_a_series.iloc[-27] if len(span_a_series) >= 27 else 0
        sb_26_ago = span_b_series.iloc[-27] if len(span_b_series) >= 27 else 0
        cloud_26_ago = max(sa_26_ago, sb_26_ago)
        
        if close > price_26_ago and close > cloud_26_ago:
            is_chikou_perfect = True

    if is_weekly_perfect and is_above_cloud and is_within_range and is_tk_optimal and \
       is_kijun_ok and is_adx_valid and is_vol_good and is_chikou_perfect:
        pass # signals.append("Kumo Perfect") (REMOVED)

    # ==========================================
    # 🚀 SHARED ROCKET LOGIC (Used by Gurum)
    # ==========================================
    # 1. Safety (Weekly): Close > Weekly Kijun (Medium-term support alive)
    # 2. Location (Daily): Close > Cloud AND Close > Kijun (Bullish Zone)
    # 3. Alignment: Tenkan > Kijun AND Chikou > Price_26_ago
    # 4. Energy: (Price - Kijun) / Kijun <= 5% (Compressed)
    # 5. Acceleration: Stoch(12,5,5) GC AND K in 20-70
    # 6. Volume: Vol > Prev Vol
    
    # --- 1. Weekly Check ---
    is_weekly_safe = False
    try:
        # Resample for Weekly Kijun
        df_wk = df.resample('W-FRI').agg({'High':'max', 'Low':'min', 'Close':'last'}).dropna()
        if len(df_wk) >= 26:
            w_h26 = df_wk['High'].rolling(26).max()
            w_l26 = df_wk['Low'].rolling(26).min()
            w_kijun = (w_h26 + w_l26) / 2
            curr_w_close = df_wk['Close'].iloc[-1]
            curr_w_kijun = w_kijun.iloc[-1]
            if curr_w_close > curr_w_kijun:
                is_weekly_safe = True
    except:
        is_weekly_safe = True # Fallback

    # --- 2. Daily Location ---
    # Above Cloud (Span A & B) and Above Kijun
    is_daily_loc_strict = (close > curr_span_a) and (close > curr_span_b) and (close > curr_k)
    is_daily_loc_ok = is_daily_loc_strict # Alias for compatibility if needed elsewhere

    # --- 3. Alignment ---
    # Tenkan > Kijun (Bullish TK)
    is_tk_good = curr_t > curr_k
    
    # Chikou > Price 26 days ago
    is_chikou_rocket = False
    if len(df) >= 27:
        price_26_ago = df['Close'].iloc[-27]
        if close > price_26_ago:
            is_chikou_rocket = True

    # --- 4. Energy (Compression) ---
    # Diff within 5%
    is_squeeze = False
    if curr_k > 0:
        diff_pct = abs(close - curr_k) / curr_k
        is_squeeze = diff_pct <= 0.05

    # --- 5. Acceleration (Stoch) ---
    # GC and K in 20-70
    is_accel = False
    if not stoch_k_12.empty and not stoch_d_12.empty:
        curr_k_val = stoch_k_12.iloc[-1]
        curr_d_val = stoch_d_12.iloc[-1]
        prev_k_val = stoch_k_12.iloc[-2] if len(stoch_k_12) >= 2 else 0
        prev_d_val = stoch_d_12.iloc[-2] if len(stoch_d_12) >= 2 else 0
        
        is_gc = (prev_k_val <= prev_d_val) and (curr_k_val > curr_d_val)
        is_range = (20 <= curr_k_val <= 70)
        is_accel = is_gc and is_range

    # --- 6. Volume ---
    prev_vol = df['Volume'].iloc[-2] if len(df) >= 2 else 0
    is_vol_up = vol > prev_vol

    # Combine
    if is_weekly_safe and is_daily_loc_ok and is_tk_good and is_chikou_rocket and \
       is_squeeze and is_accel and is_vol_up:
        pass # signals.append("Kumo Rocket") (REMOVED)
        
    # ==========================================
    # ☁️ GURUM STRATEGIES (Macro-Based)
    # 1. Aggressive (Good Macro): Relaxed Checks, No Weekly Constraints
    # 2. Defensive (Bad Macro): Strict Checks + Weekly Trend Support
    # ==========================================

    # ------------------------------------------
    # 1. GURUM AGGRESSIVE (Good Macro)
    # ------------------------------------------
    
    # [Cross Aggressive]
    # - Daily TK Cross
    # - RSI < 75 (Relaxed)
    # - Vol > 100% Prev (1x)
    # - Kijun Slope >= 0 (Flat or Rising)
    
    is_kijun_flat_or_up = curr_k >= k_short.iloc[-2] # Current Kijun >= Prev Kijun
    is_above_kijun = close > curr_k
    
    if is_tk_cross_today and (rsi < 75) and (vol >= prev_vol) and is_kijun_flat_or_up and is_stoch_up:
        signals.append("Gurum Cross Aggressive")

    # [Rocket Aggressive]
    # - Price > Daily Cloud & Kijun
    # - Squeeze <= 10%
    # - Stoch Rising (limit 85)
    # - Alignment: T > K, Chikou > Price-26
    # - Vol > 5Day Avg OR Vol > Prev
    
    # Re-calc specific conditions locally if needed
    is_squeeze_10 = False
    if curr_k > 0:
        is_squeeze_10 = (abs(close - curr_k) / curr_k) <= 0.10
        
    is_rocket_stoch_85 = False
    if not stoch_k_12.empty:
         ck = stoch_k_12.iloc[-1]
         # Rising or GC check reused `is_stoch_up` or custom
         # Spec: "Stoch rising section allowed up to 85"
         if (ck <= 85) and is_stoch_up:
             is_rocket_stoch_85 = True

    is_vol_rocket_cond = (vol >= vol_5avg) or (vol > prev_vol)
    
    if is_above_cloud and is_above_kijun and is_squeeze_10 and is_rocket_stoch_85 and \
       is_tk_good and is_chikou_rocket and is_vol_rocket_cond:
        signals.append("Gurum Rocket Aggressive")

    # [Perfect Aggressive]
    # - Price > Daily Cloud + Within 0-15% (TIGHTENED from 25%)
    # - ADX >= 20 (INCREASED from 15)
    # - Tenkan > Kijun (Alignment)
    # - Chikou > Price
    # - Volume >= 5-day Average (NEW)
    
    # [FIX] Use cloud-based distance instead of Kijun-based
    if cloud_top > 0:
        squeeze_from_cloud = ((close - cloud_top) / cloud_top)
        is_within_perfect_zone = (0.00 <= squeeze_from_cloud <= 0.15)  # 0-15% above cloud
    else:
        is_within_perfect_zone = False
    
    if is_above_cloud and is_within_perfect_zone and (curr_adx >= 20) and is_tk_good and is_chikou_rocket and is_vol_good:
         signals.append("Gurum Perfect Aggressive")

    # ------------------------------------------
    # 2. GURUM DEFENSIVE (Bad Macro)
    # ------------------------------------------
    # Re-calc Weekly Support metrics first
    
    is_w_above_cloud = False
    is_w_above_kijun = False
    
    try:
        # We need weekly data
        df_wk_g = df.resample('W-FRI').agg({'High':'max', 'Low':'min', 'Close':'last'}).dropna()
        if len(df_wk_g) >= 52:
            wh9 = df_wk_g['High'].rolling(9).max()
            wl9 = df_wk_g['Low'].rolling(9).min()
            wt = (wh9 + wl9) / 2
            
            wh26 = df_wk_g['High'].rolling(26).max()
            wl26 = df_wk_g['Low'].rolling(26).min()
            wk = (wh26 + wl26) / 2
            
            # W-Cloud Top (Span A vs Span B shifted forward 26 - but here we check CURRENT price vs Cloud at current time? 
            # Cloud is projected 26 periods ahead. The cloud under the price TODAY is based on data from 26 periods ago.
            # Standard Ichimoku check: Close(t) > Cloud(t).
            # Cloud(t) = SpanA(t-26) and SpanB(t-26).
            # So we shift(26) the spans to match future alignment, then lookup at current index?
            # Actually easier: SpanA calculated today is projected to t+26.
            # The SpanA at `t` was calculated at `t-26`.
            w_sa_val = ((wt + wk)/2).shift(26).iloc[-1]
            
            wh52 = df_wk_g['High'].rolling(52).max()
            wl52 = df_wk_g['Low'].rolling(52).min()
            w_sb_val = ((wh52 + wl52)/2).shift(26).iloc[-1]
            
            w_cloud_top = max(w_sa_val, w_sb_val)
            w_close = df_wk_g['Close'].iloc[-1]
            
            if w_close > w_cloud_top:
                is_w_above_cloud = True
            if w_close > wk.iloc[-1]:
                is_w_above_kijun = True
                
    except:
        # Fallback if not enough data
        pass

    # [Cross Defensive]
    # - Daily TK Cross
    # - RSI < 70
    # - Vol > 120% Prev
    # - Weekly Price > Weekly Cloud
    # - Chikou > Price-26
    
    is_vol_surge_120 = vol >= (prev_vol * 1.2)
    
    if is_tk_cross_today and (rsi < 70) and is_vol_surge_120 and is_w_above_cloud and is_chikou_rocket:
        signals.append("Gurum Cross Defensive")

    # [Rocket Defensive]
    # - Squeeze <= 5%
    # - Stoch Rising (limit 70)
    # - Weekly Price > Weekly Kijun
    # - Price > Cloud & Kijun
    # - Alignment (T>K, Chikou>P)
    
    is_squeeze_5 = False
    if curr_k > 0:
        is_squeeze_5 = (abs(close - curr_k) / curr_k) <= 0.05

    is_rocket_stoch_70 = False
    if not stoch_k_12.empty:
         ck = stoch_k_12.iloc[-1]
         if (ck <= 70) and is_stoch_up:
             is_rocket_stoch_70 = True
             
    if is_above_cloud and is_above_kijun and is_squeeze_5 and is_rocket_stoch_70 and \
       is_tk_good and is_chikou_rocket and is_w_above_kijun:
        signals.append("Gurum Rocket Defensive")

    # [Perfect Defensive]
    # - Squeeze <= 10% (TIGHTENED from 15%)
    # - ADX >= 20 (INCREASED from 18)
    # - Weekly Price > Weekly Cloud
    # - Alignment (T>K, GC recent)
    # - Chikou > Price & Cloud (Full Breakout)
    
    # [FIX] Use cloud-based distance instead of Kijun-based
    if cloud_top > 0:
        squeeze_from_cloud_def = ((close - cloud_top) / cloud_top)
        is_within_perfect_zone_def = (0.00 <= squeeze_from_cloud_def <= 0.10)  # 0-10% above cloud (stricter)
    else:
        is_within_perfect_zone_def = False
    
    # Chikou > Price AND Cloud on Daily?
    # Spec: "Chikou > Price AND Gurum completely". 
    # Current `is_chikou_perfect` usually checks Chikou > Price.
    # We will assume `is_chikou_rocket` (Price > Price26) is the proxy for Chikou > Price.
    # Cloud check for Chikou is tricky without lookup. Let's trust `is_chikou_perfect` logic if it exists, or just ensure Price > Cloud (which implies Chikou likely above if trend is strong).
    # Let's align with "Weekly Price > Cloud" which makes it safe.
    
    # GC recent check (1-7 days)
    # We can check K_short > D_short and check if cross happened recently.
    # Simply checking `is_tk_good` (T>K) is good baseline.
    
    if is_w_above_cloud and is_within_perfect_zone_def and (curr_adx >= 20) and is_tk_good and is_chikou_rocket:
         signals.append("Gurum Perfect Defensive")

    # ==========================================
    # 🏅 ZENITH (Best of Best) - [Requires Other Signals + All Green]
    # ==========================================
    # Logic: Award Zenith ONLY if:
    # 1. Stock already has at least one other strategy signal
    # 2. AND all 5 technical indicators are green:
    #    - Bollinger: Inside Upper Band (Not Overheated)
    #    - RSI: Bullish but Safe (45 <= RSI < 70)
    #    - MACD: Bullish Trend (> Signal)
    #    - Stochastic: Not Overheated (< 80)
    #    - Ichimoku: Full Bullish Alignment (Above Cloud, Tenkan > Kijun, Chikou > Price)
    
    # First check if we have any other signals
    has_other_signals = len(signals) > 0
    
    if has_other_signals:
        # Now check all 5 green conditions
        # 1. Bollinger Calculation
        std20 = df['Close'].rolling(20).std()
        upper_band = df['SMA20'] + (2 * std20)
        curr_upper = upper_band.iloc[-1]
        
        # Zenith Checks
        is_bollinger_green = close <= curr_upper
        is_rsi_green = 45 <= rsi < 70
        is_macd_green = curr_macd > curr_sig
        
        # Stoch using 12,5,5 (Slow)
        curr_slow_k = stoch_k_12.iloc[-1] if not stoch_k_12.empty else 50
        is_stoch_green = curr_slow_k < 80
        
        # Ichimoku Alignment
        # is_tk_good (T>K), is_chikou_rocket (Close > Price26), is_above_cloud (Close > SpanA & SpanB)
        is_ichimoku_green = is_above_cloud and is_tk_good and is_chikou_rocket

        if is_bollinger_green and is_rsi_green and is_macd_green and is_stoch_green and is_ichimoku_green:
            signals.append("Zenith")

    return list(set(signals))


def fetch_fmp_news(symbols):
    """
    Fetch news from FMP for a list of symbols.
    Filter for Today and Yesterday only.
    """
    import requests
    from django.conf import settings
    
    if not symbols:
        return {}
        
    api_key = getattr(settings, 'FMP_API_KEY', None)
    if not api_key:
        return {}
        
    # Chunking symbols to avoid URL length issues (though 50 is usually fine)
    # FMP supports comma separation
    s_str = ",".join(symbols)
    url = f"https://financialmodelingprep.com/stable/news/stock?symbols={s_str}&apikey={api_key}"
    
    news_map = {s: [] for s in symbols}
    
    try:
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            
            today = timezone.now().date()
            yesterday = today - timedelta(days=1)
            
            for item in data:
                # publishedDate: "2023-10-25 14:30:00"
                pub_str = item.get('publishedDate')
                if not pub_str: continue
                
                try:
                    # Parse date
                    pub_dt = datetime.strptime(pub_str, "%Y-%m-%d %H:%M:%S").date()
                except:
                    continue
                    
                # Filter: Today or Yesterday
                if pub_dt == today or pub_dt == yesterday:
                   sym = item.get('symbol')
                   # Data might contain symbols we didn't ask for (related), but usually matches.
                   if sym in news_map:
                       news_map[sym].append({
                           'title': item.get('title'),
                           'image': item.get('image'),
                           'site': item.get('site'),
                           'text': item.get('text'),
                           'url': item.get('url'),
                           'date': pub_str
                       })
    except Exception as e:
        print(f"FMP News Fetch Error: {e}")
        
    return news_map


def vestiq_pick_view(request):
    """
    [Vestiq Pick 2.0]
    Tabs: Intraday (1H) vs Daily (Strategy)
    Includes Advanced Macro Sentiment Integration.
    """
    # --- Theme Definitions (Global for this view) ---
    QUANTUM_THEME = ['IONQ', 'RGTI', 'QBTS', 'QUBT', 'IBM', 'GOOGL']
    AEROSPACE_THEME = ['LMT', 'RTX', 'NOC', 'GD', 'BA', 'HII', 'LHX', 'PLTR', 'AXON', 'KTOS', 'AVAV', 'RKLB']
    CLEAN_ENERGY_THEME = ['TSLA', 'RIVN', 'LCID', 'FSLR', 'ENPH', 'SEDG', 'RUN', 'PLUG']
    AI_THEME = ['NVDA', 'AMD', 'SMCI', 'AVGO', 'MSFT', 'GOOGL', 'META']
    ROBOTICS_THEME = ['ISRG', 'PATH', 'TDY', 'ROK']
    CYBERSECURITY_THEME = ['PANW', 'CRWD', 'FTNT', 'ZS', 'OKTA', 'NET']
    BITCOIN_THEME = ['COIN', 'MSTR', 'MARA', 'RIOT', 'CLSK']
    NEO_CLOUD_THEME = ['SNOW', 'MDB', 'DDOG', 'CFLT']

    from updatedata.models import Ticker, PriceHistory
    from scanner.models import ScanBatch, ScanRow, DailyPick
    from datetime import datetime
    import fear_and_greed
    import yfinance as yf
    import pandas as pd
    
    symbol_req = request.GET.get("symbol")
    
    # 1. Date Handling
    date_str = request.GET.get("date")
    today = timezone.now().date()
    
    if date_str:
        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            target_date = today
    else:
        target_date = today
    
    # [Fix] Always fall back to last available trading day if selected date has no data
    # This handles weekends, holidays, and future dates gracefully for ALL cases
    last_pick = DailyPick.objects.filter(date__lte=target_date).order_by('-date').first()
    if last_pick and last_pick.date != target_date:
        # No data for target_date, use last available date on or before target
        target_date = last_pick.date
    elif not last_pick:
        # No historical data at all (or future date beyond all data), try to get the most recent
        last_pick = DailyPick.objects.order_by('-date').first()
        if last_pick:
            target_date = last_pick.date

    # ----------------------------------------------------
    # 2. Advanced Macro Sentiment Calculation
    # ----------------------------------------------------
    # ... (Keep existing Macro Logic) ...
    # (Simplified for brevity in view file edit, assuming code around this tool call preserves it if I don't touch it. 
    # But wait, replace_file_content replaces chunks. I must be careful not to delete the Macro Logic if I am not viewing it.
    # The previous view showed lines 849-1000.  The macro logic is INSIDE vestiq_pick_view.
    # I am editing calculate_vestiq_strategies AND vestiq_pick_view.
    # I should use MULTI_REPLACE or be very careful.
    
    # Actually, I'll just edit calculate_vestiq_strategies first, then edit vestiq_pick_view to remove HPE.
    # Let's do calculate_vestiq_strategies first.
    
    # ----------------------------------------------------
    # 2. Advanced Macro Sentiment Calculation
    # ----------------------------------------------------
    # Factors & Weights:
    # 1. Retail Sentiment (Fear & Greed): 35%
    # 2. Market Internal (VIX): 20%
    # 3. Momentum (S&P 500 RSI): 15%
    # 4. Risk Appetite (Bitcoin): 15% (New)
    # 5. Macro Stress (Yields + Dollar + Oil): 15% (New)
    
    current_language = get_language()
    
    try:
        # A. Fetch Fear & Greed (0-100)
        fg_data = fear_and_greed.get()
        fg_score = float(fg_data.value)
        fg_label = fg_data.description
    except:
        fg_score = 50
        fg_label = "Neutral"

    try:
        # B. Fetch Macro Data (Batch)
        # ^GSPC (S&P500), ^VIX (Volatility), ^TNX (10Y Yield), DX-Y.NYB (Dollar)
        # BTC-USD (Bitcoin), CL=F (Crude Oil)
        macro_tickers = ['^GSPC', '^VIX', '^TNX', 'DX-Y.NYB', 'BTC-USD', 'CL=F']
        df_macro = yf.download(macro_tickers, period="60d", progress=False, auto_adjust=True)['Close']
        
        # Latest Values
        spx = df_macro['^GSPC'].iloc[-1]
        vix = df_macro['^VIX'].iloc[-1]
        tnx = df_macro['^TNX'].iloc[-1]
        dxy = df_macro['DX-Y.NYB'].iloc[-1]
        btc = df_macro['BTC-USD'].iloc[-1]
        oil = df_macro['CL=F'].iloc[-1]
        

        # --- C. Normalize Scores to 0-100 Scale (0=Extreme Fear, 100=Extreme Greed) ---
        
        # 1. VIX Score (Inverse: Higher VIX = Fear/Lower Score)
        # Range assumption: VIX 10 (Greed) to VIX 35 (Fear)
        vix_score = 100 - ((vix - 10) / (35 - 10) * 100)
        vix_score = max(0, min(100, vix_score))
        
        # 2. Momentum Score (S&P 500 RSI 14)
        delta = df_macro['^GSPC'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        spx_rsi_series = 100 - (100 / (1 + rs))
        spx_rsi = spx_rsi_series.iloc[-1]
        mom_score = spx_rsi

        # 3. Risk Appetite (Bitcoin RSI)
        delta_btc = df_macro['BTC-USD'].diff()
        gain_btc = (delta_btc.where(delta_btc > 0, 0)).rolling(14).mean()
        loss_btc = (-delta_btc.where(delta_btc < 0, 0)).rolling(14).mean()
        rs_btc = gain_btc / loss_btc
        btc_rsi = 100 - (100 / (1 + rs_btc))
        btc_score = btc_rsi.iloc[-1]
        
        # 4. Macro Stress Score (Inverse: High Yield/Dollar/Oil = Fear)
        # TNX > 4.5% is Stress. DXY > 106 is Stress. Oil > 90 is Stress.
        tnx_score = 100 - ((tnx - 3.5) / (5.0 - 3.5) * 100)
        dxy_score = 100 - ((dxy - 100) / (110 - 100) * 100)
        oil_score = 100 - ((oil - 65) / (90 - 65) * 100) # 65=Cheap(Greed), 90=Expensive(Fear)
        
        avg_stress = (tnx_score + dxy_score + oil_score) / 3
        macro_stress_score = max(0, min(100, avg_stress))
        
        # Helper to calculate contribution
        c1 = int(round(fg_score * 0.35))
        c2 = int(round(vix_score * 0.20))
        c3 = int(round(mom_score * 0.15))
        c4 = int(round(btc_score * 0.15))
        
        # Calculate Total first
        final_score = (fg_score * 0.35) + (vix_score * 0.20) + (mom_score * 0.15) + (btc_score * 0.15) + (macro_stress_score * 0.15)
        sentiment_score = int(round(final_score))
        
        # Adjust last contribution to force sum equality
        c5 = sentiment_score - (c1 + c2 + c3 + c4)
        
        # Breakdown Translation Logic
        if current_language == 'ko':
            formula_breakdown = [
                {'name': '시장심리 (Fear & Greed)', 'val': int(fg_score), 'w': '35%', 'contrib': c1},
                {'name': '변동성 (VIX)', 'val': int(vix_score), 'w': '20%', 'contrib': c2},
                {'name': '모멘텀 (S&P 500)', 'val': int(mom_score), 'w': '15%', 'contrib': c3},
                {'name': '위험선호 (Bitcoin)', 'val': int(btc_score), 'w': '15%', 'contrib': c4},
                {'name': '거시경제 (금리/유가/달러)', 'val': int(macro_stress_score), 'w': '15%', 'contrib': c5},
            ]
        else:
            formula_breakdown = [
                {'name': 'Fear & Greed', 'val': int(fg_score), 'w': '35%', 'contrib': c1},
                {'name': 'Volatility (VIX)', 'val': int(vix_score), 'w': '20%', 'contrib': c2},
                {'name': 'Momentum (S&P 500)', 'val': int(mom_score), 'w': '15%', 'contrib': c3},
                {'name': 'Risk Appetite (Bitcoin)', 'val': int(btc_score), 'w': '15%', 'contrib': c4},
                {'name': 'Macro Stress (Rates/Oil)', 'val': int(macro_stress_score), 'w': '15%', 'contrib': c5},
            ]
        
    except Exception as e:
        print(f"Error calculating macro sentiment: {e}")
        messages.warning(request, "실시간 시장 지표를 가져오는데 실패했습니다. 새로고침 하거나 5~10초 뒤에 다시 시도해주세요.")
        sentiment_score = int(fg_score)
        formula_breakdown = [{'name': 'Fear & Greed (Fallback)', 'val': int(fg_score), 'w': '100%', 'contrib': int(fg_score)}]

    # Redefine Sentiment Label based on Composite Score
    if sentiment_score < 25: sentiment_label = "Extreme Fear"
    elif sentiment_score < 45: sentiment_label = "Fear"
    elif sentiment_score < 55: sentiment_label = "Neutral"
    elif sentiment_score < 75: sentiment_label = "Greed"
    else: sentiment_label = "Extreme Greed"

    # Define Macro Stance (Contrarian)
    if sentiment_score < 25:
        if current_language == 'ko':
            macro_stance = {"text": "공격적 매수 (Aggressive Buy)", "color": "#22c55e", "icon": "bi-lightning-charge-fill", "desc": "극도의 공포: 과매도 구간, 강한 반등 예상"}
        else:
            macro_stance = {"text": "Aggressive Buy", "color": "#22c55e", "icon": "bi-lightning-charge-fill", "desc": "Extreme Fear: Oversold Bounce Likely"}
    elif sentiment_score < 45:
        if current_language == 'ko':
            macro_stance = {"text": "매수/비중확대 (Buy)", "color": "#4ade80", "icon": "bi-basket-fill", "desc": "공포 구간: 저점 매집의 기회 (Good Entry)"}
        else:
            macro_stance = {"text": "Buy (Accumulate)", "color": "#4ade80", "icon": "bi-basket-fill", "desc": "Fear: Good Entry Zone"}
    elif sentiment_score <= 55:
        if current_language == 'ko':
            macro_stance = {"text": "중립/관망 (Neutral)", "color": "#94a3b8", "icon": "bi-pause-circle-fill", "desc": "방향성 탐색 구간 (Indecisive)"}
        else:
            macro_stance = {"text": "Neutral / Hold", "color": "#94a3b8", "icon": "bi-pause-circle-fill", "desc": "Market Indecisive"}
    elif sentiment_score < 75:
        if current_language == 'ko':
            macro_stance = {"text": "주의/수익실현 (Caution)", "color": "#facc15", "icon": "bi-exclamation-triangle-fill", "desc": "탐욕 구간: 리스크 관리 및 분할 매도"}
        else:
            macro_stance = {"text": "Caution / Profit", "color": "#facc15", "icon": "bi-exclamation-triangle-fill", "desc": "Greed: Risk Elevation"}
    else:
        if current_language == 'ko':
            macro_stance = {"text": "매수 금지 (Avoid)", "color": "#ef4444", "icon": "bi-shield-slash-fill", "desc": "극도의 탐욕: 조정 가능성 높음"}
        else:
            macro_stance = {"text": "Avoid / Defensive", "color": "#ef4444", "icon": "bi-shield-slash-fill", "desc": "Extreme Greed: Correction Risk High"}

    context = {
        "page_title": "Vestiq Pick",
        "target_date": target_date.strftime("%Y-%m-%d"),
        "sentiment_score": sentiment_score,
        "sentiment_label": sentiment_label,
        "macro_stance": macro_stance,
        "formula_breakdown": formula_breakdown,
        "language": current_language,
    }

    picks = []
    
    saved_picks = DailyPick.objects.filter(date=target_date)
    
    if saved_picks.exists():
        s_symbols = [p.symbol for p in saved_picks]
        
        # Fetch history to calc day's change (Only need prev day + target day)
        # [OPTIMIZED] Reduced from 120 days to 5 (buffer for weekends) since trends are cached
        ph_qs = PriceHistory.objects.filter(
            symbol__symbol__in=s_symbols,
            date__lte=target_date,
            date__gte=target_date - timedelta(days=40)  # Fetched 40 days for AvgVol(20) calculation
        ).order_by('symbol__symbol', 'date')
        
        ph_map = {}
        for ph in ph_qs:
            s_ = ph.symbol.symbol
            if s_ not in ph_map: ph_map[s_] = []
            ph_map[s_].append(ph)
            
        for p in saved_picks:
            hist = ph_map.get(p.symbol, [])
            
            # Determine Current Price (on target_date)
            # If p.price is stored, use it. Else find close on target_date.
            curr_price = p.price
            curr_vol = 0
            
            # Find exact date match in hist for volume/close fallback
            match = [h for h in hist if h.date == target_date]
            if match:
                if not curr_price: curr_price = match[0].close
                curr_vol = match[0].volume
                # [FIX] Use stored change_percent from PriceHistory (already stored as percentage)
                if match[0].change_percent is not None:
                    change_pct = match[0].change_percent  # Already a percentage value
                else:
                    change_pct = 0.0
                # [FIX] Use stored volume_percent from PriceHistory (already stored as percentage)
                if match[0].volume_percent is not None:
                    vol_change = match[0].volume_percent  # Already a percentage value
                else:
                    vol_change = 0.0
            elif hist:
                # Fallback to latest available in window (even if curr_price exists from p.price)
                if not curr_price: curr_price = hist[-1].close
                if curr_vol == 0: curr_vol = hist[-1].volume
                # Use the latest available change_percent (already stored as percentage)
                if hist[-1].change_percent is not None:
                    change_pct = hist[-1].change_percent  # Already a percentage value
                else:
                    change_pct = 0.0
                if hist[-1].volume_percent is not None:
                    vol_change = hist[-1].volume_percent  # Already a percentage value
                else:
                    vol_change = 0.0
            else:
                change_pct = 0.0
                vol_change = 0.0

            if not curr_price: curr_price = 0

                
            # Avg Volume (20)
            avg_volume = 0
            if len(hist) >= 20:
                avg_volume = sum([h.volume for h in hist[-20:]]) / 20
            elif len(hist) > 0:
                avg_volume = sum([h.volume for h in hist]) / len(hist)
                
            p_name = p.symbol
            try:
                t_obj = Ticker.objects.filter(symbol=p.symbol).first()
                if t_obj: p_name = t_obj.name
            except:
                pass

            # --- Trend Analysis (Stochastics) ---
            # [OPTIMIZED] Use cached trends from PriceHistory instead of recalculating
            long_trend = "Neutral"
            mid_trend = "Neutral"
            
            # Try to get cached trend data for this date
            target_ph = [h for h in hist if h.date == target_date and h.vestiq_scan]
            if target_ph:
                # Use cached values
                long_trend = target_ph[0].stoch_long_trend or "Neutral"
                mid_trend = target_ph[0].stoch_mid_trend or "Neutral"
            elif len(hist) > 50:
                # Fallback: Calculate if not cached (for old data or edge cases)
                h_data = [{'Open': h.open, 'High': h.high, 'Low': h.low, 'Close': h.close} for h in hist]
                df_h = pd.DataFrame(h_data)
                
                try:
                    # Long Stoch (20, 12, 12)
                    lk, ld = calculate_stoch_slow(df_h, 20, 12, 12)
                    if not lk.empty and not ld.empty:
                        if pd.isna(lk.iloc[-1]) or pd.isna(ld.iloc[-1]):
                            long_trend = "Neutral"
                        else:
                            long_trend = "Up" if lk.iloc[-1] > ld.iloc[-1] else "Down"
                        
                    # Mid Stoch (10, 6, 6)
                    mk, md = calculate_stoch_slow(df_h, 10, 6, 6)
                    if not mk.empty and not md.empty:
                        if pd.isna(mk.iloc[-1]) or pd.isna(md.iloc[-1]):
                            mid_trend = "Neutral"
                        else:
                            mid_trend = "Up" if mk.iloc[-1] > md.iloc[-1] else "Down"
                except Exception as e:
                    print(f"Stoch Calc Error {p.symbol}: {e}")

            # --- Secret Sauce Check (Historical) ---
            is_secret = False
            strat_list = p.strategy.split(", ")
            
            # [New Logic] Trust the Strategy Label directly
            if 'Secret' in strat_list:
                is_secret = True
            
            # [Legacy Fallback] - If data was saved before 'Secret' existed in DB
            # 1. Alpha Best
            if not is_secret and any('Alpha' in s for s in strat_list) and long_trend == "Up" and mid_trend != "Up":
                # is_secret = True # Disable Legacy override for now to emphasize new strict logic
                pass
            # 2. Prime Best
            if not is_secret and any('Prime' in s for s in strat_list) and long_trend == "Up" and mid_trend == "Up":
                # is_secret = True
                pass

            
            # [Custom Themes] Detect Themes (Do NOT override primary sector yet)
            themes = []
            
            # Use Global Theme Definitions defined at top of view
            sym_clean = p.symbol.strip().upper()

            # Check Themes
            if sym_clean in QUANTUM_THEME: themes.append("Quantum")
            if sym_clean in AEROSPACE_THEME: themes.append("Aerospace & Defense")
            if sym_clean in CLEAN_ENERGY_THEME: themes.append("Clean Energy & EV")
            if sym_clean in AI_THEME: themes.append("Artificial Intelligence")
            if sym_clean in ROBOTICS_THEME: themes.append("Robotics")
            if sym_clean in CYBERSECURITY_THEME: themes.append("Cybersecurity")
            if sym_clean in BITCOIN_THEME: themes.append("Bitcoin & Crypto")
            if sym_clean in NEO_CLOUD_THEME: themes.append("Neo Cloud")
            
            # [DEBUG] Log ALL stocks with themes
            if themes:
                print(f"🎯 [THEME DEBUG Historical] {sym_clean}: Sector='{sector}', Themes={themes}")

            # Get Primary Sector (GICS)
            # Default to Ticker.sector. If not found, "Unknown".
            # We NO LONGER override this with the theme.
            sector = "Unknown"
            try:
                t_obj = Ticker.objects.filter(symbol=p.symbol).first()
                if t_obj and t_obj.sector:
                    sector = t_obj.sector
            except:
                pass
            
            picks.append({
                'symbol': p.symbol,
                'name': p_name,
                'sector': sector,
                'themes': themes,
                'price': curr_price,
                'change': round(change_pct, 2),
                'vol_change': round(vol_change, 1),
                'avg_volume': format_volume(avg_volume),
                'avg_volume_num': avg_volume, # For sorting
                'strategies': strat_list,
                'volume': curr_vol,
                'comment': p.reason or "",
                'long_trend': long_trend,
                'mid_trend': mid_trend,
                'is_secret': is_secret,
                'is_zenith': 'Zenith' in strat_list
            })
    elif target_date == today:
        # A. Define Universe (Scan ALL results from latest batch)
        # User requested: "No market cap limit, fetch all"
        batch = ScanBatch.objects.order_by("-started_at").first()
        if batch:
            # Get ALL symbols from the batch (could be 1000+)
            all_symbols = list(ScanRow.objects.filter(batch=batch).values_list('symbol', flat=True))
        else:
            all_symbols = ['AAPL', 'TSLA', 'NVDA', 'AMD', 'MSFT']
            
        # Optimization: Process in Chunks to avoid SQL overload
        CHUNK_SIZE = 100
        
        # Pre-fetch Ticker info map for name lookup (one query for all is fine usually, or chunk it too if massive)
        # 2000 tickers for name/sector is relatively light for Django.
        ticker_map = {t.symbol: t for t in Ticker.objects.filter(symbol__in=all_symbols)}
        
        for i in range(0, len(all_symbols), CHUNK_SIZE):
            chunk_symbols = all_symbols[i:i + CHUNK_SIZE]
            
            # B. Fetch History for Chunk
            # Need ~400 days for SMA120/Algo stability? 
            # calculate_vestiq_strategies checks len < 120. 
            # Use 200 days safely.
            cutoff = today - timedelta(days=250)
            
            all_prices = PriceHistory.objects.filter(
                symbol__symbol__in=chunk_symbols, 
                date__gte=cutoff
            ).order_by('symbol__symbol', 'date')
            
            if not all_prices.exists():
                continue

            # Convert to DataFrame
            # Values list is efficient
            data = list(all_prices.values('symbol__symbol', 'date', 'open', 'high', 'low', 'close', 'volume', 'volume_percent', 'change_percent'))
            if not data: continue
            
            df_chunk = pd.DataFrame(data)
            df_chunk.rename(columns={'symbol__symbol': 'Symbol', 'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'volume': 'Volume', 'volume_percent': 'Vol_Pct', 'change_percent': 'Change_Pct'}, inplace=True)
            df_chunk['date'] = pd.to_datetime(df_chunk['date'])
            
            grouped = df_chunk.groupby('Symbol')
            
            for sym, group in grouped:
                group = group.sort_values('date')
                if len(group) < 120: continue # Min constraint from calc function
                
                signals = calculate_vestiq_strategies(group)
                
                if signals:
                    # --- FUNDAMENTAL CHECK ---
                    # Keep existing logic: check profitability if Ticker exists
                    is_fund_ok = False
                    try:
                        t_obj = ticker_map.get(sym)
                        if t_obj:
                            # We can't easily access latest fundamentals efficiently without n+1 in this structure
                            # unless we pre-fetch fundamentals. 
                            # For now, let's look up only if signal exists (rare event).
                            fd = t_obj.fundamentals.order_by('-date').first()
                            if fd:
                                ey = fd.earnings_yield or 0
                                roe = fd.return_on_equity or 0
                                if ey > 0 or roe > 0: is_fund_ok = True
                                else: is_fund_ok = False
                            else: is_fund_ok = True
                        else: is_fund_ok = True
                    except:
                        is_fund_ok = True

                    if not is_fund_ok: continue
                    # -------------------------

                    last_row = group.iloc[-1]
                    price = last_row['Close']
                    strat_name = ", ".join(signals)
                    
                    DailyPick.objects.get_or_create(
                        date=today, 
                        symbol=sym, 
                        defaults={'strategy': strat_name, 'price': price}
                    )
                    
                    # Calc Changes
                    change_pct = 0.0
                    vol_change = 0.0
                    if len(group) >= 2:
                        # [Fix] Use Stored Change Pct if available (Accurate for holidays/weekends)
                        if 'Change_Pct' in last_row and pd.notna(last_row['Change_Pct']):
                             change_pct = last_row['Change_Pct']
                        else:
                             prev_close = group.iloc[-2]['Close']
                             if prev_close > 0:
                                 change_pct = ((price - prev_close) / prev_close) * 100
                        
                        if 'Vol_Pct' in last_row and pd.notna(last_row['Vol_Pct']):
                             vol_change = last_row['Vol_Pct']
                        else:
                             prev_vol = group.iloc[-2]['Volume']
                             curr_vol = last_row['Volume']
                             if prev_vol > 0:
                                 vol_change = ((curr_vol - prev_vol) / prev_vol) * 100

                    p_name = sym
                    t_obj = ticker_map.get(sym)
                    if t_obj: p_name = t_obj.name
                    
                    # Live Trend Analysis
                    long_trend = "Neutral"
                    mid_trend = "Neutral"
                    try:
                        lk, ld = calculate_stoch_slow(group, 20, 12, 12)
                        mk, md = calculate_stoch_slow(group, 10, 6, 6)
                        if not lk.empty and not pd.isna(lk.iloc[-1]):
                             long_trend = "Up" if lk.iloc[-1] > ld.iloc[-1] else "Down"
                        if not mk.empty and not pd.isna(mk.iloc[-1]):
                             mid_trend = "Up" if mk.iloc[-1] > md.iloc[-1] else "Down"
                    except: pass
                    
                    # Secret Sauce
                    is_secret = False
                    if 'Secret' in signals: is_secret = True
                    # if any('Alpha' in s for s in signals) and long_trend == "Up" and mid_trend != "Up": is_secret = True
                    # if any('Prime' in s for s in signals) and long_trend == "Up" and mid_trend == "Up": is_secret = True
                    
                    # Get sector
                    sector = t_obj.sector if t_obj and t_obj.sector else "Unknown"

                    # [Custom Themes] Detect Themes (Live Branch)
                    themes = []
                    # Use Global Theme Definitions
                    sym_clean = sym.strip().upper() 

                    if sym_clean in QUANTUM_THEME: themes.append("Quantum")
                    if sym_clean in AEROSPACE_THEME: themes.append("Aerospace & Defense")
                    if sym_clean in CLEAN_ENERGY_THEME: themes.append("Clean Energy & EV")
                    if sym_clean in AI_THEME: themes.append("Artificial Intelligence")
                    if sym_clean in ROBOTICS_THEME: themes.append("Robotics")
                    if sym_clean in CYBERSECURITY_THEME: themes.append("Cybersecurity")
                    if sym_clean in BITCOIN_THEME: themes.append("Bitcoin & Crypto")
                    if sym_clean in NEO_CLOUD_THEME: themes.append("Neo Cloud")
                    
                    # [DEBUG] Log ALL stocks with themes
                    if themes:
                        print(f"🎯 [THEME DEBUG Live] {sym_clean}: Sector='{sector}', Themes={themes}")
                    
                    avg_vol_val = group['Volume'].tail(20).mean()
                    
                    picks.append({
                        'symbol': sym,
                        'name': p_name,
                        'sector': sector,
                        'themes': themes,
                        'price': price,
                        'change': round(change_pct, 2),
                        'vol_change': round(vol_change, 1),
                        'avg_volume': format_volume(avg_vol_val),
                        'avg_volume_num': avg_vol_val, # For sorting
                        'strategies': signals,
                        'volume': last_row['Volume'],
                        'comment': get_kim_comment(group),
                        'long_trend': long_trend,
                        'mid_trend': mid_trend,
                        'is_secret': is_secret,
                        'is_zenith': 'Zenith' in signals
                    })

    # Calculate Leading Sectors (2-week trend) from SectorPerformance History
    # User Request: Use 2-week trend instead of just today's picks
    # IMPORTANT: Use latest available SectorPerformance date, not today, to stay in sync with Sector Leaders page
    leading_sectors = []
    
    try:
        # 1. Get the latest available SectorPerformance date (most recent trading day)
        latest_sector_data = SectorPerformance.objects.order_by('-date').first()
        
        if latest_sector_data:
            latest_date = latest_sector_data.date
            start_date = latest_date - timedelta(days=14)
            
            perf_qs = SectorPerformance.objects.filter(
                date__gte=start_date, 
                date__lte=latest_date
            ).values('sector', 'change_percent')
            
            # print(f"🔍 [DEBUG] Leading Sectors Query: {start_date} to {latest_date}")
            
            if perf_qs.exists():
                from collections import defaultdict
                sector_scores = defaultdict(float)
                
                for p in perf_qs:
                    # Sum up change_percent over the period (Cumulative Return Proxy)
                    sector_scores[p['sector']] += p['change_percent']
                
                # Sort by total score desc
                sorted_sectors = sorted(sector_scores.items(), key=lambda x: x[1], reverse=True)
                leading_sectors = [s[0] for s in sorted_sectors[:5]]
                
                print(f"🏆 [DEBUG] Top 5 Leading Sectors: {leading_sectors}")
            else:
                print(f"⚠️ [DEBUG] No SectorPerformance data found in range")
        else:
            print(f"⚠️ [DEBUG] No SectorPerformance data exists at all, using fallback...")
            # 2. Fallback: If no history (e.g. fresh install), use today's picks average
            from collections import defaultdict
            sector_changes = defaultdict(list)
            for pick in picks:
                sector = pick.get('sector')
                change = pick.get('change')
                if sector and change is not None:
                    sector_changes[sector].append(change)
            
            sector_avg = []
            for sector, changes in sector_changes.items():
                avg_change = sum(changes) / len(changes) if changes else 0
                sector_avg.append((sector, avg_change))
            
            sector_avg.sort(key=lambda x: x[1], reverse=True)
            leading_sectors = [sector for sector, _ in sector_avg[:5]]
            print(f"🏆 [DEBUG] Fallback top 5: {leading_sectors}")

    except Exception as e:
        print(f"❌ Leading Sector Calc Error: {e}")
        import traceback
        traceback.print_exc()
        leading_sectors = []

    print(f"✅ [DEBUG] Final leading_sectors being sent to template: {leading_sectors}")

    # Re-sort picks with Leading Sectors Priority
    # Key: (Is NOT Leading (0=Top, 1=Bottom), Sector Name, -AvgVolume)
    picks.sort(key=lambda x: (
        0 if x.get('sector') in leading_sectors else 1,
        x.get('sector', 'ZZZ'),
        -(x.get('avg_volume_num', 0) or 0)
    ))
    
    # Debug: Print strategy statistics
    from collections import Counter
    all_strategies = []
    for pick in picks:
        all_strategies.extend(pick.get('strategies', []))
    
    strategy_counts = Counter(all_strategies)
    print("\n" + "="*60)
    print("📊 [STRATEGY STATISTICS]")
    print("="*60)
    print(f"Total picks: {len(picks)}")
    print(f"Total strategy occurrences: {len(all_strategies)}")
    print("\nStrategy breakdown:")
    for strategy, count in strategy_counts.most_common():
        print(f"  • {strategy}: {count} picks")
    print("="*60 + "\n")
    
    # [FIX] Reconstruct sectors_grouped for template rendering
    # The template iterates `sectors_grouped`, expecting [{'grouper': name, 'list': [picks]}]
    # [MULTI-SECTOR SUPPORT]: Add pick to multiple groups (GICS + Themes)
    from collections import defaultdict
    sector_map = defaultdict(list)
    
    print("\n" + "="*60)
    print("🔧 [SECTOR MAP DEBUG] Building sector_map...")
    print("="*60)
    
    for p in picks:
        # 1. Add to Primary Sector (GICS)
        sec = p.get('sector', 'Unknown')
        sector_map[sec].append(p)
        
        # 2. Add to Theme Categories (if any)
        themes = p.get('themes', [])
        if themes:
            print(f"  📊 {p.get('symbol')}: GICS='{sec}', Themes={themes}")
        for theme in themes:
            # Add to theme category (allow duplicates across categories)
            sector_map[theme].append(p)
    
    print(f"\n🗂️  Final sector_map keys: {list(sector_map.keys())}")
    for sector_name, stock_list in sector_map.items():
        print(f"  • {sector_name}: {len(stock_list)} stocks - {[s['symbol'] for s in stock_list]}")
    print("="*60 + "\n")
        
    sectors_grouped = []
    added_sectors = set()  # Track which sectors we've already added
    
    # 1. Add Leading Sectors First (in rank order)
    for ls in leading_sectors:
        if ls in sector_map and ls not in added_sectors:
            sectors_grouped.append({'grouper': ls, 'list': sector_map[ls]})
            added_sectors.add(ls)
            
    # 2. Add Remaining Sectors (Alphabetical)
    for sec in sorted(sector_map.keys()):
        if sec not in added_sectors:
            sectors_grouped.append({'grouper': sec, 'list': sector_map[sec]})
            added_sectors.add(sec)
    
    context['picks'] = picks
    context['sectors_grouped'] = sectors_grouped
    context['leading_sectors'] = leading_sectors
    chart_symbol = symbol_req if symbol_req else (picks[0]['symbol'] if picks else 'AAPL')
    context['chart_data'] = "[]"
    context['chart_markers'] = "[]"
    context['chart_symbol'] = chart_symbol
    
    # [OPTIMIZATION] Preload all profile data to avoid per-click API requests
    # Fetch all profile data for displayed stocks at once
    stock_profiles = {}
    symbols = [p['symbol'] for p in picks]
    
    if symbols:
        tickers = Ticker.objects.filter(symbol__in=symbols).prefetch_related('fundamentals')
        for t_obj in tickers:
            fund = t_obj.fundamentals.order_by('-date').first()
            
            # Parse 52W Range
            y_low, y_high = 0, 0
            if t_obj.price_range and '-' in t_obj.price_range:
                try:
                    parts = t_obj.price_range.split('-')
                    y_low = float(parts[0].strip().replace(',',''))
                    y_high = float(parts[1].strip().replace(',',''))
                except:
                    pass
            
            stock_profiles[t_obj.symbol] = {
                'name': t_obj.name,
                'description': t_obj.description,
                'sector': t_obj.sector,
                'industry': t_obj.industry,
                'image': t_obj.image,
                'ceo': t_obj.ceo,
                'employees': t_obj.full_time_employees,
                'ipo_date': str(t_obj.ipo_date) if t_obj.ipo_date else None,
                'beta': t_obj.beta,
                'last_dividend': t_obj.last_dividend,
                'price_range': t_obj.price_range,
                'year_low': y_low,
                'year_high': y_high,
                'is_etf': t_obj.is_etf,
                'market': t_obj.market,
                'market_cap': getattr(fund, 'market_cap', 0) if fund else 0,
                'pe_ratio': getattr(fund, 'pe_ratio', 0) if fund else 0,
                'eps': getattr(fund, 'eps_ttm', 0) if fund else 0,
                'pbr': getattr(fund, 'pb_ratio', 0) if fund else 0,
                'roe': getattr(fund, 'return_on_equity_ttm', 0) if fund else 0,
            }
    
    
    # Convert to JSON for safe JavaScript embedding
    import json
    context['stock_profiles'] = json.dumps(stock_profiles)
    print(f"✅ [OPTIMIZATION] Preloaded {len(stock_profiles)} stock profiles")

    return render(request, "scanner/vestiq_pick.html", context)


def send_report_email(request):
    """
    AI Report 페이지에서 특정 이메일로 리포트 발송
    """
    if request.method != "POST":
        return redirect("scanner:dashboard")

    symbol = request.POST.get("symbol")
    email = request.POST.get("email")

    if not symbol or not email:
        messages.error(request, "Symbol and Email are required.")
        return redirect("scanner:dashboard")

    # 1. 데이터 조회 (ai_report_view 로직 재사용)
    #    실제로는 ai_report_view 로직을 별도 함수로 분리하는 것이 좋으나,
    #    여기서는 간단히 필요한 데이터를 다시 조회합니다.
    row = ScanRow.objects.filter(symbol=symbol).order_by("-created_at").first()
    if not row:
        messages.error(request, f"No data found for {symbol}")
        return redirect("scanner:dashboard")

    # AI Report 데이터 가져오기 (캐시 또는 DB)
    # ai_report_view와 동일한 로직으로 데이터 구성
    # AI Report 데이터 가져오기 (캐시 또는 DB)
    # ai_report_view와 동일한 로직으로 데이터 구성
    close = getattr(row, "close", None)
    volume = getattr(row, "volume", None)
    prev_volume = getattr(row, "prev_volume", None)
    price_change_pct = getattr(row, "price_change_pct", None)
    vol_change_pct = getattr(row, "vol_change_pct", None)

    if price_change_pct is None:
        prev_close = getattr(row, "prev_close", None)
        if close is not None and prev_close not in (None, 0):
            price_change_pct = (close - prev_close) / prev_close * 100.0

    if vol_change_pct is None:
        if volume not in (None,) and prev_volume not in (None, 0):
            vol_change_pct = (volume - prev_volume) / prev_volume * 100.0

    stats = {
        "close": close,
        "price_change_pct": price_change_pct,
        "vol_change_pct": vol_change_pct,
        "volume": volume,
        "prev_volume": prev_volume,
        "f_volume": getattr(row, "f_volume", None),
        "f_volatility": getattr(row, "f_volatility", None),
        "f_trend": getattr(row, "f_trend", None),
        "f_pattern": getattr(row, "f_pattern", None),
        "f_momentum": getattr(row, "f_momentum", None),
    }

    company = {
        "name": getattr(row, "company_name", "") or symbol,
        "sector": getattr(row, "sector", "") or "",
        "industry": getattr(row, "industry", "") or "",
    }

    financials = get_financials_for_ai(symbol)
    language = get_language()

    # AI Report 생성/조회
    
    ai_report, error = generate_ai_report_structured(
        symbol=symbol,
        stats=stats,
        company=company,
        financials=financials,
        language=language
    )

    if not ai_report:
        messages.error(request, f"Failed to generate report for {symbol}: {error}")
        return redirect("scanner:report", symbol=symbol)

    # 2. 이메일 발송
    try:
        report_item = {
            "symbol": symbol,
            "company": company["name"],
            "stats": stats,
            "ai": ai_report
        }
        
        subject = f"[Vestiq] AI Report for {symbol}"
        body = f"""
        Attached is the AI Report for {symbol} ({company['name']}).
        
        Generated at: {timezone.now().strftime('%Y-%m-%d %H:%M')}
        """

        send_email_with_pdf(
            subject=subject,
            body=body,
            report_items=[report_item],
            generated_at=timezone.now(),
            to_email=email
        )
        messages.success(request, f"Email sent to {email} successfully!")
    except Exception as e:
        messages.error(request, f"Failed to send email: {e}")

    return redirect("scanner:report", symbol=symbol)


# -------------------------------------------------------------------------
# Strategy Backtest Lab
# -------------------------------------------------------------------------

def backtest_lab_view(request):
    """
    Render the Dedicated Backtest Lab Page.
    """
    from .models import DailyPick
    latest_pick = DailyPick.objects.order_by('-date').first()
    latest_date = latest_pick.date.strftime('%Y-%m-%d') if latest_pick else None
    
    return render(request, "scanner/backtest_lab.html", {
        "latest_date": latest_date
    })
    """
    Render the Backtest Lab UI
    """
    return render(request, "scanner/backtest_lab.html")


def api_run_backtest(request):
    """
    API: Run strategy simulation
    """
    if request.method != "POST":
        return JsonResponse({'error': 'Method not allowed'}, status=405)
        
    try:
        data = json.loads(request.body)
        
        # Extract config
        config = {
            'rsi_threshold': float(data.get('rsi', 30)),
            'volume_multiplier': float(data.get('volume', 2.0)),
            'profit_target_pct': float(data.get('profit', 5.0)),
            'max_hold_days': int(data.get('hold', 5)),
            'initial_capital': 10000
        }
        
        engine = BacktestEngine(config)
        results = engine.run()
        
        if 'error' in results:
            return JsonResponse({'error': results['error']}, status=400)
            
        return JsonResponse(results)
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

    
# ==========================================
# Modified API Chart Data with Sentiment Logic
# ==========================================
def api_chart_data(request, symbol):
    import fear_and_greed
    
    # [NEW] Active Period
    period = request.GET.get('period', 'daily')

    try:
        # Fetch Sentiment
        try:
            fg = fear_and_greed.get()
            sentiment = int(fg.value)
        except:
            sentiment = 50

        # Base Factors
        stop_mult = 1.0
        target_mult = 1.0
        
        # Adjust Factors
        if sentiment < 25: 
            stop_mult = 1.2
            target_mult = 1.2
        elif sentiment > 75:
            stop_mult = 0.8
            target_mult = 0.8
            
        # Fetch Data from DB
        cutoff_date = datetime.now().date() - timedelta(days=365*5 + 50) 
        qs = PriceHistory.objects.filter(symbol__symbol=symbol, date__gte=cutoff_date).order_by('date')
        
        # --- LAZY UPDATE LOGIC DISABLED ---
        # The user requested to disable on-the-fly updates from YFinance.
        # Charts should only reflect what is currently in the DB (PriceHistory).
        # See Step 907-928 in history.

                
        if qs.exists():
            data = list(qs.values('date', 'open', 'high', 'low', 'close', 'volume'))
            df = pd.DataFrame(data)
            df['date'] = pd.to_datetime(df['date'])
            df.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'volume': 'Volume'}, inplace=True)
        else:
            # Fallback: Fetch from YFinance (for Macro/Indices/Missing tickers)
            try:
                # Use a cached session or just standard yf (since this is on-demand)
                t_yf = yf.Ticker(symbol)
                # Fetch enough history for indicators (SMA120 needs ~6 months, let's get 2y)
                hist = t_yf.history(period="2y")
                
                if hist.empty:
                    return JsonResponse({'error': 'No data found'}, status=404)
                
                # Normalize YF Data
                df = hist.reset_index()
                # YF columns: Date, Open, High, Low, Close, Volume, Dividends, Stock Splits
                df.rename(columns={'Date': 'date'}, inplace=True)
                
                # Make naive datetime for consistency
                if df['date'].dt.tz is not None:
                    df['date'] = df['date'].dt.tz_localize(None)
                    
            except Exception as e:
                print(f"YFinance Fallback Error for {symbol}: {e}")
                return JsonResponse({'error': 'No data found'}, status=404)
        
        # [LIVE UPDATE PATCH]
        # Append latest data from YFinance if DB is lagging (Display Only, No DB Write)
        try:
            last_db_date = df['date'].max() if not df.empty else None
            # If last date is today, we might still want updates? 
            # But let's assume if it's strictly older than today (or generally fetching last 5d to be safe)
            
            # Fetch last 5 days to catch up any missing recent candles
            t_live = yf.Ticker(symbol)
            live_hist = t_live.history(period="5d")
            
            if not live_hist.empty:
                live_vals = live_hist.reset_index()
                live_vals.rename(columns={'Date': 'date'}, inplace=True)
                
                # Timezone naive
                if live_vals['date'].dt.tz is not None:
                    live_vals['date'] = live_vals['date'].dt.tz_localize(None)
                
                # Normalize columns
                live_vals.rename(columns={'Open':'Open', 'High':'High', 'Low':'Low', 'Close':'Close', 'Volume':'Volume'}, inplace=True)
                # Ensure other columns match if needed (YF capitalizes, DB was renamed to Title case above)
                
                # Filter for newer dates
                if last_db_date:
                    new_rows = live_vals[live_vals['date'].dt.date > last_db_date.date()]
                else:
                    new_rows = live_vals
                
                if not new_rows.empty:
                    # Append strictly needed columns
                    df = pd.concat([df, new_rows[['date', 'Open', 'High', 'Low', 'Close', 'Volume']]], ignore_index=True)
        except Exception as e:
            print(f"Live Append Error: {e}")
            pass
        
        # Sort and Reset
        df = df.sort_values('date').reset_index(drop=True)
        
        # [NEW] WEEKLY RESAMPLING
        if period == 'weekly':
            # Set date as index for resampling
            df.set_index('date', inplace=True)
            
            # Resample to Weekly (Ending Friday)
            df_weekly = df.resample('W-FRI').agg({
                'Open': 'first',
                'High': 'max',
                'Low': 'min',
                'Close': 'last',
                'Volume': 'sum'
            })
            # Drop incomplete periods
            df_weekly.dropna(inplace=True)
            
            # Reset index
            df = df_weekly.reset_index()
            
            # Filter out future dates (Allow up to 7 days ahead for Weekly Friday label)
            df = df[df['date'] <= pd.Timestamp.today() + pd.Timedelta(days=7)]
            
            # Reset Index
            df = df.reset_index(drop=True)
        
        # Rename step handled above for both cases, ensuring 'Open'...'Volume' exist.

        
        # 1. Indicators
        df['SMA20'] = df['Close'].rolling(window=20).mean()
        df['SMA60'] = df['Close'].rolling(window=60).mean()
        df['SMA120'] = df['Close'].rolling(window=120).mean()
        df['SMA200'] = df['Close'].rolling(window=200).mean()
        
        # Bollinger Bands (20, 2)
        df['STD20'] = df['Close'].rolling(window=20).std()
        df['Upper'] = df['SMA20'] + (df['STD20'] * 2)
        df['Lower'] = df['SMA20'] - (df['STD20'] * 2)
        
        # Stochastics (Triple Screen)
        sk_s, sd_s = calculate_stoch_slow(df, 5, 3, 3)
        sk_m, sd_m = calculate_stoch_slow(df, 10, 6, 6)
        sk_l, sd_l = calculate_stoch_slow(df, 20, 12, 12)
        
        df['k_s'], df['d_s'] = sk_s, sd_s
        df['k_m'], df['d_m'] = sk_m, sd_m
        df['k_l'], df['d_l'] = sk_l, sd_l
        
        # RSI (14)
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))

        # MACD (12, 26, 9)
        exp12 = df['Close'].ewm(span=12, adjust=False).mean()
        exp26 = df['Close'].ewm(span=26, adjust=False).mean()
        df['MACD'] = exp12 - exp26
        df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
        df['Hist'] = df['MACD'] - df['Signal']

        # [NEW] Ichimoku Cloud Calculations
        # Tenkan (9)
        h9 = df['High'].rolling(window=9).max()
        l9 = df['Low'].rolling(window=9).min()
        df['tenkan'] = (h9 + l9) / 2
        
        # Kijun (26)
        h26 = df['High'].rolling(window=26).max()
        l26 = df['Low'].rolling(window=26).min()
        df['kijun'] = (h26 + l26) / 2
        
        # Span A (Tenkan+Kijun)/2 shifted 26
        df['span_a'] = ((df['tenkan'] + df['kijun']) / 2).shift(26)
        
        # Span B (High52+Low52)/2 shifted 26
        h52 = df['High'].rolling(window=52).max()
        l52 = df['Low'].rolling(window=52).min()
        df['span_b'] = ((h52 + l52) / 2).shift(26)
        
        # Chikou (Close shifted -26)
        df['chikou'] = df['Close'].shift(-26)

        # Format for ECharts
        ohlcv = []
        ma = {'ma20': [], 'ma60': [], 'ma120': [], 'ma200': []}
        bb = {'upper': [], 'lower': []}
        stoch = {'s': [], 'm': [], 'l': []}
        rsi_data = []
        macd_data = {'macd': [], 'diff': [], 'signal': []}
        ichimoku_data = {'tenkan': [], 'kijun': [], 'span_a': [], 'span_b': [], 'chikou': []}
        markers = []

        df = df.fillna(0) 
        check_start_idx = max(0, len(df) - 90) # Check signals for last 90 days only
        
        for idx in range(len(df)):
            row = df.iloc[idx]
            ts = int(row['date'].timestamp()) + 3600 * 12 
            d_str = row['date'].strftime('%Y-%m-%d')
            
            ohlcv.append({
                'time': ts,
                'open': float(row['Open']), 'high': float(row['High']), 'low': float(row['Low']), 'close': float(row['Close']), 'volume': float(row['Volume']),
                'value': [float(row['Open']), float(row['Close']), float(row['Low']), float(row['High'])] 
            })
            
            ma['ma20'].append({'time': ts, 'value': float(row['SMA20']) if row['SMA20'] else None})
            ma['ma60'].append({'time': ts, 'value': float(row['SMA60']) if row['SMA60'] else None})
            ma['ma120'].append({'time': ts, 'value': float(row['SMA120']) if row['SMA120'] else None})
            ma['ma200'].append({'time': ts, 'value': float(row['SMA200']) if row['SMA200'] else None})
            
            bb['upper'].append({'time': ts, 'value': float(row['Upper']) if row['Upper'] else None})
            bb['lower'].append({'time': ts, 'value': float(row['Lower']) if row['Lower'] else None})
            
            stoch['s'].append({'time': ts, 'k': float(row['k_s']), 'd': float(row['d_s'])})
            stoch['m'].append({'time': ts, 'k': float(row['k_m']), 'd': float(row['d_m'])})
            stoch['l'].append({'time': ts, 'k': float(row['k_l']), 'd': float(row['d_l'])})
            
            rsi_data.append({'time': ts, 'value': float(row['RSI'])})
            macd_data['macd'].append({'time': ts, 'value': float(row['MACD'])})
            macd_data['signal'].append({'time': ts, 'value': float(row['Signal'])})
            macd_data['diff'].append({'time': ts, 'value': float(row['Hist'])})
            
            # Ichimoku - Force Chikou trailing gap (last 26 rows must be None)
            total_rows = len(df)
            is_last_26 = (idx >= total_rows - 26)
            
            ichimoku_data['tenkan'].append(float(row['tenkan']) if pd.notnull(row.get('tenkan')) else None)
            ichimoku_data['kijun'].append(float(row['kijun']) if pd.notnull(row.get('kijun')) else None)
            ichimoku_data['span_a'].append(float(row['span_a']) if pd.notnull(row.get('span_a')) else None)
            ichimoku_data['span_b'].append(float(row['span_b']) if pd.notnull(row.get('span_b')) else None)
            
            # Chikou: Force None for last 26 values, also treat 0 as None
            if is_last_26:
                ichimoku_data['chikou'].append(None)
            else:
                chikou_val = row.get('chikou')
                if pd.notnull(chikou_val) and chikou_val != 0:
                    ichimoku_data['chikou'].append(float(chikou_val))
                else:
                    ichimoku_data['chikou'].append(None)

        # --- SIGNAL MARKERS (Last 90 Days) ---
        check_start = max(0, len(df) - 90)  # Show signals from last 90 days
        
        # Collect signals by date to avoid duplicates
        signal_map = {}
        
        # Include ALL candles including the last one
        # User wants to see all signals from the past 90 days on the chart
        for i in range(check_start, len(df)):
            curr = df.iloc[i]
            d_str = curr['date'].strftime('%Y-%m-%d')
            
            l_price = float(curr['Low'])
            h_price = float(curr['High'])
            
            # Create a slice up to this point to simulate "latest state" for strategy function
            # We slice up to i+1 so that 'curr' is the last row
            # Optimization: pass only necessary window if known, but full slice is safer for SMA/RSI calculation
            # [FIX] Weekly Ichimoku needs at least 52 weeks (~260 days). 
            # 200 days is too short for Weekly Span B calculation (needs 52-week High/Low).
            # Increased to 500 days (~2 years) to ensure Weekly indicators are valid.
            start_slice = max(0, i - 500) 
            df_slice = df.iloc[start_slice : i+1].copy()
            
            signals = calculate_vestiq_strategies(df_slice)
            
            if signals:
                # Deduplicate signals (sometimes logic returns dupes)
                signals = list(set(signals))
                
                # Initialize signal collection for this date
                if d_str not in signal_map:
                    signal_map[d_str] = {
                        'buy_signals': [],
                        'sell_signals': [],
                        'l_price': l_price,
                        'h_price': h_price
                    }
                
                # Collect all signals for this date
                # Priority order: Secret > Phoenix > Prime > Alpha > Hedge
                
                if any('Secret' in s for s in signals):
                    signal_map[d_str]['buy_signals'].append({
                        'name': 'Secret ★',
                        'color': '#fbbf24',
                        'symbol': 'path://M12 .587l3.668 7.568 8.332 1.151-6.064 5.828 1.48 8.279-7.416-3.967-7.417 3.967 1.481-8.279-6.064-5.828 8.332-1.151z',
                        'symbolSize': 18
                    })
                
                if any('Phoenix' in s for s in signals):
                    signal_map[d_str]['buy_signals'].append({
                        'name': 'Phoenix 🐦‍🔥',
                        'color': '#f97316',
                        'symbol': 'triangle',
                        'symbolSize': 15
                    })
                
                if any('Prime' in s for s in signals):
                    signal_map[d_str]['buy_signals'].append({
                        'name': 'Prime ⚡',
                        'color': '#E5C1C5',
                        'symbol': 'arrow',
                        'symbolSize': 12
                    })
                
                if any('Alpha' in s for s in signals):
                    signal_map[d_str]['buy_signals'].append({
                        'name': 'Alpha ✨',
                        'color': '#22c55e',
                        'symbol': 'arrow',
                        'symbolSize': 12
                    })
                
                if any('Hedge' in s for s in signals):
                    signal_map[d_str]['sell_signals'].append({
                        'name': 'Hedge 💧',
                        'color': '#ef4444',
                        'symbol': 'arrow',
                        'symbolSize': 12,
                        'symbolRotate': 180
                    })
                
                # Gurum (Kumo) Signals
                if any('Gurum Rocket' in s for s in signals):
                    signal_map[d_str]['buy_signals'].append({
                        'name': 'GURUM ROCKET 🚀',
                        'color': '#fbbf24',  # Gold
                        'symbol': 'rect',
                        'symbolSize': 14
                    })
                
                if any('Gurum Perfect' in s for s in signals):
                    signal_map[d_str]['buy_signals'].append({
                        'name': 'GURUM PERFECT 💎',
                        'color': '#a855f7',  # Purple
                        'symbol': 'diamond',
                        'symbolSize': 14
                    })
                
                if any('Gurum Cross' in s for s in signals):
                    signal_map[d_str]['buy_signals'].append({
                        'name': 'GURUM CROSS ⚔️',
                        'color': '#06b6d4',  # Cyan
                        'symbol': 'pin',
                        'symbolSize': 14
                    })
        
        # Create SEPARATE stacked markers for each signal
        for d_str, sig_data in signal_map.items():
            # Initialize Y offset
            current_y_offset = 35
            
            # Handle buy signals (bottom of candle) - Each signal separate
            for signal in sig_data['buy_signals']:
                markers.append({
                    'coord': [d_str, sig_data['l_price']],
                    'value': signal['name'],
                    'symbol': signal['symbol'],
                    'symbolSize': signal['symbolSize'],
                    'symbolRotate': 0,
                    'symbolOffset': [0, current_y_offset],
                    'itemStyle': {
                        'color': signal['color'],
                        'shadowBlur': 5,
                        'shadowColor': signal['color']
                    },
                    'label': {
                        'show': True,
                        'position': 'bottom',
                        'distance': 5,
                        'formatter': signal['name'],
                        'fontSize': 14,
                        'fontWeight': 'bold',
                        'color': signal['color']
                    },
                    'tooltip': {'formatter': f"<b>{signal['name']}</b><br>{d_str}"}
                })
                current_y_offset += 50  # Stack next signal 50px below
            
            # Handle sell signals (top of candle) - Separate markers
            for signal in sig_data['sell_signals']:
                markers.append({
                    'coord': [d_str, sig_data['h_price']],
                    'value': signal['name'],
                    'symbol': signal['symbol'],
                    'symbolSize': signal['symbolSize'],
                    'symbolRotate': signal.get('symbolRotate', 0),
                    'symbolOffset': [0, -20],
                    'itemStyle': {'color': signal['color']},
                    'label': {
                        'show': True,
                        'position': 'top',
                        'distance': 5,
                        'formatter': signal['name'],
                        'fontSize': 14,
                        'fontWeight': 'bold',
                        'color': signal['color']
                    },
                    'tooltip': {'formatter': f"<b>{signal['name']}</b><br>{d_str}"}
                })

        # --- FORCE MARKER ON LAST CANDLE IF STRATEGY SAYS ALPHA/HEDGE ---
        last_row = df.iloc[-1]
        l_ts = int(last_row['date'].timestamp()) + 3600 * 12
        l_d_str = last_row['date'].strftime('%Y-%m-%d')
        l_price = float(last_row['Close']) 
        lh_price = float(last_row['High'])
        ll_price = float(last_row['Low'])
        lk = last_row['k_s']
        
        df['SMA20'] = df['Close'].rolling(20).mean()
        df['SMA60'] = df['Close'].rolling(60).mean()
        df['SMA120'] = df['Close'].rolling(120).mean()
        df['SMA200'] = df['Close'].rolling(200).mean()
        df['VolSMA20'] = df['Volume'].rolling(20).mean()
        
        # Stochastics (for Logic)
        k_s, d_s = calculate_stoch_slow(df, 5, 3, 3)
        k_m, d_m = calculate_stoch_slow(df, 10, 6, 6)
        k_l, d_l = calculate_stoch_slow(df, 20, 12, 12)
        df['k_s'] = k_s; df['d_s'] = d_s
        df['k_m'] = k_m
        df['k_l'] = k_l; df['d_l'] = d_l
        
        # MACD (for Phoenix)
        ema12 = df['Close'].ewm(span=12, adjust=False).mean()
        ema26 = df['Close'].ewm(span=26, adjust=False).mean()
        df['MACD'] = ema12 - ema26
        df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
        
        latest_signals = calculate_vestiq_strategies(df)
        
        # [Fallback] If latest has no signal, check Previous Candle
        used_row = df.iloc[-1]
        
        if not latest_signals and len(df) >= 2:
            df_prev = df.iloc[:-1].copy()
            prev_signals = calculate_vestiq_strategies(df_prev)
            if prev_signals:
                latest_signals = prev_signals
                used_row = df.iloc[-2] # Marker logic should technically use prev date

        # Marker Coordinates (Derived from the row triggering the signal)
        marker_date_str = used_row['date'].strftime('%Y-%m-%d')
        marker_price_low = float(used_row['Low'])

        # --- 2. CALCULATE ACTIVE SIGNALS (Moved UP for Consistency) ---
        active_signals = []
        entry = float(used_row['Close']) # Used for calculations
        
        # [TEXT ADAPTER]
        t_ma20 = "20일선" if period == 'daily' else "20주선"
        t_ma200 = "200일선" if period == 'daily' else "200주선"
        
        # PRIME
        if 'Prime' in latest_signals:
            target = entry * 1.05; stop = entry * 0.97; support = float(used_row['SMA20']) if pd.notna(used_row['SMA20']) else entry * 0.95; resistance = float(used_row['Upper']) if 'Upper' in used_row and pd.notna(used_row['Upper']) else entry * 1.10
            active_signals.append({'name': 'Prime ⚡', 'color': '#f59e0b', 'reasons': [f'• {t_ma20}(생명선) 상향 돌파', '• 추세 전환의 강력한 신호', f'➤ 진입가: ${entry:.2f}', f'➤ 목표가: ${target:.2f} (+5%)', f'➤ 손절가: ${stop:.2f} (-3%)', f'➤ 지지선: ${support:.2f} (SMA20)', f'➤ 저항선: ${resistance:.2f} (BB Upper)']})

        # ALPHA
        if 'Alpha' in latest_signals:
            target = entry * 1.05; stop = entry * 0.95; support = float(used_row['Lower']) if 'Lower' in used_row and pd.notna(used_row['Lower']) else entry * 0.90
            active_signals.append({'name': 'Alpha ✨', 'color': '#22c55e', 'reasons': [f'• 극심한 과매도 구간 (K: {float(used_row["k_s"]):.1f})', '• 과매도 권역 반등 기대', f'➤ 진입가: ${entry:.2f}', f'➤ 목표가: ${target:.2f}', f'➤ 손절가: ${stop:.2f}', f'➤ 지지선: ${support:.2f} (BB Lower)']})

        # HEDGE
        if 'Hedge' in latest_signals:
            target = entry * 0.95; stop = entry * 1.03; resistance = float(used_row['Upper']) if 'Upper' in used_row and pd.notna(used_row['Upper']) else entry * 1.05
            active_signals.append({'name': 'Hedge 🛡️', 'color': '#ef4444', 'reasons': [f'• 극심한 과매수 구간 (K: {float(used_row["k_s"]):.1f})', '• 차익 실현 권장', f'➤ 현재가: ${entry:.2f}', f'➤ 저항선: ${resistance:.2f} (BB Upper)', f'➤ 리스크 관리(손절): ${stop:.2f}']})

        # PHOENIX
        if 'Phoenix' in latest_signals:
            target = entry * 1.10; stop = entry * 0.95; support = float(used_row['SMA200']) if 'SMA200' in used_row and pd.notna(used_row['SMA200']) else entry * 0.90
            active_signals.append({'name': 'Phoenix', 'color': '#f97316', 'reasons': [f'• 장기 상승 추세 속 깊은 조정 (Price > {t_ma200})', '• MACD 골든크로스 (추세 반전 신호)', f'➤ 진입가: ${entry:.2f}', f'➤ 목표가: ${target:.2f}', f'➤ 손절가: ${stop:.2f}', f'➤ 지지선: ${support:.2f} (SMA200)']})
        
        # SECRET
        if 'Secret' in latest_signals:
            target = entry * 1.10; stop = entry * 0.96; support = float(used_row['SMA20']) if 'SMA20' in used_row and pd.notna(used_row['SMA20']) else entry * 0.95
            active_signals.append({'name': 'Secret ★', 'color': '#fbbf24', 'reasons': ['• 3중 모멘텀 정배열 (Triple Stoch Up)', '• MACD 골든크로스 (확실한 반등)', '• 완벽한 기회 (Perfect Alignment)', f'➤ 진입가: ${entry:.2f}', f'➤ 목표가: ${target:.2f}', f'➤ 손절가: ${stop:.2f}']})


        # KUMO CROSS
        if 'Kumo Cross' in latest_signals:
            active_signals.append({'name': 'Kumo Cross ⚔️', 'color': '#c084fc', 'reasons': ['• 전환선이 기준선 골든크로스', '• 빠른 상승 모멘텀 포착']})

        # KUMO PERFECT
        if 'Kumo Perfect' in latest_signals:
            active_signals.append({'name': 'Kumo Perfect ✨', 'color': '#e9d5ff', 'reasons': ['• 삼역호전 (Perfect Order)', '• 가격 > 전환선 > 기준선 > 구름대', '• 최강 상승 배열']})






        # --- AI Analysis Comment & Forecast Lines (Detailed) ---
        ai_comment = "데이터가 부족하여 분석할 수 없습니다."
        forecast_lines = [] 
        
        if len(df) >= 2:
            last_row = df.iloc[-1]
            
            # 1. Analyze Each Stoch (Short/Mid/Long) with NUMBERS
            # Short (5,3,3)
            k_s = last_row['k_s']; d_s = last_row['d_s']
            s_val_str = f"(K: {k_s:.1f}, D: {d_s:.1f})"
            s_status = ""
            if k_s <= 20: s_status = f"과매도{s_val_str}"
            elif k_s >= 80: s_status = f"과매수{s_val_str}"
            elif k_s > d_s: s_status = f"골든크로스{s_val_str}"
            else: s_status = f"데드크로스{s_val_str}"
            
            # Mid (10,6,6)
            k_m = last_row['k_m']; d_m = last_row['d_m']
            m_val_str = f"(K: {k_m:.1f}, D: {d_m:.1f})"
            m_status = "중립"
            if k_m <= 20: m_status = "과매도"
            elif k_m >= 80: m_status = "과매수"
            elif k_m > d_m: m_status = "상승확대"
            else: m_status = "하락압력"

            # Long (20,12,12)
            k_l = last_row['k_l']; d_l = last_row['d_l']
            l_val_str = f"(K: {k_l:.1f}, D: {d_l:.1f})"
            l_trend = "상승" if k_l > d_l else "하락"
            
            # [MOVED UP] Logic moved to before marker generation
            
            # --- Combine Signals ---
            if not active_signals:
                strategy_title = "HOLD (관망)"
                strategy_color = "#94a3b8"
                reasons = ["• 뚜렷한 매매 신호 없음", "• 관망 권장"]
            else:
                # Join Names
                strategy_title = " + ".join([s['name'] for s in active_signals])
                # Pick Color (Priority: Prime > Alpha > Hedge? Or just first?)
                # If Prime is present, use Prime color (Orange/Amber) to highlight it as requested.
                # If Mixed Alpha/Hedge (rare), pick first.
                strategy_color = active_signals[0]['color'] 
                
                # Collect Reasons
                reasons = []
                for s in active_signals:
                    reasons.extend(s['reasons'])

            # Construct Comment
            ai_comment = f"""
            📊 [Vestiq AI Technical Analysis]
            
            1. Short-Term (단기): {s_status}
            2. Mid-Term (중기): {m_status} {m_val_str}
            3. Long-Term (장기): {l_trend} 추세 {l_val_str}
            
            💡 Strategy: {strategy_title}
            """
            
            signal_analysis = {
                'show': True,
                'title': strategy_title,
                'color': strategy_color,
                'reasons': reasons,
                'signals': active_signals, # Expose list for frontend iteration
                'type': "Alpha 🚀" if "Alpha" in strategy_title else "Hedge 🛡️" if "Hedge" in strategy_title else "Hold"
            }


            # MA Support Check (Text Only, No Chart Lines)
            close_price = float(last_row['Close'])
            ma20 = float(last_row['SMA20']) if last_row['SMA20'] else 0
            ma60 = float(last_row['SMA60']) if last_row['SMA60'] else 0
            
            ma_msg = []
            if ma20 and abs(close_price - ma20) / close_price < 0.02:
                ma_msg.append(f"노란색 선(20일선: {ma20:.2f})")
            if ma60 and abs(close_price - ma60) / close_price < 0.02:
                ma_msg.append(f"초록색 선(60일선: {ma60:.2f})")
                
            if ma_msg:
                 joined_ma = " 또는 ".join(ma_msg)
                 ai_comment += f"\n\n또한, 주가가 {joined_ma} 지지 라인을 지켜주는지 확인해야 합니다."
        
        else:
            signal_analysis = {'show': False}


        # Calculate Strategy Levels (Latest)
        last_close = float(df.iloc[-1]['Close'])
        strategy_prices = {
            'ALPHA': {
                'entry': last_close,
                'stop_loss': last_close * 0.95,
                'target': last_close * 1.05
            }
        }

        # Fetch Profile Data
        # from updatedata.models import Ticker # Removed to use Global Import
        t_obj = Ticker.objects.filter(symbol=symbol).first()
        profile = {}
        if t_obj:
            # Get Latest Fundamentals
            fund = t_obj.fundamentals.order_by('-date').first()
            
            # Parse Price Range for Bar Chart
            y_low, y_high = 0, 0
            if t_obj.price_range and '-' in t_obj.price_range:
                try:
                    parts = t_obj.price_range.split('-')
                    y_low = float(parts[0].strip().replace(',',''))
                    y_high = float(parts[1].strip().replace(',',''))
                except:
                    pass

            profile = {
                'name': t_obj.name,
                'description': t_obj.description,
                'sector': t_obj.sector,
                'industry': t_obj.industry,
                'image': t_obj.image,
                'ceo': t_obj.ceo,
                'employees': t_obj.full_time_employees,
                'ipo_date': t_obj.ipo_date,
                'beta': t_obj.beta,
                'last_dividend': t_obj.last_dividend,
                'price_range': t_obj.price_range,
                'year_low': y_low,
                'year_high': y_high,
                'is_etf': t_obj.is_etf,
                'market': t_obj.market,
                'market_cap': getattr(fund, 'market_cap', 0) if fund else 0,
                'pe_ratio': getattr(fund, 'pe_ratio', 0) if fund else 0,  # Frontend expects 'pe_ratio'
                'eps': getattr(fund, 'eps_ttm', 0) if fund else 0,
                'pbr': getattr(fund, 'pb_ratio', 0) if fund else 0,
                'roe': getattr(fund, 'return_on_equity_ttm', 0) if fund else 0,
            }

        # 1.5. Calculate Ichimoku Cloud
        ichimoku = {}
        try:
            if len(df) >= 52:
                # Ensure float for calculation (Using Capitalized Column Names - Reverted fix)
                # Debugging Columns to be sure
                print(f"[Chart] Ichimoku DF Columns: {df.columns}")
                for col in ['High', 'Low', 'Close']:
                    df[col] = df[col].astype(float)

                high_9 = df['High'].rolling(window=9).max()
                low_9 = df['Low'].rolling(window=9).min()
                tenkan_sen = (high_9 + low_9) / 2

                high_26 = df['High'].rolling(window=26).max()
                low_26 = df['Low'].rolling(window=26).min()
                kijun_sen = (high_26 + low_26) / 2

                senkou_span_a = ((tenkan_sen + kijun_sen) / 2).shift(26)
                high_52 = df['High'].rolling(window=52).max()
                low_52 = df['Low'].rolling(window=52).min()
                senkou_span_b = ((high_52 + low_52) / 2).shift(26)

                chikou_span = df['Close'].shift(-26)

                # Convert to simple aligned lists (matching OHLCV index exactly)
                def to_list(series):
                    # Ensure 0 becomes None for ECharts line breaking
                    return [float(x) if pd.notna(x) and x != 0 else None for x in series]

                # AGGRESSIVE Chikou fix: Truncate to remove last 26 values entirely
                chikou_span_cleaned = chikou_span.replace(0, np.nan)
                chikou_list = to_list(chikou_span_cleaned)
                
                # Ensure last 26 values are strictly None by truncating and rebuilding
                original_len = len(chikou_list)
                if original_len > 26:
                    # Keep only the first (length - 26) values, force rest to None
                    chikou_list = chikou_list[:original_len - 26] + [None] * 26
                else:
                    # If very short data, all None
                    chikou_list = [None] * original_len
                    
                ichimoku = {
                    'tenkan': to_list(tenkan_sen),
                    'kijun': to_list(kijun_sen),
                    'span_a': to_list(senkou_span_a),
                    'span_b': to_list(senkou_span_b),
                    'chikou': chikou_list
                }

                # --- FUTURE CLOUD LOGIC (Extend 26 Periods) ---
                # "Leading Spans" are calculated today but plotted 26 days ahead.
                # So the latest 26 values of the computation correspond to the future cloud.
                # Re-calculate unshifted spans to get the latest values
                leading_span_a_series = (tenkan_sen + kijun_sen) / 2
                leading_span_b_series = (high_52 + low_52) / 2
                
                # Get the last 26 values (which belong to T+1 ... T+26)
                future_a = leading_span_a_series.iloc[-26:].tolist()
                future_b = leading_span_b_series.iloc[-26:].tolist()

                # Generate Future Dates (Business Days) - Start after last date
                last_date = df['date'].iloc[-1]
                # Generate 27 days, ensure we skip the first one (today)
                future_dates = pd.date_range(start=last_date, periods=27, freq='B')[1:] 

                for i, f_date in enumerate(future_dates):
                    if i >= len(future_a): break # Safety
                    
                    ts = int(f_date.timestamp()) + 3600 * 12
                    
                    # Append Empty Candle
                    ohlcv.append({
                        'time': ts,
                        'open': None, 'high': None, 'low': None, 'close': None, 'volume': None,
                        'value': [None, None, None, None]
                    })
                    
                    # Append Empty Indicators
                    for k in ma: ma[k].append({'time': ts, 'value': None})
                    for k in bb: bb[k].append({'time': ts, 'value': None})
                    for k in stoch: stoch[k].append({'time': ts, 'k': None, 'd': None})
                    rsi_data.append({'time': ts, 'value': None})
                    macd_data['macd'].append({'time': ts, 'value': None})
                    macd_data['signal'].append({'time': ts, 'value': None})
                    macd_data['diff'].append({'time': ts, 'value': None})

                    # Append Ichimoku (Future Spans have data!)
                    ichimoku['tenkan'].append(None)
                    ichimoku['kijun'].append(None)
                    ichimoku['chikou'].append(None)
                    val_a = float(future_a[i]) if pd.notna(future_a[i]) else None
                    val_b = float(future_b[i]) if pd.notna(future_b[i]) else None
                    ichimoku['span_a'].append(val_a)
                    ichimoku['span_b'].append(val_b)
        except Exception as e:
            print(f"[Chart] Ichimoku Error: {e}") 
            import traceback
            traceback.print_exc()


        # 2. Fundamentals (Latest)
        fund_data = {}
        try:
            t_obj = Ticker.objects.filter(symbol=symbol).first()
            if t_obj:
                # Basic Info
                fund_data['name'] = t_obj.name
                fund_data['sector'] = t_obj.sector
                fund_data['industry'] = t_obj.industry
                fund_data['description'] = t_obj.description
                fund_data['market_cap'] = None
                fund_data['beta'] = t_obj.beta  # [FIX] Get beta from Ticker model
                fund_data['div'] = None
                fund_data['last_dividend'] = t_obj.last_dividend  # [FIX] Add last_dividend
                fund_data['price_range'] = t_obj.price_range  # [FIX] Add price_range
                
                # Parse 52W Range
                y_low, y_high = 0, 0
                if t_obj.price_range and '-' in t_obj.price_range:
                    try:
                        parts = t_obj.price_range.split('-')
                        y_low = float(parts[0].strip().replace(',',''))
                        y_high = float(parts[1].strip().replace(',',''))
                    except:
                        pass
                fund_data['year_low'] = y_low  # [FIX] Add year_low
                fund_data['year_high'] = y_high  # [FIX] Add year_high
                
                # Check FundamentalData (Tiingo/FMP)
                last_fund = t_obj.fundamentals.order_by('-date').first()
                
                # Lazy Update: If missing, try to fetch immediately
                if not last_fund:
                    print(f"[Chart] Fundamentals missing for {symbol}. Triggering lazy fetch...")
                    _lazy_fetch_fundamentals(t_obj)
                    last_fund = t_obj.fundamentals.order_by('-date').first() # Re-fetch

                if last_fund:
                    fund_data['market_cap'] = last_fund.market_cap
                    fund_data['per'] = last_fund.pe_ratio  # For top bar display
                    fund_data['pe_ratio'] = last_fund.pe_ratio  # [FIX] Frontend expects 'pe_ratio'
                    fund_data['pbr'] = last_fund.pb_ratio
                    fund_data['roe'] = last_fund.return_on_equity_ttm
                    fund_data['eps'] = last_fund.eps_ttm
                    # Note: dividend data comes from Ticker.last_dividend (already set above)
                
                # 52W Range Calculation (from Price History)
                # 52W Range Calculation (Robust Fallback)
                # First try PriceHistory (Tiingo/Adjusted)
                today = pd.Timestamp.now().date()
                one_year_ago = today - pd.Timedelta(days=365)
                
                high_52, low_52, curr_price = None, None, None
                
                # Check PriceHistory first
                ph_qs = PriceHistory.objects.filter(symbol=t_obj, date__gte=one_year_ago).values_list('high', 'low', 'close')
                if ph_qs.exists():
                    highs = [x[0] for x in ph_qs if x[0]]
                    lows = [x[1] for x in ph_qs if x[1]]
                    if highs and lows:
                        high_52 = max(highs)
                        low_52 = min(lows)
                        curr_price = ph_qs.last()[2]

                # Fallback to DailyPrice (OHLCV) if missing
                if high_52 is None:
                    # Leverage the ohlcv data we already fetched or query DailyPrice
                    # ohlcv is a list of dicts: {'date':..., 'open':..., ...}
                    # It might be short, so check dates
                    # Convert one_year_ago to string or comparable
                    date_thresh = one_year_ago.strftime('%Y-%m-%d')
                    
                    # Filter ohlcv for last year
                    valid_candles = [c for c in ohlcv if c['date'] >= date_thresh]
                    if valid_candles:
                         highs = [c['high'] for c in valid_candles]
                         lows = [c['low'] for c in valid_candles]
                         if highs and lows:
                             high_52 = max(highs)
                             low_52 = min(lows)
                             curr_price = valid_candles[-1]['close'] # Last Close

                if high_52 is not None:
                     fund_data['range_52w'] = {'high': high_52, 'low': low_52, 'current': curr_price}
                
                # Logo URL
                fund_data['logo_url'] = f"https://financialmodelingprep.com/image-stock/{symbol}.png"

        except Exception as e:
            print(f"[Chart] Fundamental Fetch Error: {e}")

        # Convergence pattern removed - replaced with manual trendline tool

        return JsonResponse({
            'symbol': symbol,
            'ohlcv': ohlcv,
            'ma': ma,
            'bb': bb, 
            'stoch': stoch,
            'rsi': rsi_data,
            'macd': macd_data,
            'markers': markers,
            'ichimoku': ichimoku, 
            'signal_analysis': signal_analysis,
            'strategy_prices': strategy_prices,
            'profile': fund_data, 
            'ai_comment': ai_comment,
            'forecast_lines': forecast_lines,
            'fundamentals': fund_data
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'error': str(e)}, status=500)

def _lazy_fetch_fundamentals(ticker):
    """
    Fetches fundamentals for a single ticker from FMP (Safe, no truncate).
    """
    import requests
    import datetime as dt
    from django.conf import settings
    from django.utils import timezone
    from updatedata.models import FundamentalData, PriceHistory
    
    api_key = settings.FMP_API_KEY
    if not api_key: return

    sym = ticker.symbol
    url = f"https://financialmodelingprep.com/stable/key-metrics-ttm?symbol={sym}&apikey={api_key}"
    
    try:
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            data_list = res.json()
            if data_list and isinstance(data_list, list):
                data = data_list[0]
                
                # Helpers
                def _safe_float(val):
                    try: return float(val) if val is not None else None
                    except: return None
                
                # Get Price for Calcs
                price = None
                try:
                    price = ticker.price_history.latest('date').close
                except: pass
                
                # Extract
                earnings_yield = _safe_float(data.get('earningsYieldTTM'))
                roe = _safe_float(data.get('returnOnEquityTTM'))
                m_cap = _safe_float(data.get('marketCap')) or _safe_float(data.get('marketCapTTM'))

                # Calculate PE/EPS/PBR/BVPS
                pe = (1.0 / earnings_yield) if (earnings_yield and abs(earnings_yield) > 0.000001) else None
                eps = (price * earnings_yield) if (price and earnings_yield) else None
                pbr = (pe * roe) if (pe and roe) else None
                
                # Save
                FundamentalData.objects.update_or_create(
                    symbol=ticker,
                    date=dt.date.today(),
                    defaults={
                        'market_cap': m_cap,
                        'pe_ratio': pe,
                        'pb_ratio': pbr,
                        'return_on_equity_ttm': roe,
                        'eps_ttm': eps,
                        'updated_at': timezone.now()
                    }
                )
                print(f"[Chart] Lazy fetch success for {sym}")
    except Exception as e:
        print(f"[Chart] Lazy fetch failed for {sym}: {e}")
        return JsonResponse({'error': str(e)}, status=500) 


def run_vestiq_manual_scan(request):
    """
    [Manual Trigger]
    Forces a re-scan of the top 500 symbols for the LATEST available date in PriceHistory.
    1. Finds the latest date in DB.
    2. Wipes all DailyPicks for that date.
    3. Re-calculates strategies using fresh PriceHistory data.
    4. Saves new picks.
    5. [NEW] Calculates and caches Stochastics trends for filtered stocks.
    """
    from updatedata.models import Ticker, PriceHistory
    from scanner.models import ScanBatch, ScanRow, DailyPick
    from datetime import datetime, timedelta
    import pandas as pd
    from django.utils import timezone
    from django.db.models import Max
    
    # 1. Identify "Latest Date" from Data (Anchor to key Market Tickers to avoid Crypto/Weekend noise)
    # We prioritize AAPL, then SPY, then MSFT. If global max is used, it might pick a weekend date from Crypto.
    market_proxies = ['AAPL', 'SPY', 'MSFT', 'NVDA']
    max_date_obj = PriceHistory.objects.filter(symbol__symbol__in=market_proxies).aggregate(Max('date'))
    target_date = max_date_obj['date__max']
    
    # Fallback to global max if proxies missing
    if not target_date:
        max_date_obj = PriceHistory.objects.aggregate(Max('date'))
        target_date = max_date_obj['date__max']
    
    if not target_date:
        target_date = timezone.now().date()

    # 2. CLEAR Old Picks AND Reset vestiq_scan flags for this date
    DailyPick.objects.filter(date=target_date).delete()
    PriceHistory.objects.filter(date=target_date).update(vestiq_scan=False, stoch_long_trend=None, stoch_mid_trend=None)

    # 3. Define Universe (From Latest Batch)
    batch = ScanBatch.objects.order_by("-started_at").first()
    if batch:
        top_rows = ScanRow.objects.filter(batch=batch).order_by('-volume')
        symbols = [r.symbol for r in top_rows]
    else:
        symbols = ['AAPL', 'TSLA', 'NVDA', 'AMD', 'MSFT', 'AMZN', 'GOOGL', 'META']
        
    # 4. Fetch History Bulk
    # [FIX] Increased lookback to 730 days (2 years) to ensure Weekly Ichimoku (52 weeks) has enough data.
    # 400 days was borderline for 52-week lag span.
    all_prices = PriceHistory.objects.filter(
        symbol__symbol__in=symbols, 
        date__gte=target_date - timedelta(days=730)
    ).order_by('symbol__symbol', 'date')
    
    saved_count = 0
    filtered_symbols = []  # Track symbols with signals
    
    if all_prices.exists():
        data = list(all_prices.values('symbol__symbol', 'date', 'open', 'high', 'low', 'close', 'volume'))
        df_all = pd.DataFrame(data)
        df_all.rename(columns={'symbol__symbol': 'Symbol', 'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'volume': 'Volume'}, inplace=True)
        
        if not df_all.empty:
            df_all['date'] = pd.to_datetime(df_all['date'])
            grouped = df_all.groupby('Symbol')
            
            new_picks = []
            
            for sym, group in grouped:
                group = group.sort_values('date')
                if len(group) < 60: continue
                
                last_date = group.iloc[-1]['date'].date()
                if last_date != target_date:
                    continue

                # Run Strategy
                signals = calculate_vestiq_strategies(group)
                
                if signals:
                    last_row = group.iloc[-1]
                    price = last_row['Close']
                    strat_name = ", ".join(signals)
                    
                    new_picks.append(DailyPick(
                        date=target_date, 
                        symbol=sym, 
                        strategy=strat_name, 
                        price=price,
                        reason=""
                    ))
                    filtered_symbols.append((sym, group))  # Save for trend calculation
            
            # Bulk Create Picks
            if new_picks:
                DailyPick.objects.bulk_create(new_picks)
                saved_count = len(new_picks)
                
                # Auto-cleanup: Keep only 1 year of data (365 days)
                one_year_ago = target_date - timedelta(days=365)
                deleted_count, _ = DailyPick.objects.filter(date__lt=one_year_ago).delete()
                if deleted_count > 0:
                    print(f"[Auto-cleanup] Deleted {deleted_count} DailyPick records older than {one_year_ago}")
            
            # 5. [NEW] Calculate and Cache Trends for Filtered Stocks Only
            if filtered_symbols:
                ph_updates = []
                for sym, group in filtered_symbols:
                    if len(group) < 60:
                        continue
                    
                    try:
                        # Calculate Stochastics
                        lk, ld = calculate_stoch_slow(group, 20, 12, 12)
                        mk, md = calculate_stoch_slow(group, 10, 6, 6)
                        
                        # Determine trends
                        long_trend = "Neutral"
                        mid_trend = "Neutral"
                        
                        if not lk.empty and not ld.empty and pd.notna(lk.iloc[-1]) and pd.notna(ld.iloc[-1]):
                            long_trend = "Up" if lk.iloc[-1] > ld.iloc[-1] else "Down"
                        
                        if not mk.empty and not md.empty and pd.notna(mk.iloc[-1]) and pd.notna(md.iloc[-1]):
                            mid_trend = "Up" if mk.iloc[-1] > md.iloc[-1] else "Down"
                        
                        # Queue update (will bulk update later)
                        ph_updates.append({
                            'symbol': sym,
                            'long_trend': long_trend,
                            'mid_trend': mid_trend
                        })
                    except Exception as e:
                        print(f"Trend calculation error for {sym}: {e}")
               
                # Bulk update PriceHistory
                for upd in ph_updates:
                    PriceHistory.objects.filter(
                        symbol__symbol=upd['symbol'],
                        date=target_date
                    ).update(
                        vestiq_scan=True,
                        stoch_long_trend=upd['long_trend'],
                        stoch_mid_trend=upd['mid_trend']
                    )

    messages.success(request, f"Vestiq Scan Completed for {target_date}. Found {saved_count} picks (trends cached).")
    
    # Redirect to Vestiq Pick Page for that date
    target_url = f"/scanner/vestiq-pick/?date={target_date.strftime('%Y-%m-%d')}"
    return redirect(target_url)


def ticker_history_api(request, ticker):
    """
    API Endpoint: /scanner/api/ticker-history/<ticker>/
    Returns all historical VestiqPick signals for a given ticker.
    """
    from scanner.models import DailyPick
    from updatedata.models import Ticker
    
    # Normalize ticker to uppercase
    ticker = ticker.upper().strip()
    
    # Try to get company info
    try:
        ticker_obj = Ticker.objects.get(symbol=ticker)
        company_name = ticker_obj.name or ticker
    except Ticker.DoesNotExist:
        company_name = ticker
    
    # Query all DailyPick records for this ticker
    picks = DailyPick.objects.filter(symbol=ticker).order_by('-date')
    
    if not picks.exists():
        return JsonResponse({
            'ticker': ticker,
            'company_name': company_name,
            'found': False,
            'history': []
        })
    
    # Build history list
    history = []
    for pick in picks:
        history.append({
            'date': pick.date.strftime('%Y-%m-%d'),
            'strategy': pick.strategy,
            'price': pick.price,
            'reason': pick.reason or ''
        })
    
    return JsonResponse({
        'ticker': ticker,
        'company_name': company_name,
        'found': True,
        'history': history
    })
