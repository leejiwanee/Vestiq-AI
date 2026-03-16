
from django.urls import path
from . import views

app_name = "insight"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("top20/", views.market_cap_top20, name="top20"),
    path("insider/", views.insider_analysis, name="insider"), # New
    path("seasonality/", views.seasonality_analysis, name="seasonality"), # New
    path("wsb/", views.wsb_analysis, name="wsb"),
    path("13f/", views.institutional_holdings, name="13f"),
    path("earnings/", views.earnings_report, name="earnings"),
    path("earnings/source/<str:symbol>/", views.earnings_source, name="earnings_source"),
    path("earnings/email/", views.email_earnings_report, name="email_earnings"),
    path("correlation/", views.correlation_matrix, name="correlation"), # New
    path("sector-leaders/", views.sector_leaders_view, name="sector_leaders"),
    path("sector-leaders/update/", views.update_sector_leaders_manual, name="update_sector_leaders"),
    path("earnings-2/", views.earnings_v2, name="earnings_v2"),
    path("calendar/", views.earnings_calendar_view, name="calendar"),
    path("market-101/", views.market_101_view, name="market_101"), # Education
    path("api/sector/<str:sector_name>/", views.api_sector_details, name="api_sector_details"),
]
