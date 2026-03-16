# updatedata/models.py
from django.db import models

class Ticker(models.Model):
    symbol = models.CharField(max_length=255, unique=True, db_index=True)
    name = models.CharField(max_length=255, null=True, blank=True)
    
    # New Fields for Meta Data (Tiingo Fundamentals)
    sector = models.CharField(max_length=255, null=True, blank=True)
    industry = models.CharField(max_length=255, null=True, blank=True)
    market = models.CharField(max_length=50, null=True, blank=True) # sp500, nasdaq, etc.
    
    # FMP Profile Metadata
    beta = models.FloatField(null=True, blank=True)
    last_dividend = models.FloatField(null=True, blank=True)
    price_range = models.CharField(max_length=50, null=True, blank=True) # "100-200"
    
    ceo = models.CharField(max_length=255, null=True, blank=True)
    full_time_employees = models.CharField(max_length=50, null=True, blank=True) # Sometimes can be string
    description = models.TextField(null=True, blank=True)
    image = models.URLField(null=True, blank=True)
    ipo_date = models.DateField(null=True, blank=True)
    
    is_etf = models.BooleanField(default=False)
    is_actively_trading = models.BooleanField(default=True)
    
    # Financial Modeling Prep - Price Target Consensus
    price_target_consensus = models.FloatField(null=True, blank=True)
    target_high = models.FloatField(null=True, blank=True)
    target_low = models.FloatField(null=True, blank=True)
    target_median = models.FloatField(null=True, blank=True)

    dcf = models.FloatField(null=True, blank=True) # Discounted Cash Flow
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.symbol} ({self.name})"



class FundamentalData(models.Model):
    """
    YFinance ticker.info에서 가져오는 펀더멘털 데이터.
    """
    symbol = models.ForeignKey(Ticker, on_delete=models.CASCADE, related_name='fundamentals')
    date = models.DateField()
    
    # --- Calculated Manually (Preserved) ---
    pe_ratio = models.FloatField(null=True, blank=True)
    pb_ratio = models.FloatField(null=True, blank=True)
    eps_ttm = models.FloatField(null=True, blank=True)
    book_value_per_share = models.FloatField(null=True, blank=True)
    
    # --- FMP Key Metrics TTM (Full Import) ---
    market_cap = models.FloatField(null=True, blank=True)
    enterprise_value_ttm = models.FloatField(null=True, blank=True)
    ev_to_sales_ttm = models.FloatField(null=True, blank=True)
    ev_to_operating_cash_flow_ttm = models.FloatField(null=True, blank=True)
    ev_to_free_cash_flow_ttm = models.FloatField(null=True, blank=True)
    ev_to_ebitda_ttm = models.FloatField(null=True, blank=True)
    net_debt_to_ebitda_ttm = models.FloatField(null=True, blank=True)
    current_ratio_ttm = models.FloatField(null=True, blank=True)
    income_quality_ttm = models.FloatField(null=True, blank=True)
    graham_number_ttm = models.FloatField(null=True, blank=True)
    graham_net_net_ttm = models.FloatField(null=True, blank=True)
    tax_burden_ttm = models.FloatField(null=True, blank=True)
    interest_burden_ttm = models.FloatField(null=True, blank=True)
    working_capital_ttm = models.FloatField(null=True, blank=True)
    invested_capital_ttm = models.FloatField(null=True, blank=True)
    return_on_assets_ttm = models.FloatField(null=True, blank=True)
    operating_return_on_assets_ttm = models.FloatField(null=True, blank=True)
    return_on_tangible_assets_ttm = models.FloatField(null=True, blank=True)
    return_on_equity_ttm = models.FloatField(null=True, blank=True)
    return_on_invested_capital_ttm = models.FloatField(null=True, blank=True)
    return_on_capital_employed_ttm = models.FloatField(null=True, blank=True)
    earnings_yield_ttm = models.FloatField(null=True, blank=True)
    free_cash_flow_yield_ttm = models.FloatField(null=True, blank=True)
    capex_to_operating_cash_flow_ttm = models.FloatField(null=True, blank=True)
    capex_to_depreciation_ttm = models.FloatField(null=True, blank=True)
    capex_to_revenue_ttm = models.FloatField(null=True, blank=True)
    sales_general_and_administrative_to_revenue_ttm = models.FloatField(null=True, blank=True)
    research_and_developement_to_revenue_ttm = models.FloatField(null=True, blank=True)
    stock_based_compensation_to_revenue_ttm = models.FloatField(null=True, blank=True)
    intangibles_to_total_assets_ttm = models.FloatField(null=True, blank=True)
    average_receivables_ttm = models.FloatField(null=True, blank=True)
    average_payables_ttm = models.FloatField(null=True, blank=True)
    average_inventory_ttm = models.FloatField(null=True, blank=True)
    days_of_sales_outstanding_ttm = models.FloatField(null=True, blank=True)
    days_of_payables_outstanding_ttm = models.FloatField(null=True, blank=True)
    days_of_inventory_outstanding_ttm = models.FloatField(null=True, blank=True)
    operating_cycle_ttm = models.FloatField(null=True, blank=True)
    cash_conversion_cycle_ttm = models.FloatField(null=True, blank=True)
    free_cash_flow_to_equity_ttm = models.FloatField(null=True, blank=True)
    free_cash_flow_to_firm_ttm = models.FloatField(null=True, blank=True)
    tangible_asset_value_ttm = models.FloatField(null=True, blank=True)
    net_current_asset_value_ttm = models.FloatField(null=True, blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date']
        unique_together = ('symbol', 'date')

class PriceHistory(models.Model):
    symbol = models.ForeignKey(Ticker, on_delete=models.CASCADE, related_name='price_history')
    date = models.DateField(db_index=True)
    
    open = models.FloatField(null=True)
    high = models.FloatField(null=True)
    low = models.FloatField(null=True)
    close = models.FloatField(null=True)
    volume = models.BigIntegerField(null=True)
    
    # Adjusted Data (Tiingo)
    adj_open = models.FloatField(null=True, blank=True)
    adj_high = models.FloatField(null=True, blank=True)
    adj_low = models.FloatField(null=True, blank=True)
    adj_close = models.FloatField(null=True, blank=True)
    adj_volume = models.BigIntegerField(null=True, blank=True)
    
    div_cash = models.FloatField(null=True, blank=True)
    split_factor = models.FloatField(null=True, blank=True)
    
    # Internal Stats (For Scanner)
    change_amount = models.FloatField(null=True, blank=True)
    change_percent = models.FloatField(null=True, blank=True)
    volume_percent = models.FloatField(null=True, blank=True)
    
    # Vestiq Scan Optimization (Cached Trends)
    vestiq_scan = models.BooleanField(default=False, db_index=True)
    stoch_long_trend = models.CharField(
        max_length=10, 
        null=True, 
        blank=True,
        choices=[('Up', 'Up'), ('Down', 'Down'), ('Neutral', 'Neutral')]
    )
    stoch_mid_trend = models.CharField(
        max_length=10, 
        null=True, 
        blank=True,
        choices=[('Up', 'Up'), ('Down', 'Down'), ('Neutral', 'Neutral')]
    )
    
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ('symbol', 'date')
        ordering = ['-date']
        indexes = [
            models.Index(fields=["symbol", "date"]),
            models.Index(fields=["date"]),
        ]





class CronJob(models.Model):
    name = models.CharField(max_length=100, unique=True)
    is_active = models.BooleanField(default=True)
    last_run = models.DateTimeField(null=True, blank=True)
    
    # Locking Mechanism
    is_running = models.BooleanField(default=False)
    locked_at = models.DateTimeField(null=True, blank=True)
    
    def __str__(self):
        return self.name

class BackupPriceHistory(models.Model):
    """
    Backup table for PriceHistory. 
    Stores a copy of data fetched manually via Tiingo to prevent data loss.
    """
    symbol = models.ForeignKey(Ticker, on_delete=models.CASCADE, related_name='backup_price_history')
    date = models.DateField()
    
    open = models.FloatField(null=True, blank=True)
    high = models.FloatField(null=True, blank=True)
    low = models.FloatField(null=True, blank=True)
    close = models.FloatField(null=True, blank=True)
    volume = models.BigIntegerField(null=True, blank=True)
    
    adj_open = models.FloatField(null=True, blank=True)
    adj_high = models.FloatField(null=True, blank=True)
    adj_low = models.FloatField(null=True, blank=True)
    adj_close = models.FloatField(null=True, blank=True)
    adj_volume = models.BigIntegerField(null=True, blank=True)
    
    div_cash = models.FloatField(null=True, blank=True)
    split_factor = models.FloatField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ('symbol', 'date')
        ordering = ['-date']
        indexes = [
            models.Index(fields=["symbol", "date"]),
        ]