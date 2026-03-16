"""
URL configuration for stockweb project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path,include
from django.shortcuts import redirect


urlpatterns = [
    path('accounts/', include('accounts.urls')),
    path('trades/', include('trades.urls')),
    path('admin/', admin.site.urls),
    path('i18n/', include('django.conf.urls.i18n')),  # Language switcher
    path("", include(("home.urls","home"),namespace="home")),
    path("scanner/", include(("scanner.urls", "scanner"), namespace="scanner")),
    path("top200/", include(("updatedata.urls","updatetop200"), namespace="updatetop200")),
    path("insight/", include(("insight.urls", "insight"), namespace="insight")),
    path('search/', include('search.urls')),
    path('advisor/', include('ai_advisor.urls')),
    path('news/', include('news.urls')),
]

from django.conf import settings
from django.conf.urls.static import static

urlpatterns += static(settings.STATIC_URL, document_root=settings.STATICFILES_DIRS[0])
