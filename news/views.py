"""
News Views
API endpoints for news visualizations
"""
from django.shortcuts import render
from django.http import JsonResponse
from django.utils import timezone
from datetime import timedelta
from .models import NewsArticle, DailySummary
from django.db.models import Count, Avg
from .services import get_latest_news_direct

def news_dashboard_view(request):
    """Main news dashboard page"""
    
    # [Direct Fetch] Fetch latest news directly from API on every request
    # This ensures the absolute latest news is shown.
    # Bypasses DB and background tasks.
    
    # Get latest summary (still from DB as it's daily)
    latest_summary = DailySummary.objects.first()
    
    # Fetch articles directly
    all_articles = get_latest_news_direct(limit=50)
    
    # [Pagination]
    from django.core.paginator import Paginator
    paginator = Paginator(all_articles, 10) # Show 10 articles per page
    
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'summary': latest_summary,
        'articles': page_obj, # Pass page object
        'last_updated': timezone.now(),
    }
    
    return render(request, 'news/dashboard.html', context)


def news_search_view(request):
    """News search page with filters"""
    from django.db.models import Q
    from django.utils.translation import get_language
    
    query = request.GET.get('q', '')
    date_from = request.GET.get('from', '')
    date_to = request.GET.get('to', '')
    
    articles = NewsArticle.objects.all().order_by('-published_at')
    
    # Apply search query
    if query:
        lang_code = get_language()
        if lang_code == 'ko':
            # Search in both title and title_ko for Korean
            articles = articles.filter(
                Q(title__icontains=query) | 
                Q(title_ko__icontains=query) |
                Q(description__icontains=query)
            )
        else:
            articles = articles.filter(
                Q(title__icontains=query) | 
                Q(description__icontains=query)
            )
    
    # Apply date filters
    if date_from:
        try:
            from datetime import datetime
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d')
            articles = articles.filter(published_at__gte=date_from_obj)
        except:
            pass
    
    if date_to:
        try:
            from datetime import datetime
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d')
            articles = articles.filter(published_at__lte=date_to_obj)
        except:
            pass
    
    # Limit results
    articles = articles[:100]
    
    # Prepare results with localized titles
    results = []
    lang_code = get_language()
    for article in articles:
        display_title = article.title
        if lang_code == 'ko' and article.title_ko:
            display_title = article.title_ko
        
        results.append({
            'title': display_title,
            'description': article.description,
            'source': article.source,
            'url': article.url,
            'published_at': article.published_at,
            'impact_score': article.impact_score,
            'sentiment_score': article.sentiment_score,
        })
    
    context = {
        'results': results,
        'query': query,
        'date_from': date_from,
        'date_to': date_to,
        'total_count': len(results),
    }
    
    return render(request, 'news/search.html', context)



# Unused views removed for simplification
# get_sentiment_data, get_market_mood_ai, get_wordcloud_data, get_timeline_data, get_heatmap_data, get_impact_scores

