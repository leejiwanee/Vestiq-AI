# ai_advisor/views.py

from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse
from .forms import InvestmentForm
from .services import generate_portfolio # Fixed: use correct function name

import json
from .models import InvestmentProfile, PortfolioReport, TradeRecommendation # Added TradeRecommendation
from .recommendation_service import generate_daily_recommendations, check_macro_filter # New import
from django.utils import timezone # New import
from datetime import timedelta
from django.contrib import messages # New import
from .services import get_chat_response
from django.views.decorators.csrf import csrf_exempt
import yfinance as yf
from scanner.models import ScanRow, ScanBatch
from scanner.company import get_financials_for_ai, get_company_profile
from scanner.gemini_reports import generate_ai_report_structured, _normalize_conclusion
from django.template.loader import render_to_string
import math



def index(request):
    """Main AI Advisor page (Portfolio Input)"""
    if request.method == 'POST':
        form = InvestmentForm(request.POST)
        if form.is_valid():
            # Create profile
            profile = InvestmentProfile.objects.create(**form.cleaned_data)
            
            # Generate Portfolio
            report_data = generate_portfolio(profile)
            
            # Create Report
            report = PortfolioReport.objects.create(
                profile=profile,
                allocation_json=report_data.get('allocation', {}),
                tickers_json=report_data.get('portfolio', []),
                strategy_name=report_data.get('strategy_name', 'Custom Strategy'),
                rationale=report_data.get('analysis_report', '')
            )
            
            # Store ID in session
            request.session['report_id'] = report.id
            
            return redirect('ai_advisor:result') 
    else:
        form = InvestmentForm()

    return render(request, 'ai_advisor/portfolio.html', {'form': form})


def create_profile(request):
    """Deprecated: Redirect to index"""
    return redirect('ai_advisor:input')

def result_view(request):
    report_id = request.session.get('report_id')
    
    if not report_id:
        return redirect('ai_advisor:input')
        
    report = get_object_or_404(PortfolioReport, id=report_id)
    
    context = {
        "profile": report.profile,
        "report": report,
        "allocation": report.allocation_json,
        "portfolio_list": report.tickers_json,
        "strategy_name": report.strategy_name,
        "analysis": report.rationale
    }
    return render(request, "ai_advisor/result.html", context)


# === Trading Recommendations ===

from zoneinfo import ZoneInfo

def trade_recommendations_view(request):
    """
    Display AI trading recommendations.
    Logic (KST Based):
    - Before 4 PM KST: Show Yesterday's recommendations (since today's market hasn't closed/processed fully or user wants previous night's recs).
    - After 4 PM KST: Show Today's recommendations (newly generated for the upcoming US session).
    """
    # 1. Get Current Time in NY (EST/EDT)
    now_utc = timezone.now()
    ny_zone = ZoneInfo("America/New_York")
    now_ny = now_utc.astimezone(ny_zone)
    
    current_hour_ny = now_ny.hour
    today_ny = now_ny.date()
    tomorrow_ny = today_ny + timedelta(days=1)
    
    # 2. Determine Target Date
    # If >= 16:00 NY, we want to show recommendations generated for 'Tomorrow' (Pre-market/Next Day)
    # If < 16:00 NY, we show 'Today' (Active Market)
    if current_hour_ny >= 16:
        target_date = tomorrow_ny
    else:
        target_date = today_ny

    # Detect language
    from django.utils.translation import get_language
    lang_code = get_language()
    language = 'en' if lang_code == 'en' else 'ko'

    # 3. Fetch recommendations for the specific target date ONLY
    all_recs = TradeRecommendation.objects.filter(
        date=target_date, 
        language=language
    ).order_by('-technical_score')
    
    # Separate BUY from others
    buy_recs = all_recs.filter(recommendation='BUY')
    other_recs = all_recs.exclude(recommendation='BUY')  # HOLD/AVOID
    
    # Get macro context
    macro = check_macro_filter()
    
    context = {
        'buy_recommendations': buy_recs,
        'other_recommendations': other_recs,
        'macro': macro,
        'today': today_ny, # Show NY date
        'display_date': target_date,
        'has_recommendations': all_recs.exists(),
        'has_buy_recs': buy_recs.exists(),
        'cutoff_time_passed': current_hour_ny >= 16
    }
    
    return render(request, 'ai_advisor/recommendations.html', context)


def generate_recommendations_api(request):
    """
    API: Trigger generation of recommendations
    Logic (NY Based):
    - If >= 16:00 NY, generate for Tomorrow.
    - Else, generate for Today.
    """
    if request.method == 'POST':
        try:
            from django.utils.translation import get_language
            lang_code = get_language()
            language = 'en' if lang_code == 'en' else 'ko'

            # Determine target date based on NY
            now_utc = timezone.now()
            ny_zone = ZoneInfo("America/New_York")
            now_ny = now_utc.astimezone(ny_zone)
            
            if now_ny.hour >= 16:
                target_date = now_ny.date() + timedelta(days=1)
            else:
                target_date = now_ny.date()

            # Check if already generated
            existing = TradeRecommendation.objects.filter(date=target_date, language=language)
            
            if existing.exists():
                return JsonResponse({
                    'success': False,
                    'message': f'{target_date} 추천이 이미 존재합니다.',
                    'count': existing.count()
                })
            
            # Generate new recommendations
            recommendations = generate_daily_recommendations(language=language, target_date=target_date)

            
            return JsonResponse({
                'success': True,
                'message': f'{len(recommendations)}개의 추천을 생성했습니다.',
                'count': len(recommendations)
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=500)
    
    return JsonResponse({'error': 'POST method required'}, status=400)


# === AI Stock Inspector ===

from .inspector_service import get_stock_data, calculate_indicators, analyze_stock_gemini
# import json # Already imported at the top

def inspector_view(request):
    """AI Stock Inspector Page"""
    return render(request, 'ai_advisor/inspector.html')

def api_analyze_stock(request):
    """API for AI Stock Analysis"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            symbol = data.get('symbol', '').upper()
            
            if not symbol:
                return JsonResponse({'error': 'Symbol is required'}, status=400)
                
            # 1. Get Data
            stock_data, error = get_stock_data(symbol)
            if error:
                return JsonResponse({'error': error}, status=404)
                
            # 2. Calculate Indicators
            indicators = calculate_indicators(stock_data['df'])
            
            # 3. AI Analysis
            # Language is detected inside analyze_stock_gemini, but we can pass it if we update the service signature
            # The service signature was NOT updated to accept language in the previous step (I checked inspector_service.py and it detects language inside).
            # But inspector_service.py ALREADY detects language inside analyze_stock_gemini.
            # So this is fine.
            
            analysis = analyze_stock_gemini(symbol, stock_data['company_name'], indicators)
            
            return JsonResponse({
                'symbol': symbol,
                'company': stock_data['company_name'],
                'price': stock_data['current_price'],
                'analysis': analysis,
                'indicators': {k: float(v) for k, v in indicators.items()}, # Ensure float serialization
                'news': stock_data.get('news', [])
            })
            
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
            
    return JsonResponse({'error': 'POST required'}, status=400)

# === Email Service ===
from .email_utils import generate_portfolio_pdf, send_email_with_pdf
from datetime import datetime

def send_portfolio_email(request):
    """
    Sends the generated portfolio to the user's email with PDF attachment.
    """
    if request.method == 'POST':
        email = request.POST.get('email')
        if not email:
            return JsonResponse({'success': False, 'error': 'Email is required'})
            
        data = request.session.get('portfolio_result')
        if not data:
            return JsonResponse({'success': False, 'error': 'No portfolio found in session'})
            
        try:
            profile_data = data['profile']
            report_data = data['report']
            profile = InvestmentProfile(**profile_data)
            
            # Generate PDF
            pdf_bytes = generate_portfolio_pdf(profile, report_data)
            
            # Email Details
            subject = f"Your AI Investment Portfolio: {report_data.get('strategy_name')}"
            body = f"""
            Hello,
            
            Attached is your AI-generated investment portfolio report.
            
            Strategy: {report_data.get('strategy_name')}
            Target Return: {profile.target_return}%
            
            Best regards,
            Vestiq
            """
            filename = f"Portfolio_{datetime.now().strftime('%Y%m%d')}.pdf"
            
            # Send Email
            send_email_with_pdf(email, subject, body, pdf_bytes, filename)
            
            return JsonResponse({'success': True, 'message': 'Email sent successfully'})
            
        except Exception as e:
            print(f"Email Error: {e}")
            return JsonResponse({'success': False, 'error': str(e)})
            
    return JsonResponse({'error': 'POST required'}, status=400)


# === AI Long-Term Picks ===

from .long_term_service import get_long_term_picks

def long_term_view(request):
    """AI Long-Term Investment Page"""
    return render(request, 'ai_advisor/long_term.html')

def api_long_term_picks(request):
    """API for fetching long-term picks"""
    if request.method == 'POST':
        try:
            from django.utils.translation import get_language
            lang_code = get_language()
            language = 'en' if lang_code == 'en' else 'ko'
            
            data = get_long_term_picks(language=language)
            return JsonResponse(data)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
            return JsonResponse({'error': str(e)}, status=500)
    return JsonResponse({'error': 'POST required'}, status=400)


# -------------------------------------------------------------------------
# Chat with Your Portfolio (Floating Widget)
# -------------------------------------------------------------------------

def chat_api(request):
    """
    채팅 메시지를 처리하는 API 엔드포인트
    """
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            question = data.get('message')
            report_id = data.get('report_id') # 현재 보고 있는 리포트 ID

            if not question or not report_id:
                return JsonResponse({'error': '잘못된 요청입니다.'}, status=400)

            # 해당 리포트 가져오기
            report = PortfolioReport.objects.get(id=report_id)
            
            # AI 답변 생성
            answer = get_chat_response(report, question)
            
            return JsonResponse({'answer': answer})
            
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
            
    return JsonResponse({'error': 'POST method required'}, status=405)


# -------------------------------------------------------------------------
# AI Report (Any Ticker)
# -------------------------------------------------------------------------

def report_input_view(request):
    """
    Page to input ticker for AI Report
    """
    return render(request, "ai_advisor/report_input.html")


def report_result_view(request, symbol):
    """
    Container page for AI Report result
    """
    symbol = symbol.upper()
    return render(request, "ai_advisor/report_result.html", {"symbol": symbol})


def api_ai_report_advisor(request, symbol):
    """
    API to generate AI Report for ANY ticker.
    1. Checks if data exists in Scanner DB (latest batch).
    2. If not, fetches real-time data from Yahoo Finance.
    3. Generates AI Report.
    """
    symbol = symbol.upper()
    
    # 1. Try to get data from Scanner DB first (Fastest)
    batch = ScanBatch.objects.order_by("-started_at").first()
    row = None
    if batch:
        row = ScanRow.objects.filter(batch=batch, symbol=symbol).first()
        
    stats = {}
    company = {}
    
    if row:
        # Use existing data
        close = getattr(row, "close", None)
        volume = getattr(row, "volume", None)
        prev_volume = getattr(row, "prev_volume", None)
        price_change_pct = getattr(row, "price_change_pct", None)
        vol_change_pct = getattr(row, "vol_change_pct", None)
        
        # Recalculate if missing
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
        # 2. Fetch Real-time Data from Yahoo Finance
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="5d")
            
            if hist.empty:
                return JsonResponse({"error": f"No data found for {symbol}"}, status=404)
                
            # Current Data
            current = hist.iloc[-1]
            prev = hist.iloc[-2] if len(hist) > 1 else current
            
            close = float(current["Close"])
            prev_close = float(prev["Close"])
            volume = int(current["Volume"])
            prev_volume = int(prev["Volume"])
            
            price_change_pct = ((close - prev_close) / prev_close) * 100.0
            vol_change_pct = ((volume - prev_volume) / prev_volume) * 100.0 if prev_volume > 0 else 0.0
            
            stats = {
                "close": close,
                "price_change_pct": price_change_pct,
                "vol_change_pct": vol_change_pct,
                "volume": volume,
                "prev_volume": prev_volume,
                # No scanner flags available for non-scanned stocks
                "f_volume": None,
                "f_volatility": None,
                "f_trend": None,
                "f_pattern": None,
                "f_momentum": None,
            }
            
            # Company Info
            info = ticker.info
            company = {
                "name": info.get("shortName") or info.get("longName") or symbol,
                "sector": info.get("sector", ""),
                "industry": info.get("industry", ""),
            }
            
        except Exception as e:
            return JsonResponse({"error": f"Failed to fetch data: {str(e)}"}, status=500)

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
        return JsonResponse({"error": error}, status=500)

    # Extract fair value
    fair_value = ai_report.get("fair_value") if ai_report else None
    
    # Reuse the scanner partial template
    context = {
        "symbol": symbol,
        "row": row, # Might be None
        "stats": stats,
        "ai_report": ai_report,
        "fair_value": fair_value,
        "ai_disabled": False,
        "company_name": company["name"], # Ensure company name is passed
        "sector": company["sector"],
        "industry": company["industry"],
    }
    
    html = render_to_string("scanner/partials/ai_report_content.html", context, request=request)
    
    return JsonResponse({"html": html})
