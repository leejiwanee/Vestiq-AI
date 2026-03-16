from django.urls import path
from . import views

app_name = "home"
urlpatterns = [
    path("", views.index, name="index"),
    path("gemini-summary/", views.gemini_market_summary, name="gemini_market_summary"),
]
