import yfinance as yf
import pandas as pd
import numpy as np
from google import genai
import os
import json
from datetime import datetime, timedelta

def get_stock_data(symbol):
    """
    Fetches historical data for the symbol.
    """
    try:
        ticker = yf.Ticker(symbol)
        # Fetch 1 year of data to ensure enough for 240 MA
        df = ticker.history(period="2y")
        
        if df.empty:
            return None, "No data found for symbol"
            
        info = ticker.info
        current_price = info.get('currentPrice', df['Close'].iloc[-1])
        company_name = info.get('longName', symbol)
        
        # Fetch News
        news = []
        try:
            raw_news = ticker.news
            for item in raw_news[:5]: # Top 5 news
                content = item.get('content', {})
                click_url = content.get('clickThroughUrl', {}).get('url')
                
                # Handle different structure versions of yfinance news
                if not click_url:
                    click_url = item.get('link')
                
                title = content.get('title')
                if not title:
                    title = item.get('title')

                # Prioritize timestamp (providerPublishTime)
                pub_date = item.get('providerPublishTime')
                if not pub_date:
                    # Fallback to pubDate string and convert to timestamp
                    pub_date_str = content.get('pubDate')
                    if pub_date_str:
                        try:
                            # Try parsing ISO format
                            dt = datetime.fromisoformat(pub_date_str.replace('Z', '+00:00'))
                            pub_date = int(dt.timestamp())
                        except Exception:
                            pub_date = 0 # Invalid
                
                # Thumbnail
                thumb = None
                thumbnail = content.get('thumbnail', {})
                if thumbnail:
                    resolutions = thumbnail.get('resolutions', [])
                    if resolutions:
                        thumb = resolutions[-1].get('url') # Get largest
                
                if title and click_url:
                    news.append({
                        'title': title,
                        'url': click_url,
                        'source': content.get('provider', {}).get('displayName', 'Yahoo Finance'),
                        'time': pub_date,
                        'thumbnail': thumb
                    })
        except Exception as e:
            print(f"News fetch error: {e}")

        return {
            'df': df,
            'current_price': current_price,
            'company_name': company_name,
            'info': info,
            'news': news
        }, None
    except Exception as e:
        return None, str(e)

def calculate_indicators(df):
    """
    Calculates technical indicators for the AI context.
    """
    # Copy to avoid SettingWithCopyWarning
    data = df.copy()
    
    # Moving Averages
    data['MA5'] = data['Close'].rolling(window=5).mean()
    data['MA20'] = data['Close'].rolling(window=20).mean()
    data['MA60'] = data['Close'].rolling(window=60).mean()
    data['MA120'] = data['Close'].rolling(window=120).mean()
    data['MA240'] = data['Close'].rolling(window=240).mean()
    
    # RSI (14) - Using Wilder's Smoothing (alpha=1/14 or com=13) to match TradingView
    delta = data['Close'].diff()
    gain = (delta.where(delta > 0, 0))
    loss = (-delta.where(delta < 0, 0))
    
    avg_gain = gain.ewm(com=13, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(com=13, min_periods=14, adjust=False).mean()
    
    rs = avg_gain / avg_loss
    data['RSI'] = 100 - (100 / (1 + rs))
    
    # MACD (12, 26, 9)
    exp1 = data['Close'].ewm(span=12, adjust=False).mean()
    exp2 = data['Close'].ewm(span=26, adjust=False).mean()
    data['MACD'] = exp1 - exp2
    data['Signal'] = data['MACD'].ewm(span=9, adjust=False).mean()
    
    # Bollinger Bands (20, 2)
    data['BB_Middle'] = data['Close'].rolling(window=20).mean()
    data['BB_Std'] = data['Close'].rolling(window=20).std()
    data['BB_Upper'] = data['BB_Middle'] + (data['BB_Std'] * 2)
    data['BB_Lower'] = data['BB_Middle'] - (data['BB_Std'] * 2)
    
    # Get latest values
    latest = data.iloc[-1]
    
    return {
        'price': latest['Close'],
        'ma5': latest['MA5'],
        'ma20': latest['MA20'],
        'ma60': latest['MA60'],
        'ma120': latest['MA120'],
        'ma240': latest['MA240'],
        'rsi': latest['RSI'],
        'macd': latest['MACD'],
        'macd_signal': latest['Signal'],
        'bb_upper': latest['BB_Upper'],
        'bb_lower': latest['BB_Lower'],
        'volume': latest['Volume']
    }

def get_market_context():
    """
    Fetches key market indices to provide macro context.
    """
    try:
        tickers = ['SPY', 'QQQ', '^VIX', 'DX-Y.NYB']
        data = yf.download(tickers, period="5d", progress=False)['Close']
        
        # Calculate % change from yesterday
        latest = data.iloc[-1]
        prev = data.iloc[-2]
        
        changes = ((latest - prev) / prev) * 100
        
        context = {
            "SP500_Change": f"{changes.get('SPY', 0):.2f}%",
            "NASDAQ_Change": f"{changes.get('QQQ', 0):.2f}%",
            "VIX_Level": f"{latest.get('^VIX', 0):.2f}",
            "USD_Index_Change": f"{changes.get('DX-Y.NYB', 0):.2f}%"
        }
        return context
    except Exception as e:
        print(f"Market Context Error: {e}")
        return {}

def analyze_stock_gemini(symbol, company_name, indicators):
    """
    Sends data to Gemini for aggressive analysis using the modern google.genai SDK.
    """
    api_key = os.environ.get("GEMINI2_API_KEY")
    if not api_key:
        return None
    
    # Fetch Market Context
    market_ctx = get_market_context()
    market_str = "\n".join([f"- {k}: {v}" for k, v in market_ctx.items()]) if market_ctx else "- Market data unavailable"

    try:
        # Initialize Client (New SDK pattern)
        client = genai.Client(api_key=api_key)
        
        # Construct the prompt
        from django.utils.translation import get_language
        from .prompts import get_inspector_prompt
        
        lang_code = get_language()
        language = 'en' if lang_code == 'en' else 'ko'
        
        prompt = get_inspector_prompt(symbol, company_name, indicators, market_str, language=language)

        # Generate content with JSON enforcement
        response = client.models.generate_content(
            model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
            contents=prompt,
            config={
                'response_mime_type': 'application/json'
            }
        )
        
        # Parse JSON response
        return json.loads(response.text)

    except Exception as e:
        print(f"Gemini Error: {e}")
        # Fallback
        return {
            "score": 50,
            "signal": "HOLD",
            "strategy": "Wait",
            "verdict_title": "Analysis Temporarily Unavailable",
            "reasoning": [f"AI Error: {str(e)}"],
            "targets": {"entry": "-", "target": "-", "stop_loss": "-"},
            "risk_level": "Unknown"
        }
