# scanner/models.py

from django.db import models
from django.utils import timezone

class DailyPrice(models.Model):
    """
    [재료] yfinance에서 가져온 일봉 데이터
    updatedata 앱이 채워넣고, scanner 앱이 읽어서 분석함.
    """
    symbol = models.CharField(max_length=20, db_index=True)
    date = models.DateField(db_index=True)
    
    open = models.FloatField()
    high = models.FloatField()
    low = models.FloatField()
    close = models.FloatField()
    volume = models.BigIntegerField()

    class Meta:
        unique_together = [("symbol", "date")]
        indexes = [
            models.Index(fields=["symbol", "date"]),
        ]

    def __str__(self):
        return f"{self.symbol} {self.date}"


class ScanBatch(models.Model):
    """
    [기록] 'Run Scan' 버튼을 한 번 누를 때마다 생성되는 회차 정보
    """
    started_at = models.DateTimeField(db_index=True, default=timezone.now)
    
    # 통계 정보
    scanned_count = models.IntegerField(default=0)    # 총 스캔한 종목 수
    triggered_count = models.IntegerField(default=0)  # 조건 만족한 종목 수
    
    avg_price_change = models.FloatField(null=True, blank=True) # 시장 평균 등락률
    avg_vol_change = models.FloatField(null=True, blank=True)   # 시장 평균 거래량 변화율

    def __str__(self):
        return f"Batch {self.id} ({self.started_at.strftime('%Y-%m-%d %H:%M')})"


class ScanRow(models.Model):
    """
    [결과] 해당 Batch에서 분석된 개별 종목의 결과
    """
    batch = models.ForeignKey(ScanBatch, on_delete=models.CASCADE, related_name="rows")
    
    symbol = models.CharField(max_length=20, db_index=True)
    company = models.CharField(max_length=255, blank=True, null=True)
    industry = models.CharField(max_length=255, blank=True, null=True) # 섹터/산업 정보 저장

    # 분석 시점의 스냅샷 데이터
    close = models.FloatField(null=True, blank=True)
    price_change_pct = models.FloatField(null=True, blank=True)
    
    volume = models.BigIntegerField(null=True, blank=True)
    prev_volume = models.BigIntegerField(null=True, blank=True) # [필수] views.py에서 저장함
    vol_change_pct = models.FloatField(null=True, blank=True)

    # 5가지 필터 통과 여부 (True/False)
    f_volume = models.BooleanField(default=False)
    f_volatility = models.BooleanField(default=False)
    f_trend = models.BooleanField(default=False)
    f_pattern = models.BooleanField(default=False)
    f_momentum = models.BooleanField(default=False)

    # 최종 Trigger 여부 (하나라도 통과했으면 True)
    trigger = models.BooleanField(default=False, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    
    f_value = models.BooleanField(default=False)
    f_oversold = models.BooleanField(default=False) # [New] BB Lower + RSI <= 30
    f_lux = models.BooleanField(default=False) # [New] Smart Pattern (Trend + Momentum)
    f_gap = models.BooleanField(default=False) # [New] Gap Up
    f_squeeze = models.BooleanField(default=False) # [New] Bollinger Squeeze

    # [New] VCS Score (0-100) for Sorting
    # [New] VCS Score (0-100) for Sorting
    vcs = models.IntegerField(null=True, blank=True, db_index=True)
    
    # [New] Technicals for Tooltip (Since we calculate them dynamically)
    rsi = models.FloatField(null=True, blank=True)
    rvol = models.FloatField(null=True, blank=True)
    ma20 = models.FloatField(null=True, blank=True)
    ma60 = models.FloatField(null=True, blank=True)
    
    # Store detailed score components as JSON for perfect tooltip
    # e.g. {"trend": 25, "mom": 20, "vol": 10, "pattern": 5, "base": 40}
    score_details = models.JSONField(default=dict, blank=True)

    @property
    def vcs_status(self):
        if self.vcs is None: return None
        if self.vcs >= 65: return "🚀 BUY"
        if self.vcs >= 35: return "👀 WATCH"
        return "🔻 AVOID"

    @property
    def vcs_badge_class(self):
        if self.vcs is None: return ""
        if self.vcs >= 65: return "qa-badge qa-badge-buy"
        if self.vcs >= 35: return "qa-badge qa-badge-watch"
        return "qa-badge qa-badge-avoid"

    @property
    def vcs_color(self):
        if self.vcs is None: return "qa-num-zero"
        if self.vcs >= 65: return "qa-num-pos"
        if self.vcs >= 35: return "qa-num-zero"
        return "qa-num-neg"
    
    @property
    def vcs_badge_style(self):
        # Helper for inline styles if needed, currently using classes
        return ""

    @property
    def vcs_breakdown(self):
        """
        Returns a breakdown string for UI tooltip using stored score components.
        Expected keys in score_details: base, trend, mom, vol, pattern
        """
        if not self.score_details:
             # Fallback for old rows or incomplete data
             return f"Score: {self.vcs or 0}"
             
        d = self.score_details
        base = d.get('base', 40)
        trend = d.get('trend', 0)
        mom = d.get('mom', 0)
        vol = d.get('vol', 0)
        pattern = d.get('pattern', 0)
        
        # Format Trend specific text based on value
        trend_txt = "Range"
        if trend == 25: trend_txt = "Strong Up (+25)"
        elif trend == 15: trend_txt = "Up (+15)"
        else: trend_txt = "Weak (0)"

        # Format details
        return (f"Base: {base} | "
                f"Trend: {trend_txt} | "
                f"Mom: {mom:+d} | "
                f"Vol: {vol:+d} | "
                f"Pattern: {pattern:+d} "
                f"(RSI: {self.rsi or '-'}, RVOL: {self.rvol or '-'})")

    def __str__(self):
        return f"{self.symbol} (Trigger={self.trigger})"

class AiReport(models.Model):
    """
    [AI 리포트] Gemini 분석 결과 캐싱용
    """
    batch = models.ForeignKey(ScanBatch, on_delete=models.SET_NULL, null=True, blank=True)
    symbol = models.CharField(max_length=20, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    payload = models.JSONField(default=dict) # AI 응답 전체 저장

    def __str__(self):
        return f"AiReport for {self.symbol} ({self.created_at})"


class DailyPick(models.Model):
    """
    [Vestiq Pick] Stores daily recommended stocks.
    Allows for Calendar View of past picks.
    """
    date = models.DateField(default=timezone.now, db_index=True)
    symbol = models.CharField(max_length=20)
    
    # Strategy that picked this
    strategy = models.CharField(max_length=255, default="Prime") # Pullback, Breakout, etc.
    
    # Snapshot Data at time of pick
    price = models.FloatField(null=True, blank=True)
    reason = models.TextField(blank=True, null=True) # AI or Logic explanation

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("date", "symbol")]
        ordering = ["-date", "symbol"]

    def __str__(self):
        return f"[{self.date}] {self.symbol} ({self.strategy})"

