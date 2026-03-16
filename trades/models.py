from django.db import models
from django.contrib.auth.models import User
from decimal import Decimal

class TradeRecord(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    ticker = models.CharField(max_length=20, verbose_name="Ticker")
    buy_date = models.DateField(verbose_name="Buy Date")
    buy_price = models.DecimalField(max_digits=15, decimal_places=2, verbose_name="Buy Price")
    invested_amount = models.DecimalField(max_digits=15, decimal_places=2, verbose_name="Invested Amount")
    
    sell_date = models.DateField(null=True, blank=True, verbose_name="Sell Date")
    sell_price = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True, verbose_name="Sell Price")
    
    profit_percent = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Profit %")
    profit_amount = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True, verbose_name="Profit Amount")
    
    # New Fields for Journaling
    strategy = models.CharField(max_length=50, blank=True, null=True, verbose_name="Strategy")
    notes = models.TextField(blank=True, null=True, verbose_name="Notes")
    ai_analysis = models.TextField(blank=True, null=True, verbose_name="AI Analysis")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def update_totals(self):
        """Recalculate invested_amount and buy_price based on transactions"""
        transactions = self.transactions.all().order_by('date', 'created_at')
        total_invested = Decimal('0.00')
        total_quantity = Decimal('0.00')
        
        for tx in transactions:
            if tx.type == 'BUY':
                total_invested += tx.amount
                total_quantity += tx.quantity
            elif tx.type == 'SELL':
                total_quantity -= tx.quantity
            elif tx.type == 'SPLIT':
                # For split, quantity is the ratio (e.g. 0.2 for 1-for-5 reverse split)
                # Or we can store the new quantity directly?
                # Let's assume tx.quantity is the ratio multiplier.
                # If 1-for-5 reverse split, ratio is 0.2. New Qty = Old Qty * 0.2
                if tx.quantity:
                    total_quantity = total_quantity * tx.quantity
            
        self.invested_amount = total_invested
        if total_quantity > 0:
            self.buy_price = total_invested / total_quantity
        
        self.save()

    def save(self, *args, **kwargs):
        # Calculate profit if sell_price is provided
        if self.sell_price and self.buy_price and self.invested_amount:
            # Calculate quantity (implied)
            quantity = self.invested_amount / self.buy_price
            
            # Calculate total sell value
            sell_value = quantity * self.sell_price
            
            # Calculate profit amount
            self.profit_amount = sell_value - self.invested_amount
            
            # Calculate profit percent
            if self.invested_amount != 0:
                self.profit_percent = (self.profit_amount / self.invested_amount) * 100
            else:
                self.profit_percent = 0
        else:
            self.profit_amount = None
            self.profit_percent = None
            
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.ticker} ({self.buy_date})"

    class Meta:
        ordering = ['-buy_date']
        verbose_name = "Trade Record"
        verbose_name_plural = "Trade Records"

class TradeTransaction(models.Model):
    TRANSACTION_TYPES = [
        ('BUY', 'Buy'),
        ('SELL', 'Sell'),
        ('SPLIT', 'Stock Split'),
    ]
    
    trade = models.ForeignKey(TradeRecord, on_delete=models.CASCADE, related_name='transactions')
    date = models.DateField()
    type = models.CharField(max_length=10, choices=TRANSACTION_TYPES)
    price = models.DecimalField(max_digits=15, decimal_places=2)
    amount = models.DecimalField(max_digits=15, decimal_places=2) # Invested Amount
    quantity = models.DecimalField(max_digits=15, decimal_places=4) # Calculated quantity
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    def save(self, *args, **kwargs):
        if not self.quantity and self.price and self.amount:
            self.quantity = self.amount / self.price
        super().save(*args, **kwargs)
        
    def __str__(self):
        return f"{self.type} {self.trade.ticker} on {self.date}"

