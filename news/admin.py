from django.contrib import admin
from .models import NewsArticle, DailySummary


@admin.register(NewsArticle)
class NewsArticleAdmin(admin.ModelAdmin):
    list_display = ('title', 'source', 'published_at', 'sentiment_score', 'impact_score', 'sector', 'country')
    list_filter = ('source', 'sector', 'country', 'published_at')
    search_fields = ('title', 'content', 'description')
    readonly_fields = ('created_at', 'updated_at')
    ordering = ('-published_at',)


@admin.register(DailySummary)
class DailySummaryAdmin(admin.ModelAdmin):
    list_display = ('date', 'total_articles', 'avg_sentiment')
    readonly_fields = ('created_at', 'updated_at')
    ordering = ('-date',)
