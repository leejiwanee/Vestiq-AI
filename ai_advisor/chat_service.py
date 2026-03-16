import os
import json
from google import genai
from news.models import DailySummary
from django.utils import timezone
from datetime import timedelta

MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

def _client():
    key = os.getenv("GEMINI2_API_KEY")
    return genai.Client(api_key=key) if key else None

def get_market_news_context(days=3):
    """Fetch recent market summaries"""
    try:
        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=days)
        summaries = DailySummary.objects.filter(date__gte=start_date).order_by('-date')
        
        context = []
        for s in summaries:
            context.append(f"[{s.date}] Market Mood: {s.market_mood}\nSummary: {s.summary_text[:500]}...")
            
        return "\n\n".join(context)
    except Exception as e:
        print(f"Error fetching news: {e}")
        return "No recent market news available."

def generate_chat_response(user_message, portfolio_data, language='ko'):
    """
    Generate a response to the user's question based on their portfolio and market news.
    """
    client = _client()
    if not client:
        return "AI Service is currently unavailable (API Key missing)."

    # 1. Prepare Context
    news_context = get_market_news_context()
    
    # Format Portfolio Data for Prompt
    profile = portfolio_data.get('profile', {})
    report = portfolio_data.get('report', {})
    
    portfolio_str = json.dumps(report.get('portfolio', []), indent=2, ensure_ascii=False)
    allocation_str = json.dumps(report.get('allocation', {}), indent=2, ensure_ascii=False)
    strategy_name = report.get('strategy_name', 'Custom Strategy')
    
    # 2. Build Prompt
    system_instruction = (
        "You are an expert AI Investment Advisor. "
        "You have access to the user's specific portfolio and recent market news. "
        "Answer the user's question accurately, referencing their specific holdings and the market context. "
        "Be helpful, professional, but concise. "
        "If the user asks about something unrelated to investing or their portfolio, politely steer them back. "
        f"Respond in {language}."
    )
    
    prompt = f"""
    [User Portfolio Context]
    Strategy: {strategy_name}
    Target Return: {profile.get('target_return', 'N/A')}%
    Risk Tolerance: {profile.get('risk_tolerance', 'N/A')}
    
    Asset Allocation:
    {allocation_str}
    
    Holdings:
    {portfolio_str}
    
    [Recent Market News]
    {news_context}
    
    [User Question]
    {user_message}
    
    [Your Answer]
    """
    
    try:
        response = client.models.generate_content(
            model=MODEL,
            contents=prompt,
            config=genai.types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.7
            )
        )
        return getattr(response, "text", "Sorry, I couldn't generate a response.")
        
    except Exception as e:
        print(f"Chat Generation Error: {e}")
        return "An error occurred while processing your request."
