from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

class UserProfile(models.Model):
    """
    Stores Kakao OAuth tokens for each user.
    One-to-One relationship with Django's User model.
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='kakao_profile')
    
    # Kakao OAuth Tokens
    kakao_access_token = models.CharField(max_length=500, blank=True, null=True)
    kakao_refresh_token = models.CharField(max_length=500, blank=True, null=True)
    token_expires_at = models.DateTimeField(blank=True, null=True)
    
    # Kakao User Info (optional)
    kakao_user_id = models.BigIntegerField(blank=True, null=True, unique=True)
    kakao_nickname = models.CharField(max_length=100, blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.user.username}'s Kakao Profile"
    
    def is_token_valid(self):
        """Check if access token is still valid"""
        if not self.kakao_access_token or not self.token_expires_at:
            return False
        return timezone.now() < self.token_expires_at
    
    class Meta:
        db_table = 'accounts_userprofile'
        verbose_name = 'User Kakao Profile'
        verbose_name_plural = 'User Kakao Profiles'
