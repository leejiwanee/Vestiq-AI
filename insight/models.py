from django.db import models
from django.utils import timezone

# Create your models here.

class MarketCapSnapshot(models.Model):
    """
    특정 Universe의 이전 Market Cap TOP N 종목 목록을 저장하여
    새롭게 편입된 종목을 확인하기 위한 모델
    """
    # 'global', 'sp500' 등 유니버스 키를 저장합니다.
    universe_key = models.CharField(max_length=50, unique=True, default="global")
    # 예: ["TSLA", "AAPL", "MSFT", ...]
    top_symbols_json = models.JSONField(default=list)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.universe_key} Snapshot ({self.updated_at.strftime('%Y-%m-%d %H:%M')})"

class SectorPerformance(models.Model):
    """
    섹터별 등락률 및 대장주(Leaders), 급등주(Gainers) 정보를 저장하는 모델.
    매일 장 마감 후 업데이트.
    """
    date = models.DateField(db_index=True)
    sector = models.CharField(max_length=100)
    change_percent = models.FloatField(default=0.0)
    rank = models.IntegerField(default=0)
    pe_ratio = models.FloatField(null=True, blank=True)
    
    # JSON Data for Frontend
    # Leaders: [{"symbol": "AAPL", "price": 150.0, "change": 1.2, "mkt_cap": 2500000000000}, ...]
    leaders_data = models.JSONField(default=list, blank=True)
    
    # Gainers: [{"symbol": "ABC", "price": 10.0, "change": 15.5}, ...]
    gainers_data = models.JSONField(default=list, blank=True)
    
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date', 'rank']
        unique_together = ('date', 'sector')

    def __str__(self):
        return f"[{self.date}] {self.sector} ({self.change_percent}%)"

class EarningsCalendar(models.Model):
    """
    FMP Earnings Calendar Data
    Stores earnings release info (Actual vs Estimated)
    """
    symbol = models.CharField(max_length=20, db_index=True)
    date = models.DateField(db_index=True)
    eps_actual = models.FloatField(null=True, blank=True)
    eps_estimated = models.FloatField(null=True, blank=True)
    revenue_actual = models.BigIntegerField(null=True, blank=True)
    revenue_estimated = models.BigIntegerField(null=True, blank=True)
    time = models.CharField(max_length=20, null=True, blank=True) # e.g. 'bmo', 'amc'
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['date', 'symbol']
        unique_together = ('symbol', 'date')

    def __str__(self):
        return f"{self.symbol} Earnings ({self.date})"