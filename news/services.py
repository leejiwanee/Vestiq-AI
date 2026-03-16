"""
News Services
Fetches and analyzes news articles using Tiingo API.
"""
import logging
from datetime import datetime
from dateutil import parser as date_parser
from django.utils import timezone
from .models import NewsArticle, DailySummary
from utils.tiingo_client import TiingoClient
import re
from collections import Counter
from django.db.models import Avg

logger = logging.getLogger(__name__)

def fetch_general_news():
    """
    Fetch general market news using Tiingo.
    """
    client = TiingoClient()
    # Tiingo 'general' news often comes from tags like 'market', 'business'
    # Or just fetch without tickers.
    articles = client.get_news(limit=20)
    
    saved_count = 0
    for art in articles:
        try:
            # Tiingo format: {'title':..., 'url':..., 'description':..., 'publishedDate':..., 'source':...}
            pub_date = date_parser.parse(art.get('publishedDate'))
            
            NewsArticle.objects.update_or_create(
                url=art.get('url'),
                defaults={
                    'title': art.get('title'),
                    'description': art.get('description', ''),
                    'source': art.get('source', 'Tiingo'),
                    'published_at': pub_date
                }
            )
            saved_count += 1
        except Exception as e:
            logger.error(f"Error saving news: {e}")
            continue
            
    return saved_count

def fetch_company_news(symbol):
    """
    Fetch news for a specific company using Tiingo.
    """
    client = TiingoClient()
    articles = client.get_news(tickers=[symbol], limit=10)
    
    saved_count = 0
    for art in articles:
        try:
            pub_date = date_parser.parse(art.get('publishedDate'))
            
            NewsArticle.objects.update_or_create(
                url=art.get('url'),
                defaults={
                    'title': art.get('title'),
                    'description': art.get('description', ''),
                    'source': art.get('source', 'Tiingo'),
                    'published_at': pub_date
                }
            )
            saved_count += 1
        except Exception as e:
            continue
            
    return saved_count

def get_latest_news_direct(limit: int = 50):
    """
    Fetch latest news directly for display (no DB save).
    Returns a list of dictionaries compatible with the template.
    """
    client = TiingoClient()
    articles = client.get_news(limit=limit)
    
    results = []
    for art in articles:
        try:
            pub_date = date_parser.parse(art.get('publishedDate'))
            results.append({
                'title': art.get('title'),
                'title_ko': art.get('title'), # Translator could be added here if needed
                'url': art.get('url'),
                'description': art.get('description', ''),
                'source': art.get('source', 'Tiingo'),
                'published_at': pub_date,
                'image_url': '', # Tiingo doesn't provide images usually
                'sentiment_score': 0,
                'impact_score': 0
            })
        except:
            continue
            
    return results

def update_daily_summary():
    """
    Update DailySummary based on today's fetched news.
    """
    today = timezone.now().date()
    recent_articles = NewsArticle.objects.filter(created_at__date=today)
    
    if not recent_articles.exists():
        return

    total = recent_articles.count()
    
    # 1. Sentiment (Placeholder as Tiingo doesn't give sentiment score directly in free tier usually)
    avg_sentiment = 0.0
    
    # 2. Keywords
    all_text = " ".join([a.title for a in recent_articles if a.title])
    words = re.findall(r'\w+', all_text.lower())
    stopwords = {'the', 'a', 'an', 'to', 'in', 'on', 'of', 'for', 'and', 'is', 'at', 'with', 'from', 'by', 'after', 'new', 'us', 'stock', 'market', 'stocks', 'says', 'report', 'updates', 'live', 'watch', 'data', 'week', 'year'}
    filtered_words = [w for w in words if w not in stopwords and len(w) > 3 and not w.isdigit()]
    
    keyword_counts = Counter(filtered_words).most_common(20)
    top_keywords = dict(keyword_counts)
    
    # Save
    DailySummary.objects.update_or_create(
        date=today,
        defaults={
            'total_articles': total,
            'avg_sentiment': avg_sentiment,
            'top_keywords': top_keywords,
            'market_change_pct': 0.0 # Placeholder
        }
    )

def fetch_and_analyze_news():
    """
    Wrapper for cron job. Use general news fetch and summary update.
    """
    count = fetch_general_news()
    update_daily_summary()
    return count