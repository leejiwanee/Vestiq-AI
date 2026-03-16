from django.urls import path
from django.contrib.auth import views as auth_views
from . import views
from . import kakao_oauth

urlpatterns = [
    path('login/', views.CustomLoginView.as_view(), name='login'),
    path('logout/', views.CustomLogoutView.as_view(), name='logout'),
    path('signup/', views.signup, name='signup'),
    
    # Kakao OAuth
    path('kakao/login/', kakao_oauth.kakao_login_redirect, name='kakao_login'),
    path('kakao/callback/', kakao_oauth.kakao_callback, name='kakao_callback'),
    path('kakao/disconnect/', kakao_oauth.kakao_disconnect, name='kakao_disconnect'),
]
