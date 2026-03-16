import os
import yfinance as yf
from google import genai
from datetime import timedelta
from django.conf import settings

MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

def _client():
    key = os.getenv("GEMINI2_API_KEY")
    if not key:
        return None
    return genai.Client(api_key=key)

def analyze_trade(trade):
    """
    Analyzes a closed trade using Gemini.
    """
    client = _client()
    if not client:
        return "Error: Gemini API Key is missing. Please configure it in settings."

    if not trade.sell_date:
        return "Trade is not closed yet. Close the trade to analyze performance."

    # 1. Fetch Stock Data around the trade
    # Get data from 10 days before buy to 5 days after sell
    start_date = trade.buy_date - timedelta(days=10)
    end_date = trade.sell_date + timedelta(days=5)
    
    try:
        df = yf.download(trade.ticker, start=start_date, end=end_date, progress=False)
        if df.empty:
            market_context = "No historical data available."
        else:
            # Calculate some simple metrics
            buy_day_close = df.loc[str(trade.buy_date)]['Close'] if str(trade.buy_date) in df.index else "N/A"
            sell_day_close = df.loc[str(trade.sell_date)]['Close'] if str(trade.sell_date) in df.index else "N/A"
            
            # Get max/min during holding period
            holding_df = df[(df.index >= str(trade.buy_date)) & (df.index <= str(trade.sell_date))]
            if not holding_df.empty:
                max_price = holding_df['High'].max()
                min_price = holding_df['Low'].min()
                market_context = f"During holding: Max ${max_price:.2f}, Min ${min_price:.2f}."
            else:
                market_context = "Holding period data unavailable."
                
    except Exception as e:
        market_context = f"Failed to fetch market data: {str(e)}"

    # 2. Construct Prompt
    prompt = f"""
    You are an expert trading coach. Analyze this completed trade and provide constructive feedback.
    
    Trade Details:
    - Ticker: {trade.ticker}
    - Buy: {trade.buy_date} @ ${trade.buy_price}
    - Sell: {trade.sell_date} @ ${trade.sell_price}
    - Profit/Loss: {trade.profit_percent}% (${trade.profit_amount})
    - Strategy: {trade.strategy or 'Not specified'}
    - User Notes: {trade.notes or 'None'}
    
    Market Context:
    {market_context}
    
    Please provide a brief, professional analysis in Korean (since the user is Korean).
    Structure:
    1. **Execution Rating**: (1-10 Score)
    2. **Analysis**: Was the entry/exit timed well? Did they leave money on the table?
    3. **Key Lesson**: One actionable tip for next time.
    
    Keep it concise and encouraging but honest.
    """

    try:
        response = client.models.generate_content(
            model=MODEL,
            contents=prompt
        )
        return response.text
    except Exception as e:
        return f"Error generating analysis: {str(e)}"
