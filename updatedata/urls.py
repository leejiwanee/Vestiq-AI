# updatetop200/urls.py
from django.urls import path
from . import views

app_name = "updatedata"

urlpatterns = [
    path("", views.index, name="index"),
    path("update/union-all/", views.update_universe, name="update_union_all"),
    path("refresh_iwm/", views.refresh_iwm, name="refresh_iwm"),
    path("refresh_scha/", views.refresh_scha, name="refresh_scha"),
    
    # New Standardized Update Endpoints
    path("update/ticker-list/", views.update_ticker_list, name="update_ticker_list"),
    path("update/fundamentals/", views.update_fundamentals, name="update_fundamentals"),
    path("update/daily-price/", views.update_daily_price, name="update_daily_price"),
    path("download/scha/", views.data_download_scha_csv, name="data_download_scha_csv"),
    
    # Existing Aliases
    path("progress/", views.check_task_progress, name="check_task_progress"),
    path("update/ah/", views.update_ah_prices_view, name="update_ah"),     # Keep old name
    path("update/ah-price/", views.update_ah_prices_view, name="update_ah_price"), # New alias
    
    path("check-missing-history/", views.check_missing_history, name="check_missing_history"),
    path("update/backfill/", views.backfill_history_view, name="backfill_history"),
]
