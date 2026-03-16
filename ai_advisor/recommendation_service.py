"""
AI Trading Recommendation Service
Combines Scanner results, News sentiment, and Gemini AI
"""
import os
import json
import re
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from django.utils import timezone
from django.db.models import Q
import yfinance as yf
from google import genai

from scanner.models import ScanBatch, ScanRow
from news.models import DailySummary
from news.gemini_news import _fetch_market_data
from .models import TradeRecommendation


MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


def _client():
    key = os.getenv("GEMINI2_API_KEY")
    if not key:
        return None
    return genai.Client(api_key=key)


def _extract_json(text: str) -> Optional[dict]:
    """Extract JSON from Gemini response"""
    text = (text or "").strip()
    s, e = text.find("{"), text.rfind("}")
    if s == -1 or e == -1 or e <= s:
        return None
    try:
        return json.loads(text[s:e + 1])
    except Exception:
        cleaned = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
        s, e = cleaned.find("{"), cleaned.rfind("}")
        if s != -1 and e != -1 and e > s:
            return json.loads(cleaned[s:e + 1])
        return None


def get_scanner_candidates() -> List[Dict[str, Any]]:
    """
    Get top candidates from Scanner
    Returns: List of stock data dicts with technical indicators
    """
    # Get latest scan batch (removed completed=True filter as field doesn't exist)
    latest_batch = ScanBatch.objects.order_by('-started_at').first()
    
    if not latest_batch:
        return []
    
    # Filter: triggered stocks with good momentum
    rows = ScanRow.objects.filter(
        batch=latest_batch,
        trigger=True
    ).filter(
        Q(f_momentum=True) | Q(f_trend=True)  # Has upward momentum or trend
    ).exclude(
        price_change_pct__lt=-5.0  # Exclude crashing stocks
    )
    
    # Calculate technical score for each
    candidates = []
    for row in rows:
        # Score components
        vol_score = min(50, (row.vol_change_pct or 0) * 10)  # Cap at 50
        price_score = (row.price_change_pct or 0) * 5  # Price momentum
        filter_score = sum([
            row.f_volume or False,
            row.f_volatility or False,
            row.f_trend or False,
            row.f_pattern or False,
            row.f_momentum or False,
            row.f_value or False,
        ]) * 8.33  # Each filter worth 8.33 points
        
        total_score = vol_score + price_score + filter_score
        
        candidates.append({
            'symbol': row.symbol,
            'company_name': row.company or row.symbol,
            'current_price': row.close,
            'volume': row.volume,
            'price_change_pct': row.price_change_pct,
            'vol_change_pct': row.vol_change_pct,
            'filters_triggered': [f for f in ['volume', 'volatility', 'trend', 'pattern', 'momentum', 'value']
                                   if getattr(row, f'f_{f}', False)],
            'technical_score': round(total_score, 2)
        })
    
    # Sort by score and return top 10
    candidates.sort(key=lambda x: x['technical_score'], reverse=True)
    return candidates[:10]


def check_macro_filter() -> Dict[str, Any]:
    """
    Check market mood using Home App's Market Weather Logic (Technical Only).
    Returns: {mood, score, should_trade, max_positions}
    """
    from home.services import get_market_weather
    
    # 1. Fetch Market Data (Indices + Gold)
    tickers = ["^GSPC", "^IXIC", "^VIX", "GC=F"]
    stats = {}
    
    try:
        data = yf.download(tickers, period="5d", progress=False, auto_adjust=True)['Close']
        # Handle MultiIndex columns if necessary (yfinance > 0.2)
        if hasattr(data.columns, 'levels'): 
             # Flatten or access properly. For now, simple loop assuming simple columns or handling errors
             pass

        # Re-fetch individually to be safe/simple (or optimize later)
        # yfinance download structure can be tricky with multi-tickers
        for tk in tickers:
            t = yf.Ticker(tk)
            hist = t.history(period="5d")
            if len(hist) >= 2:
                latest = hist['Close'].iloc[-1]
                prev = hist['Close'].iloc[-2]
                pct = ((latest - prev) / prev) * 100
                stats[tk] = {'price': latest, 'pct': pct}
    except Exception as e:
        print(f"Market Data Fetch Error: {e}")

    # 2. Fetch Sector Data
    SECTOR_ETFS = [
        "XLK", "XLI", "XLC", "XLF", "XLY", "XLRE", "XLV", "XLP", "XLU", "XLB", "XLE"
    ]
    sector_stats = {}
    try:
        # Batch download sectors
        s_data = yf.download(SECTOR_ETFS, period="2d", progress=False, auto_adjust=True)['Close']
        
        if not s_data.empty and len(s_data) >= 2:
            latest_row = s_data.iloc[-1]
            prev_row = s_data.iloc[-2]
            
            for tk in SECTOR_ETFS:
                try:
                    curr = latest_row[tk]
                    prev = prev_row[tk]
                    if prev > 0:
                        pct = ((curr - prev) / prev) * 100
                        sector_stats[tk] = pct # Use ticker as key for simplicity
                except: pass
    except Exception as e:
        print(f"Sector Data Fetch Error: {e}")

    # 3. Calculate Weather
    # Check if we have enough data (at least market stats)
    if not stats:
        return {
            'mood': 'Neutral',
            'score': 50,
            'should_trade': True,
            'max_positions': 5,
            'message': 'Market Data Unavailable',
            'market_data': {},
            'error': True  # Flag for UI
        }
        
    weather = get_market_weather(stats, sector_stats)
    score = weather.get('score', 50)
    status = weather.get('status', 'Cloudy')
    
    # Map Weather to Mood
    if score >= 60:
        mood = "Bullish"
    elif score <= 40:
        mood = "Bearish"
    else:
        mood = "Neutral"
        
    # Decision logic
    if mood == "Bearish" and score < 25: # Storm
        should_trade = False
        max_positions = 0
        message = "⚠️ 시장 폭락 (Storm) - 거래 보류 권장"
    elif mood == "Bearish": # Rainy
        should_trade = True
        max_positions = 3
        message = "⚡ 약세장 (Rainy) - 보수적 진행 (3개 종목만)"
    elif mood == "Bullish": # Sunny/Partly Cloudy
        should_trade = True
        max_positions = 10
        message = "✅ 강세장 (Sunny) - 적극 투자 권장"
    else: # Cloudy
        should_trade = True
        max_positions = 5
        message = "☁️ 중립 시장 (Cloudy) - 선별적 접근"
    
    # 4. Prepare Friendly Market Data for UI
    TICKER_MAP = {
        "^GSPC": "S&P 500",
        "^IXIC": "Nasdaq",
        "^VIX": "VIX",
        "GC=F": "Gold"
    }
    
    ui_market_data = {}
    for tk, data in stats.items():
        name = TICKER_MAP.get(tk, tk)
        # Flatten structure if needed or keep as is
        # stats[tk] = {'price': ..., 'pct': ...}
        # We want to pass this to template which expects data.close, data.change_pct
        ui_market_data[name] = {
            'close': round(data['price'], 2),
            'change_pct': round(data['pct'], 2)
        }

    return {
        'mood': mood,
        'score': score,
        'should_trade': should_trade,
        'max_positions': max_positions,
        'message': message,
        'market_data': ui_market_data, # Pass friendly names
        'error': False
    }


def generate_price_targets_ai(candidate: Dict[str, Any], macro_context: Dict[str, Any], language='ko') -> Optional[Dict[str, Any]]:
    """
    Use Gemini AI to calculate entry/stop/target prices
    """
    client = _client()
    if not client:
        return None
    
    # Format market context
    market_summary = ""
    if macro_context.get('market_data'):
        market_summary = "\n".join([
            f"- {name}: {data['close']} ({data['change_pct']:+.2f}%)"
            for name, data in macro_context['market_data'].items()
        ])
    
    from .prompts import get_recommendation_prompt
    
    prompt = get_recommendation_prompt(
        candidate['symbol'],
        candidate['company_name'],
        candidate['current_price'],
        candidate['price_change_pct'],
        candidate['vol_change_pct'],
        candidate['filters_triggered'],
        candidate['technical_score'],
        macro_context['mood'],
        macro_context['score'],
        market_summary,
        language=language
    )

    
    try:
        response = client.models.generate_content(model=MODEL, contents=prompt)
        text = getattr(response, "text", "") or ""
        data = _extract_json(text)
        return data
    except Exception as e:
        print(f"Gemini AI error for {candidate['symbol']}: {e}")
        return None


def generate_daily_recommendations(language='ko', target_date=None) -> List[TradeRecommendation]:
    """
    Main function: Generate today's trading recommendations
    Returns: List of saved TradeRecommendation objects
    """
    if target_date is None:
        target_date = timezone.now().date()
    
    # Check if already generated today for this language
    existing = TradeRecommendation.objects.filter(date=target_date, language=language).exists()
    if existing:
        print(f"Already generated recommendations for {target_date} ({language})")
        return list(TradeRecommendation.objects.filter(date=target_date, language=language))
    
    # Step 1: Get Scanner candidates
    candidates = get_scanner_candidates()
    
    if not candidates:
        print("No scanner candidates found")
        return []
    
    # Step 2: Check macro filter
    macro = check_macro_filter()
    
    if not macro['should_trade']:
        print(f"Trading halted: {macro['message']}")
        return []
    
    # Limit candidates based on macro
    candidates = candidates[:macro['max_positions']]
    
    # Step 3: Generate AI recommendations for each candidate
    recommendations = []
    
    for candidate in candidates:
        # Pass language to AI generator
        ai_result = generate_price_targets_ai(candidate, macro, language=language)
        
        if not ai_result:
            continue
        
        # Calculate risk/reward ratio
        rr_ratio = None
        if ai_result.get('entry_price') and ai_result.get('stop_loss') and ai_result.get('take_profit'):
            entry = ai_result['entry_price']
            sl = ai_result['stop_loss']
            tp = ai_result['take_profit']
            risk = abs(entry - sl)
            reward = abs(tp - entry)
            rr_ratio = reward / risk if risk > 0 else None
        
        # Create TradeRecommendation object
        rec = TradeRecommendation.objects.create(
            date=target_date,
            symbol=candidate['symbol'],
            company_name=candidate['company_name'],
            current_price=candidate['current_price'],
            volume=candidate.get('volume'),
            price_change_pct=candidate.get('price_change_pct', 0),
            vol_change_pct=candidate.get('vol_change_pct', 0),
            market_mood=macro['mood'],
            market_mood_score=macro['score'],
            recommendation=ai_result.get('recommendation', 'HOLD'),
            entry_price=ai_result.get('entry_price'),
            stop_loss=ai_result.get('stop_loss'),
            take_profit=ai_result.get('take_profit'),
            position_size=ai_result.get('position_size') or '1-2%',  # Default if None
            rationale=ai_result.get('rationale') or 'AI 분석 중',
            technical_score=candidate['technical_score'],
            filters_triggered=candidate['filters_triggered'],
            risk_reward_ratio=rr_ratio,
            confidence_level=ai_result.get('confidence', 'Medium'),
            language=language  # Save language
        )
        
        recommendations.append(rec)
        print(f"✅ Generated recommendation for {candidate['symbol']} ({language})")
    
    return recommendations
