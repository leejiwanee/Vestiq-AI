import requests
from django.core.cache import cache
from django.core.cache import cache
import logging

logger = logging.getLogger(__name__)

def get_market_weather(stats, sector_stats=None):
    """
    Calculate Vestiq Macro Score (Composite Sentiment) based on:
    1. Fear & Greed (Base, 35%) - Fetched via package
    2. VIX (Volatility, 20%)
    3. Momentum (SPX, 15%)
    4. Risk Appetite (Bitcoin, 15%)
    5. Macro Stress (Yields + Oil + Dollar, 15%)
    
    Returns a dict with status, icon, desc, score, color.
    """
    import fear_and_greed

    # 1. Fetch Inputs from 'stats'
    # stats = {'TICKER': {'price': x, 'pct': y}, ...}
    
    # A. Fear & Greed (35%)
    try:
        fg_data = fear_and_greed.get()
        fg_score = float(fg_data.value)
    except:
        fg_score = 50.0

    # B. VIX (20%) - Inverse (Low VIX = High Score/Greed)
    val_vix = stats.get('^VIX', {}).get('price', 20.0)
    # Norm: 10(Greed) to 35(Fear). 
    vix_score = 100 - ((val_vix - 10) / (35 - 10) * 100)
    vix_score = max(0, min(100, vix_score))

    # C. Momentum (SPX) (15%) - Using Pct Change as proxy for RSI (simplification for stats dict)
    # Ideally we need history for RSI. 
    # Fallback: Use PCT change. If > 0.5% -> Bullish (60+). If < -0.5% -> Bearish.
    # But 'stats' only has daily pct.
    # Let's use simple logic: If pct > 0: +Points.
    # Or rely on VIX/FG which capture momentum partially.
    # Better: Use 'price' vs 'prev' if available, but we only have 1-day change in stats usually.
    # Let's use the 'pct' from stats.
    val_spx_pct = stats.get('^GSPC', {}).get('pct', 0.0)
    # Map -2% to +2% -> 0 to 100? No, that's daily.
    # Base 50. +1% -> 70. -1% -> 30.
    mom_score = 50 + (val_spx_pct * 20)
    mom_score = max(0, min(100, mom_score))

    # D. Risk Appetite (BTC) (15%)
    val_btc_pct = stats.get('BTC-USD', {}).get('pct', 0.0)
    btc_score = 50 + (val_btc_pct * 10) # BTC more volatile
    btc_score = max(0, min(100, btc_score))

    # E. Macro Stress (15%) - Yields, Dollar, Oil
    val_tnx = stats.get('^TNX', {}).get('price', 3.5)
    val_dxy = stats.get('DX-Y.NYB', {}).get('price', 100.0)
    val_oil = stats.get('CL=F', {}).get('price', 70.0)

    tnx_score = 100 - ((val_tnx - 3.5) / (5.0 - 3.5) * 100)
    dxy_score = 100 - ((val_dxy - 100) / (110 - 100) * 100)
    oil_score = 100 - ((val_oil - 65) / (90 - 65) * 100)
    
    avg_stress = (tnx_score + dxy_score + oil_score) / 3
    macro_stress_score = max(0, min(100, avg_stress))

    # Composite Score
    final_score = (
        (fg_score * 0.35) + 
        (vix_score * 0.20) + 
        (mom_score * 0.15) + 
        (btc_score * 0.15) + 
        (macro_stress_score * 0.15)
    )
    score = int(final_score)

    # Determine Weather Status
    # <25 Extreme Fear, <45 Fear, <55 Neutral, <75 Greed, >75 Extreme Greed
    if score < 25:
        weather = {
            "icon": "bi bi-lightning-charge-fill", "status": "Aggressive Buy", 
            "desc": "Extreme Fear: Oversold Bounce Likely",
            "bg_gradient": "#e2e8f0", "text_color": "#1e293b", "score": score
        }
    elif score < 45:
        weather = {
            "icon": "bi bi-basket-fill", "status": "Buy (Accumulate)", 
            "desc": "Fear: Good Entry Zone",
            "bg_gradient": "#e2e8f0", "text_color": "#1e293b", "score": score
        }
    elif score <= 55:
        weather = {
            "icon": "bi bi-pause-circle-fill", "status": "Neutral / Hold", 
            "desc": "Market Indecisive",
            "bg_gradient": "#e2e8f0", "text_color": "#1e293b", "score": score
        }
    elif score < 75:
        weather = {
            "icon": "bi bi-exclamation-triangle-fill", "status": "Caution", 
            "desc": "Greed: Risk Elevation",
            "bg_gradient": "#e2e8f0", "text_color": "#1e293b", "score": score
        }
    else:
        weather = {
            "icon": "bi bi-shield-slash-fill", "status": "Avoid", 
            "desc": "Extreme Greed: High Risk",
            "bg_gradient": "#e2e8f0", "text_color": "#1e293b", "score": score
        }
        
    return weather

# ---------------------------------------------------------
# GEMINI MARKET WEATHER
# ---------------------------------------------------------
import os
import json
import requests
from datetime import datetime, time, timedelta
from django.utils import timezone
from django.conf import settings

import feedparser
import urllib3

# -----------------------------------------
# NEWS FETCHER
# -----------------------------------------
def fetch_news(limit=10):
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    UA = "Mozilla/5.0 QuantDash/1.0"

    FEEDS = [
        ("CNBC", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10001147"),
        ("MarketWatch", "https://www.marketwatch.com/rss/topstories"),
        ("NYT Business", "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml"),
    ]

    session = requests.Session()
    session.headers.update({"User-Agent": UA})

    items = []

    for source, url in FEEDS:
        try:
            r = session.get(url, verify=False, timeout=5)
            feed = feedparser.parse(r.text)
        except Exception as e:
            logger.error(f"Failed to fetch news from {source} ({url}): {e}")
            continue

        for e in feed.entries[:limit]:
            title = getattr(e, "title", "").strip()
            link = getattr(e, "link", "").strip()
            if title and link:
                items.append({"title": title, "url": link, "source": source})

    return items[:limit]

# -----------------------------------------
# TIINGO PRICE FETCHER (Fallback)
# -----------------------------------------
def get_tiingo_last_price(ticker):
    """
    Fetches the last closing price AND percentage change from Tiingo API.
    Returns: (price, pct_change)
    """
    try:
        api_key = os.getenv("TIINGO_API_KEY")
        if not api_key:
            return None, 0.0
        
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Token {api_key}'
        }
        
        # Calculate start date (ensure we get at least 2 days for pct change)
        start_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
        
        # Tiingo End-of-Day Endpoint with history
        url = f"https://api.tiingo.com/tiingo/daily/{ticker}/prices?startDate={start_date}&sort=date"
        
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data and isinstance(data, list) and len(data) > 0:
                # Get latest
                latest = data[-1]
                price = float(latest.get('close', 0))
                
                pct = 0.0
                if len(data) >= 2:
                    prev = float(data[-2].get('close', 0))
                    if prev != 0:
                        pct = ((price - prev) / prev) * 100
                
                return price, pct
                
        return None, 0.0
    except Exception as e:
        logger.error(f"Tiingo Fetch Failed for {ticker}: {e}")
        return None, 0.0

def get_gemini_market_weather(stats, theme_stats=None, sector_stats=None):
    """
    Generates a market summary using Gemini (via REST API).
    Rotates at 4:00 PM ET.
    """
    import pytz
    
    # 1. Determine Cache Key based on Market Window (US/Eastern)
    est = pytz.timezone('US/Eastern')
    now_est = datetime.now(est)
    
    # Market Hours: 10:00 AM - 4:00 PM ET
    # Logic:
    # - If Weekend (Sat/Sun): Use LAST Friday's FINAL.
    # - If Weekday < 10 AM: Use YESTERDAY's FINAL.
    # - If Weekday 10 AM <= Time < 4 PM: Use HOURLY key (e.g., 2025-12-12_10).
    # - If Weekday >= 4 PM: Use TODAY's FINAL.

    def get_last_trading_day_final(dt):
        # Go back 1 day until we find a weekday
        d = dt.date() - timedelta(days=1)
        while d.weekday() >= 5: # 5=Sat, 6=Sun
            d -= timedelta(days=1)
        return f"gemini_market_weather_v9_{d}_FINAL"

    is_weekend = now_est.weekday() >= 5
    current_hour = now_est.hour
    today_str = now_est.date().isoformat()
    
    if is_weekend:
        # Weekend -> Last Trading Day Final
        cache_key = get_last_trading_day_final(now_est)
    else:
        # Weekday
        if current_hour < 10:
            # Pre-market -> Yesterday Final
            cache_key = get_last_trading_day_final(now_est)
        elif 10 <= current_hour < 16:
            # Market Open -> Hourly Update
            cache_key = f"gemini_market_weather_v9_{today_str}_{current_hour}"
        else:
            # Post-market (>= 16:00) -> Today Final
            cache_key = f"gemini_market_weather_v9_{today_str}_FINAL" 
    
    # Use explicit JSON file caching
    import json
    import os
    
    cache_dir = os.path.join(settings.BASE_DIR, '.gemini_cache')
    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir, exist_ok=True)
        
    cache_file = os.path.join(cache_dir, f"{cache_key}.json")
    
    # Check if cache exists and is fresh
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                cached_data = json.load(f)
                
            # Check expiration logic
            last_updated_str = cached_data.get('last_updated_ts') # Timestamp for logic
            
            # If valid cache, use it
            if last_updated_str:
                last_ts = datetime.fromisoformat(last_updated_str)
                # If cached data is from the same cycle date and not expired
                # (Simple rule: Cache is valid for this cycle date until the next 4 PM)
                
                # However, for simplicity and user experience:
                # If the file exists for this specific CYCLE DATE key, it is valid contextually.
                # We just need to update the display time.
                
                logger.info(f"Gemini JSON Cache HIT: {cache_file}")
                
                # Update display time to NOW if it's missing or old, just to show freshness? 
                # No, user asked "Why does it update every refresh?". 
                # It SHOULD NOT update every refresh if the content is the same.
                
                # So we KEEP the original generated time to show stable generation.
                # UNLESS 'last_updated' is missing.
                if 'last_updated' not in cached_data:
                     import pytz
                     est = pytz.timezone('US/Eastern')
                     now_est = datetime.now(est)
                     cached_data['last_updated'] = now_est.strftime("%Y-%m-%d %I:%M %p EST")
                
                return cached_data
        except Exception as e:
            logger.error(f"Failed to load cache {cache_file}: {e}")
            
    logger.info(f"Gemini JSON Cache MISS: {cache_file} - Generating new summary...")

    # ... (Data Preparation) ...

    # Analyze for specific questions
    special_instructions = ""
    vix_pct = stats.get('^VIX', {}).get('pct', 0)
    
    if vix_pct > 2.0:
         special_instructions += "IMPORTANT: VIX is rising today. EXPLICITLY explain the reason for this volatility based on the news.\n"
         
    # 2. Build Market Data String
    lines = []
    for ticker, info in stats.items():
        # Clean ticker name
        short_name = ticker.replace("=F", "").replace("=X", "").replace("-USD", "")
        price = info.get('price')
        pct = info.get('pct')
        
        # Safety check: Ensure values are floats (handle None)
        if price is None: price = 0.0
        if pct is None: pct = 0.0
        
        lines.append(f"{short_name}: {price:.2f} ({pct:+.2f}%)")
        
    market_data_str = "\n".join(lines)
    
    # 2.5 Build Sector & Theme Data String
    if sector_stats:
        lines.append("\n[Sectors]")
        for s in sector_stats[:5]: # Top 5
             lines.append(f"{s['name']}: {s['change']}")
             
    if theme_stats:
        lines.append("\n[Themes]")
        for t in theme_stats[:5]:
            lines.append(f"{t['name']}: {t['change']}")

    # 3. Fetch News for Context
    news_items = fetch_news(limit=5)
    news_lines = [f"- {item['title']}" for item in news_items]
    news_str = "\n".join(news_lines)

    # 3. Call Gemini REST API
    try:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return None
            
        model_id = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={api_key}"
        
        prompt = f"""
        You are a witty, sharp, and engaging financial commentator (like a mix of Bloomberg and a cool financial blog).
        Analyze the following market data AND news headlines to provide a summary of "What's going on with the markets today?".
        
        {market_data_str}

        {news_str}
        
        {special_instructions}
        
        Requirements:
        1. Provide the summary in TWO languages: English and Korean.
        2. Tone: Unique, Insightful, slightly Witty/Fun but professional.
        3. Structure (JSON):
           - title: Catchy headline.
           - summary: Short, punchy summary (2-3 sentences).
           - snapshot: List of 3-4 key indices/assets with a VERY short comment. MUST INCLUDE S&P 500, Nasdaq, Russell 2000, Bitcoin. Use FRIENDLY NAMES.
           - macro: A section dedicated to "Macro Economy".
             IMPORTANT:
             - You MUST USE the provided "News Headlines" and "Market Data" to form these points. Do not hallucinate generic reasons.
             - CRITICAL: Do NOT attribute broad market volatility (VIX rising, S&P 500 dropping) to single-stock news (like M&A, Earnings, or CEO changes) UNLESS it is a "Magnificent 7" stock (Apple, Nvidia, Microsoft, etc.).
             - If no specific macro news explains the VIX, simply state "Volatility has increased amidst general market uncertainty" rather than making up a reason.
             - Format: A list of 3-5 high-impact bullet points.
             - **MANDATORY FORMATTING**: Start each point with a short, bold title followed by a colon. 
               Example: "<b>Rising Bond Yields</b>: The 10-year treasury yield spiked..."
               Use HTML <b> tags for the title part.
           - sectors: List of top 3 performing sectors and bottom 3 performing sectors.
             IMPORTANT: For the 'ko' (Korean) version, YOU MUST TRANSLATE the sector names into Korean.
           - themes: List of top 3 performing themes.
        
        JSON Structure:
        {{
            "en": {{
                "title": "...",
                "summary": "...",
                "snapshot": [ {{"label": "...", "value": "...", "comment": "..."}} ],
                "macro": {{ "title": "Macro Vibes", "points": ["...", "...", "..."] }},
                "sectors": [ {{"name": "...", "change": "...", "comment": "..."}} ],
                "themes": [ {{"name": "...", "change": "...", "comment": "..."}} ]
            }},
            "ko": {{
                "title": "...",
                "summary": "...",
                "snapshot": [ {{"label": "...", "value": "...", "comment": "..."}} ],
                "macro": {{ "title": "매크로 경제", "points": ["...", "...", "..."] }},
                "sectors": [ {{"name": "...", "change": "...", "comment": "..."}} ],
                "themes": [ {{"name": "...", "change": "...", "comment": "..."}} ]
            }}
        }}
        """
        
        payload = {
            "contents": [{
                "parts": [{"text": prompt}]
            }],
            "generationConfig": {
                "response_mime_type": "application/json"
            }
        }
        
        response = None
        last_err = None
        for model in [model_id, "gemini-2.5-flash-lite", "gemini-2.0-flash"]:
            target_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            try:
                response = requests.post(target_url, json=payload, timeout=60)
                response.raise_for_status()
                break
            except Exception as ex:
                last_err = ex
                continue
        if response is None:
            raise last_err
        
        data = response.json()
        
        if "candidates" in data and data["candidates"]:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            result = json.loads(text)
            
            # Add timestamp in EST
            import pytz
            est = pytz.timezone('US/Eastern')
            now_est = datetime.now(est)
            result['last_updated'] = now_est.strftime("%Y-%m-%d %I:%M %p EST")
            result['last_updated_ts'] = now_est.isoformat()

            # Save to JSON Cache
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
                
            logger.info(f"Gemini JSON Cache SET: {cache_file}")
            return result
            
    except Exception as e:
        logger.error(f"Gemini Market Weather Failed: {e}")
        return None
