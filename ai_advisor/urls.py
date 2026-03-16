from django.urls import path
from . import views

app_name = "ai_advisor"

urlpatterns = [
    path("", views.index, name="input"),  # Fixed: use index instead of input_view
    path("result/", views.result_view, name="result"),
    path("api/send-email/", views.send_portfolio_email, name="send_email"),
    
    # Trading Recommendations
    path("recommendations/", views.trade_recommendations_view, name="recommendations"),
    path("api/generate-recommendations/", views.generate_recommendations_api, name="api_generate_recommendations"),
    
    # AI Stock Inspector
    path("inspector/", views.inspector_view, name="inspector"),
    path("api/analyze-stock/", views.api_analyze_stock, name="api_analyze_stock"),
    
    # Long Term Picks
    path("long-term/", views.long_term_view, name="long_term"),
    path("api/long-term/", views.api_long_term_picks, name="api_long_term_picks"),
    
    
    # Chat with Your Portfolio
    path("api/chat/", views.chat_api, name="chat_api"),

    # AI Report (Any Ticker)
    path("report/", views.report_input_view, name="report_input"),
    path("report/<str:symbol>/", views.report_result_view, name="report_result"),
    path("api/report/<str:symbol>/", views.api_ai_report_advisor, name="api_report"),
]