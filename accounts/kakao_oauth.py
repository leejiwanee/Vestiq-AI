"""
Kakao OAuth 2.0 Authentication Views
Handles login, callback, and token refresh for KakaoTalk messaging.
"""

import requests
import json
from datetime import datetime, timedelta
from urllib.parse import urlencode

from django.shortcuts import redirect
from django.http import JsonResponse
from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.auth import login
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .models import UserProfile


# Kakao OAuth URLs
KAKAO_AUTH_URL = "https://kauth.kakao.com/oauth/authorize"
KAKAO_TOKEN_URL = "https://kauth.kakao.com/oauth/token"
KAKAO_USER_INFO_URL = "https://kapi.kakao.com/v2/user/me"


def kakao_login_redirect(request):
    """
    Step 1: Redirect user to Kakao login page
    Always shows account selection screen
    """
    params = {
        'client_id': settings.KAKAO_REST_API_KEY,
        'redirect_uri': request.build_absolute_uri('/accounts/kakao/callback/'),
        'response_type': 'code',
        'scope': 'talk_message',  # Permission for KakaoTalk messaging
        'prompt': 'select_account',  # Always show account selection
    }
    
    kakao_auth_url = f"{KAKAO_AUTH_URL}?{urlencode(params)}"
    return redirect(kakao_auth_url)


@csrf_exempt
def kakao_callback(request):
    """
    Step 2: Handle callback from Kakao with authorization code
    Exchange code for access token and create/update user
    """
    code = request.GET.get('code')
    
    if not code:
        return JsonResponse({'error': 'No authorization code provided'}, status=400)
    
    # Exchange authorization code for access token
    token_data = {
        'grant_type': 'authorization_code',
        'client_id': settings.KAKAO_REST_API_KEY,
        'redirect_uri': request.build_absolute_uri('/accounts/kakao/callback/'),
        'code': code,
    }
    
    # Add client_secret if available (optional but recommended)
    if hasattr(settings, 'KAKAO_CLIENT_SECRET') and settings.KAKAO_CLIENT_SECRET:
        token_data['client_secret'] = settings.KAKAO_CLIENT_SECRET
    
    try:
        # Request access token
        token_response = requests.post(KAKAO_TOKEN_URL, data=token_data)
        token_response.raise_for_status()
        token_json = token_response.json()
        
        access_token = token_json.get('access_token')
        refresh_token = token_json.get('refresh_token')
        expires_in = token_json.get('expires_in', 21600)  # Default 6 hours
        
        # Get user info from Kakao
        user_info_response = requests.get(
            KAKAO_USER_INFO_URL,
            headers={'Authorization': f'Bearer {access_token}'}
        )
        user_info_response.raise_for_status()
        user_info = user_info_response.json()
        
        kakao_user_id = user_info.get('id')
        kakao_nickname = user_info.get('properties', {}).get('nickname', f'kakao_{kakao_user_id}')
        
        # Check if this Kakao ID is already linked to another user
        try:
            existing_profile = UserProfile.objects.get(kakao_user_id=kakao_user_id)
            
            # If user is logged in and trying to link, but Kakao ID is already linked to another user
            if request.user.is_authenticated and existing_profile.user != request.user:
                # Clear the old connection first
                existing_profile.kakao_access_token = None
                existing_profile.kakao_refresh_token = None
                existing_profile.token_expires_at = None
                existing_profile.kakao_user_id = None
                existing_profile.kakao_nickname = None
                existing_profile.save()
                
                # Now link to current user
                user = request.user
                profile, _ = UserProfile.objects.get_or_create(user=user)
            else:
                # Use existing profile
                user = existing_profile.user
                profile = existing_profile
                
        except UserProfile.DoesNotExist:
            # No existing Kakao connection
            if request.user.is_authenticated:
                # Link Kakao to existing logged-in user
                user = request.user
                profile, _ = UserProfile.objects.get_or_create(user=user)
            else:
                # Create new user for this Kakao account
                user, created = User.objects.get_or_create(
                    username=f'kakao_{kakao_user_id}',
                    defaults={'first_name': kakao_nickname}
                )
                profile, _ = UserProfile.objects.get_or_create(user=user)
        
        # Save tokens to profile
        profile.kakao_access_token = access_token
        profile.kakao_refresh_token = refresh_token
        profile.token_expires_at = timezone.now() + timedelta(seconds=expires_in)
        profile.kakao_user_id = kakao_user_id
        profile.kakao_nickname = kakao_nickname
        profile.save()
        
        # Only login if user wasn't already logged in
        if not request.user.is_authenticated:
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        
        request.session['kakao_logged_in'] = True
        
        # Redirect to Vestiq Pick page
        return redirect('/scanner/vestiq-pick/')
        
    except requests.exceptions.RequestException as e:
        return JsonResponse({'error': f'Kakao API error: {str(e)}'}, status=500)
    except Exception as e:
        return JsonResponse({'error': f'Server error: {str(e)}'}, status=500)


def refresh_kakao_token(user):
    """
    Refresh expired access token using refresh token
    """
    try:
        profile = user.kakao_profile
        
        if not profile.kakao_refresh_token:
            return False
        
        token_data = {
            'grant_type': 'refresh_token',
            'client_id': settings.KAKAO_REST_API_KEY,
            'refresh_token': profile.kakao_refresh_token,
        }
        
        if hasattr(settings, 'KAKAO_CLIENT_SECRET') and settings.KAKAO_CLIENT_SECRET:
            token_data['client_secret'] = settings.KAKAO_CLIENT_SECRET
        
        response = requests.post(KAKAO_TOKEN_URL, data=token_data)
        response.raise_for_status()
        token_json = response.json()
        
        # Update tokens
        profile.kakao_access_token = token_json.get('access_token')
        
        # Refresh token might be updated
        if 'refresh_token' in token_json:
            profile.kakao_refresh_token = token_json['refresh_token']
        
        expires_in = token_json.get('expires_in', 21600)
        profile.token_expires_at = timezone.now() + timedelta(seconds=expires_in)
        profile.save()
        
        return True
        
    except Exception as e:
        print(f"Token refresh failed: {e}")
        return False


def get_valid_kakao_token(user):
    """
    Get valid access token, refreshing if necessary
    Returns None if user not authenticated or refresh fails
    """
    if not user.is_authenticated:
        return None
    
    try:
        profile = user.kakao_profile
        
        # Check if token is valid
        if profile.is_token_valid():
            return profile.kakao_access_token
        
        # Try to refresh
        if refresh_kakao_token(user):
            return profile.kakao_access_token
        
        return None
        
    except UserProfile.DoesNotExist:
        return None


def kakao_disconnect(request):
    """
    Disconnect Kakao from user account (remove tokens)
    """
    if not request.user.is_authenticated:
        return redirect('login')
    
    try:
        profile = request.user.kakao_profile
        
        # Clear Kakao tokens
        profile.kakao_access_token = None
        profile.kakao_refresh_token = None
        profile.token_expires_at = None
        profile.kakao_user_id = None
        profile.kakao_nickname = None
        profile.save()
        
    except UserProfile.DoesNotExist:
        pass  # No profile to disconnect
    
    # Redirect back to referring page or home
    return redirect(request.META.get('HTTP_REFERER', '/'))
