import os
import json
import re
from typing import Optional, Dict, Any
from google import genai
from django.utils import timezone
from .models import NewsArticle
import yfinance as yf

from datetime import datetime, time, timedelta
from .models import NewsArticle, DailySummary

MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

def _client():
    key = os.getenv("GEMINI2_API_KEY")
    if not key:
        return None
    return genai.Client(api_key=key)

SCHEMA = (
    '{'
    '"mood": "Bullish" | "Bearish" | "Neutral", '
    '"score": number, '
    '"summary": string, '
    '"key_factors": [string]'
    '}'
)

def _extract_json(text: str) -> Optional[dict]:
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

def _fetch_market_data() -> Dict[str, Any]:
    """
    Fetch real-time data for major market indices.
    Returns: {"SPY": {"change_pct": -2.5, "close": 450.0}, ...}
    """
    indices = {
        "^GSPC": "S&P 500",
        "^IXIC": "NASDAQ",
        "^VIX": "VIX (Fear Index)"
    }
    
    market_data = {}
    
    for symbol, name in indices.items():
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="5d")  # Get last 5 days to ensure we have data
            
            if len(hist) >= 2:
                latest = hist.iloc[-1]
                previous = hist.iloc[-2]
                
                change_pct = ((latest['Close'] - previous['Close']) / previous['Close']) * 100
                
                market_data[name] = {
                    "close": round(latest['Close'], 2),
                    "change_pct": round(change_pct, 2),
                    "date": latest.name.strftime("%Y-%m-%d")
                }
        except Exception as e:
            print(f"Failed to fetch {name}: {e}")
            continue
    
    return market_data

def generate_market_mood() -> Dict[str, Any]:
    """
    Analyze recent news to determine market mood using Gemini.
    Cached in DailySummary with a 16:15 cutoff.
    """
    now = timezone.now()
    # [Modified] Always target TODAY for the report.
    # If it's early morning, it will be a "Pre-Market" or "Morning" update.
    # If it's after close, it will be a "Closing" update.
    target_date = now.date()

    # 1. Check Cache
    try:
        summary = DailySummary.objects.filter(date=target_date).first()
        if summary and summary.market_mood:
            return summary.market_mood
    except Exception as e:
        print(f"Cache check failed: {e}")

    # 2. Generate New Report
    client = _client()
    if not client:
        return {"error": "API Key missing"}

    # Get top 20 recent headlines
    articles = NewsArticle.objects.order_by('-published_at')[:20]
    if not articles:
        return {"error": "No news data"}

    headlines = "\n".join([f"- {a.title} (Impact: {a.impact_score})" for a in articles])
    
    # Fetch real market data
    market_data = _fetch_market_data()
    
    # Format market data for prompt
    if market_data:
        market_summary = "\n".join([
            f"- {name}: {data['close']} ({data['change_pct']:+.2f}%) on {data['date']}"
            for name, data in market_data.items()
        ])
    else:
        market_summary = "Market data unavailable."

    from ai_advisor.prompts import get_market_mood_prompt
    prompt = get_market_mood_prompt(market_summary, headlines, SCHEMA)

    try:
        response = client.models.generate_content(model=MODEL, contents=prompt)
        text = getattr(response, "text", "") or ""
        data = _extract_json(text)
        
        if not data:
            return {"error": "Failed to parse AI response"}
            
        # 3. Save to Cache
        # We save it to the target_date's summary. 
        # If we are before 16:15 (e.g. 10 AM), we are generating/fetching the report for Yesterday.
        # If we are after 16:15, we are generating for Today.
        
        summary, created = DailySummary.objects.get_or_create(date=target_date)
        summary.market_mood = data
        summary.save()
            
        return data
        
    except Exception as e:
        return {"error": str(e)}

def translate_titles(articles_data: list) -> Dict[int, str]:
    """
    Translate a batch of news titles to Korean using Gemini.
    Input: [{'id': 1, 'title': '...'}, ...]
    Output: {1: '...', 2: '...'}
    """
    if not articles_data:
        return {}

    client = _client()
    if not client:
        return {}

    # Prepare prompt
    titles_text = "\n".join([f"{a['id']}: {a['title']}" for a in articles_data])
    
    prompt = f"""
    Translate the following news titles into natural Korean suitable for a finance news dashboard.
    Return ONLY a JSON object mapping ID to translated title.
    
    Input Titles:
    {titles_text}
    
    Output Format:
    {{
        "1": "한국어 제목 1",
        "2": "한국어 제목 2"
    }}
    """
    
    try:
        response = client.models.generate_content(model=MODEL, contents=prompt)
        text = getattr(response, "text", "") or ""
        data = _extract_json(text)
        
        if not data:
            return {}
            
        # Convert string keys back to int
        return {int(k): v for k, v in data.items()}
        
    except Exception as e:
        print(f"[Gemini] Translation failed: {e}")
        return {}

def generate_market_comic(mood_data: Dict[str, Any], target_date) -> Optional[str]:
    """
    Generate a comic-style illustration of today's market mood using Gemini 2.5 Flash Image.
    Returns the saved image path or None if failed.
    """
    import os  # Import locally to avoid any scope issues
    
    # [IMPORTANT] Use NANOBANANA_API_KEY for image generation only
    api_key = os.getenv("NANOBANANA_API_KEY")
    if not api_key:
        print("[Gemini] No NANOBANANA_API_KEY found for image generation")
        return None
    
    client = genai.Client(api_key=api_key)
    
    # Create prompt for comic image
    mood = mood_data.get('mood', 'Neutral')
    
    # Simplified, concise prompt
    prompt = f"Stock market cartoon: {mood} mood. Cute nano banana style."

    try:
        # Generate image using Gemini 2.5 Flash Image
        response = client.models.generate_content(
            model="gemini-2.5-flash-image",
            contents=[prompt]
        )
        
        # Extract image from response
        image_data = None
        for part in response.parts:
            if part.inline_data is not None:
                image_data = part.as_image()
                break
        
        if not image_data:
            print("[Gemini] No image generated")
            return None
            
        # Save the image
        import os
        from django.conf import settings
        
        # Create directory if it doesn't exist
        image_dir = os.path.join(settings.BASE_DIR, 'static', 'news', 'mood_comics')
        os.makedirs(image_dir, exist_ok=True)
        
        # Save image with date-based filename
        filename = f"market_mood_{target_date.strftime('%Y%m%d')}.png"
        filepath = os.path.join(image_dir, filename)
        
        # Save using PIL
        image_data.save(filepath)
        
        # Return relative URL
        relative_url = f"/static/news/mood_comics/{filename}"
        print(f"[Gemini] Comic image saved: {relative_url}")
        return relative_url
        
    except Exception as e:
        print(f"[Gemini] Image generation failed: {e}")
        return None

