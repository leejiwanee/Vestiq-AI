from django.urls import path
from . import views

app_name = 'news'

urlpatterns = [
    # Main Dashboard
    path('', views.news_dashboard_view, name='dashboard'),
    
    # Search Page
    path('search/', views.news_search_view, name='search'),
    
    # API Endpoints (Removed unused endpoints)
    # path('api/sentiment/', views.get_sentiment_data, name='api_sentiment'),
    # path('api/mood/', views.get_market_mood_ai, name='api_market_mood'),
    # path('api/wordcloud/', views.get_wordcloud_data, name='api_wordcloud'),
    # path('api/timeline/', views.get_timeline_data, name='api_timeline'),
    # path('api/heatmap/', views.get_heatmap_data, name='api_heatmap'),
    # path('api/impact/', views.get_impact_scores, name='api_impact'),
    # path('api/market-mood/', views.get_market_mood_ai, name='api_market_mood'),
]
