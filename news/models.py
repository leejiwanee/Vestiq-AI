from django.db import models
from django.utils import timezone


class NewsArticle(models.Model):
    """저장된 뉴스 기사"""
    title = models.CharField(max_length=500)
    title_ko = models.CharField(max_length=500, blank=True, null=True) # [New] Korean translation
    content = models.TextField(blank=True, null=True)
    description = models.TextField(blank=True, null=True)  # Short summary
    source = models.CharField(max_length=100)
    author = models.CharField(max_length=200, blank=True, null=True)
    published_at = models.DateTimeField()
    url = models.TextField()
    image_url = models.TextField(blank=True, null=True)
    
    # Analysis results
    sentiment_score = models.FloatField(null=True, blank=True)  # -1 (bearish) to +1 (bullish)
    impact_score = models.IntegerField(null=True, blank=True)  # 0-100
    keywords = models.JSONField(default=list, blank=True)  # ["keyword1", "keyword2", ...]
    country = models.CharField(max_length=100, blank=True, null=True)
    sector = models.CharField(max_length=100, blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-published_at']
        indexes = [
            models.Index(fields=['-published_at']),
            models.Index(fields=['sentiment_score']),
            models.Index(fields=['impact_score']),
        ]
    
    def __str__(self):
        return f"{self.title} ({self.source})"


class DailySummary(models.Model):
    """일별 뉴스 요약 통계"""
    date = models.DateField(unique=True)
    total_articles = models.IntegerField(default=0)
    avg_sentiment = models.FloatField(default=0.0)  # Average sentiment score
    market_change_pct = models.FloatField(default=0.0)  # [New] S&P 500 daily change %
    
    # JSON fields for complex data
    top_keywords = models.JSONField(default=dict, blank=True)  # {"keyword": count, ...}
    sector_counts = models.JSONField(default=dict, blank=True)  # {"Tech": 10, "Finance": 8, ...}
    country_counts = models.JSONField(default=dict, blank=True)  # {"USA": 15, "China": 5, ...}
    sentiment_distribution = models.JSONField(default=dict, blank=True)  # {"positive": 10, "negative": 5, "neutral": 3}
    market_mood = models.JSONField(default=dict, blank=True)  # AI Analysis Cache
    mood_image_url = models.CharField(max_length=500, blank=True, null=True)  # [New] AI-generated comic image
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-date']
        verbose_name_plural = "Daily summaries"
    
    def __str__(self):
        return f"Summary for {self.date}"
