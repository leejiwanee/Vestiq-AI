from django.urls import path
from . import views

urlpatterns = [
    path('', views.TradeListView.as_view(), name='trade_list'),
    path('calendar/', views.TradeCalendarView.as_view(), name='trade_calendar'),
    path('add/', views.TradeCreateView.as_view(), name='trade_add'),
    path('<int:pk>/edit/', views.TradeUpdateView.as_view(), name='trade_edit'),
    path('<int:pk>/close/', views.TradeCloseView.as_view(), name='trade_close'),
    path('<int:pk>/history/', views.TradeDetailView.as_view(), name='trade_history'),
    path('<int:pk>/add/', views.TradeAddView.as_view(), name='trade_add_position'),
    path('<int:pk>/delete/', views.TradeDeleteView.as_view(), name='trade_delete'),
    path('<int:pk>/analyze/', views.analyze_trade_view, name='trade_analyze'),
    path('update-cash/', views.update_cash_balance, name='update_cash_balance'),
]
