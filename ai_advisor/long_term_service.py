import os
import json
from datetime import datetime, timedelta, time
from django.utils.translation import get_language
from django.utils import timezone
from google import genai
import yfinance as yf
from django.conf import settings
from .models import LongTermPickReport

def get_long_term_picks(language='ko'):
    """
    Asks Gemini for 20 high-conviction long-term stock picks.
    Enriches with real-time price data from yfinance.
    Cached: Expires at 4:15 PM the next day.
    """
    # 1. Check for valid cached report for this language
    try:
        latest_report = LongTermPickReport.objects.filter(language=language).last()
        if latest_report:
            # Calculate expiration time: Next day at 16:15
            created_local = timezone.localtime(latest_report.created_at)
            expiration_date = created_local.date() + timedelta(days=1)
            expiration_time = timezone.make_aware(datetime.combine(expiration_date, time(16, 15)))
            
            if timezone.now() < expiration_time:
                print(f"Using cached report from {created_local} ({language})")
                data = latest_report.data
                return data
            else:
                print("Cached report expired.")
                latest_report.delete()
    except Exception as e:
        print(f"Cache check error: {e}")

    # 2. Generate new report
    api_key = os.environ.get("GEMINI2_API_KEY")
    if not api_key:
        return {"error": "API Key not found"}

    try:
        client = genai.Client(api_key=api_key)

        current_year = datetime.now().year
        
        from .prompts import get_long_term_picks_prompt
        
        prompt = get_long_term_picks_prompt(current_year, language=language)
        
        response = client.models.generate_content(
            model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
            contents=prompt,
            config={'response_mime_type': 'application/json'}
        )
        
        data = json.loads(response.text)
        
        # Enrich with real-time price
        for pick in data.get('picks', []):
            try:
                ticker = yf.Ticker(pick['symbol'])
                hist = ticker.history(period="1d")
                if not hist.empty:
                    current_price = hist['Close'].iloc[-1]
                    pick['price'] = f"${current_price:.2f}"
                    
                    # Get daily change
                    prev_close = ticker.info.get('previousClose', current_price)
                    change = ((current_price - prev_close) / prev_close) * 100
                    pick['change_percent'] = f"{change:+.2f}%"
                else:
                    pick['price'] = "N/A"
                    pick['change_percent'] = "0.00%"
            except:
                pick['price'] = "N/A"
                pick['change_percent'] = "0.00%"
        
        # 3. Save to Cache
        try:
            LongTermPickReport.objects.create(data=data, language=language)
        except Exception as e:
            print(f"Failed to save report: {e}")
            
        return data

    except Exception as e:
        print(f"Long Term Picks Error: {e}")
        return {"error": str(e)}
