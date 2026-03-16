from django.urls import path
from . import views
from . import view_backtest
from . import kakao_view

app_name = "scanner"

urlpatterns = [
    path("", views.dashboard_view, name="dashboard"),
    path("run/", views.run_scan_view, name="run_scan"),
    path("report/<str:symbol>/", views.report_view, name="report"),
    path("api/ai_report/<str:symbol>/", views.api_ai_report, name="api_ai_report"),
    path("api/news/", views.api_news, name="api_news"),
    path("detail/<str:symbol>/", views.detail_view, name="detail"),

    path('export/csv/', views.export_scan_csv, name='export_scan_csv'),
    path('export/email/', views.send_scan_email, name='send_scan_email'),
    path('export/email/report/', views.send_report_email, name='send_report_email'),
    
    # Strategy Backtest Lab
    path("lab/", views.backtest_lab_view, name="backtest_lab"),
    path("api/run-backtest/", views.api_run_backtest, name="api_run_backtest"),
    path('vestiq-pick/', views.vestiq_pick_view, name='vestiq_pick'), # New
    path("vestiq-pick/scan/", views.run_vestiq_manual_scan, name="vestiq_pick_scan"),
    
    # Live Vestiq Picks
    path("chart/<str:symbol>/", views.api_chart_data, name="api_chart_data"),
    path("vestiq-pick/backtest/", view_backtest.api_backtest_picks, name="vestiq_pick_backtest"),
    path("api/options/<str:symbol>/", views.vm_get_options, name="api_get_options"),
    path("api/ticker-history/<str:ticker>/", views.ticker_history_api, name="ticker_history_api"),
    path("send-kakao-pick/", kakao_view.send_kakao_vestiq_pick, name="send_kakao_pick"),
]
