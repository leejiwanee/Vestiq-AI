from django.db import models
from django.utils.translation import gettext_lazy as _

class InvestmentProfile(models.Model):
    """
    사용자가 입력한 투자 성향 및 정보
    """
    RISK_CHOICES = [
        ("low", _("Low (Stable - Principal Protection)")),
        ("medium", _("Medium (Balanced)")),
        ("high", _("High (Aggressive - High Return)")),
    ]
    
    GOAL_CHOICES = [
        ("retirement", _("Retirement Fund")),
        ("house", _("House Purchase")),
        ("wealth", _("Wealth Accumulation")),
        ("short_term", _("Short-term Lump Sum (Travel/Wedding)")),
    ]

    # 기본 정보
    total_amount = models.BigIntegerField(help_text="총 투자 가능 금액 ($)")
    risk_tolerance = models.CharField(max_length=10, choices=RISK_CHOICES, default="medium")
    duration_months = models.IntegerField(help_text="투자 기간 (개월 단위)", default=12)
    
    # 추가 정보 (AI가 더 정교하게 짜주기 위함)
    target_return = models.FloatField(help_text="목표 수익률 (%)", null=True, blank=True)
    monthly_contribution = models.BigIntegerField(help_text="월 추가 납입 가능 금액 ($)", default=0)
    investment_goal = models.CharField(max_length=20, choices=GOAL_CHOICES, default="wealth")
    
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"${self.total_amount:,} ({self.get_risk_tolerance_display()})"


class PortfolioReport(models.Model):
    """
    Gemini가 생성한 포트폴리오 결과 저장
    """
    profile = models.OneToOneField(InvestmentProfile, on_delete=models.CASCADE)
    
    # AI 분석 결과 (JSON으로 저장해서 나중에 차트 그리기 용이하게)
    allocation_json = models.JSONField(help_text="자산 배분 비율 (JSON)")
    tickers_json = models.JSONField(help_text="추천 종목 리스트 (JSON)")
    strategy_name = models.CharField(max_length=100, default="Custom Strategy", help_text="전략 이름")
    
    # 텍스트 리포트
    rationale = models.TextField(help_text="AI의 투자 근거 및 조언")
    
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Report for Profile #{self.profile.id}"


class TradeRecommendation(models.Model):
    """
    AI-generated daily trading recommendations
    Combines Scanner results + News sentiment + Gemini AI analysis
    """
    created_at = models.DateTimeField(auto_now_add=True)
    date = models.DateField(db_index=True)  # Recommendation date
    
    # Stock Info
    symbol = models.CharField(max_length=20, db_index=True)
    company_name = models.CharField(max_length=255, blank=True)
    
    # Current Market Data
    current_price = models.FloatField()
    volume = models.BigIntegerField(null=True)
    price_change_pct = models.FloatField(null=True)
    vol_change_pct = models.FloatField(null=True)
    
    # Market Context
    market_mood = models.CharField(max_length=20)  # Bullish/Bearish/Neutral
    market_mood_score = models.IntegerField(null=True)  # 0-100
    
    # AI Recommendation
    recommendation = models.CharField(max_length=10, db_index=True)  # BUY/HOLD/AVOID
    entry_price = models.FloatField(null=True, blank=True)
    stop_loss = models.FloatField(null=True, blank=True)
    take_profit = models.FloatField(null=True, blank=True)
    position_size = models.CharField(max_length=20, blank=True)  # e.g., "2-3%"
    
    # Analysis Details
    rationale = models.TextField(blank=True)  # AI reasoning in Korean
    technical_score = models.FloatField(default=0)  # 0-100
    filters_triggered = models.JSONField(default=list)  # ['volume', 'momentum', ...]
    
    # Risk Metrics
    risk_reward_ratio = models.FloatField(null=True, blank=True)  # (TP-Entry)/(Entry-SL)
    confidence_level = models.CharField(max_length=20, blank=True)  # High/Medium/Low
    language = models.CharField(max_length=10, default='ko', db_index=True)  # 'ko' or 'en'
    
    class Meta:
        ordering = ['-date', '-technical_score']
        indexes = [
            models.Index(fields=['date', 'recommendation']),
            models.Index(fields=['date', 'language']),
        ]
    
    def __str__(self):
        return f"{self.symbol} - {self.recommendation} ({self.date}) [{self.language}]"
    
    @property
    def potential_gain_pct(self):
        """계산된 익절 퍼센트"""
        if self.entry_price and self.take_profit:
            return ((self.take_profit - self.entry_price) / self.entry_price) * 100
        return None
    
    @property
    def potential_loss_pct(self):
        """계산된 손절 퍼센트"""
        if self.entry_price and self.stop_loss:
            return ((self.stop_loss - self.entry_price) / self.entry_price) * 100
        return None

class LongTermPickReport(models.Model):
    """
    Stores the AI-generated Long-Term Stock Picks report.
    Cached to avoid frequent API calls.
    Expires at 4:15 PM the next day.
    """
    created_at = models.DateTimeField(auto_now_add=True)
    language = models.CharField(max_length=10, default='ko', db_index=True)  # 'ko' or 'en'
    data = models.JSONField(help_text="Full JSON response from Gemini")
    
    def __str__(self):
        return f"LongTermPickReport ({self.created_at}) [{self.language}]"