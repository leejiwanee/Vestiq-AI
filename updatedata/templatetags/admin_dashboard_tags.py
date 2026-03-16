from django import template
from django.contrib.auth.models import User
from updatedata.models import Ticker, FundamentalData, CronJob, PriceHistory
from django.db.models import Max

register = template.Library()

@register.simple_tag
def get_dashboard_stats():
    total_users = User.objects.count()
    total_tickers = Ticker.objects.count()
    
    # Market stats
    from django.db.models import Count
    
    # Dynamic Market Stats (User Request: Group by 'market' column values)
    market_stats_qs = Ticker.objects.values('market').annotate(count=Count('id')).order_by('-count')
    
    market_stats = []
    # Keep legacy vars for now just in case, but they might be 0 if logic changes
    sp500 = 0
    nasdaq = 0
    russell = 0
    
    for item in market_stats_qs:
        m_name = item['market']
        if not m_name: 
            m_name = "Unassigned"
        
        c = item['count']
        market_stats.append({'name': m_name, 'count': c})
        
        # Legacy mapping (approximate)
        if m_name and 'sp500' in m_name.lower(): sp500 += c
        if m_name and 'nasdaq' in m_name.lower(): nasdaq += c
        if m_name and 'russell' in m_name.lower(): russell += c
    
    # Cron Jobs
    cron_jobs = list(CronJob.objects.all())
    
    # Sort Order
    # 1. Sector Leaders (16:05)
    # 2. Price History (16:10)
    # 3. Fundamentals (16:25)
    # 4. News Collection (Last)
    priority = {
        'update_sector_leaders': 1,
        'update_price_history': 2,
        'update_fundamental_data': 3,
        'update_news': 99
    }
    
    cron_jobs.sort(key=lambda x: priority.get(x.name, 50))
    
    # Latest Price History Date
    latest_price_date = PriceHistory.objects.aggregate(Max('date'))['date__max']
    
    return {
        'total_users': total_users,
        'total_tickers': total_tickers,
        'sp500': sp500,
        'nasdaq': nasdaq,
        'russell': russell,
        'market_stats': market_stats,
        'cron_jobs': cron_jobs,
        'latest_price_date': latest_price_date,
    }


