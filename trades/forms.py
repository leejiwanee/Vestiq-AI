from django import forms
from .models import TradeRecord

class TradeForm(forms.ModelForm):
    class Meta:
        model = TradeRecord
        fields = ['ticker', 'buy_date', 'buy_price', 'invested_amount', 'sell_date', 'sell_price', 'strategy', 'notes']
        widgets = {
            'buy_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'sell_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'ticker': forms.TextInput(attrs={'class': 'form-control'}),
            'buy_price': forms.NumberInput(attrs={'class': 'form-control'}),
            'invested_amount': forms.NumberInput(attrs={'class': 'form-control'}),
            'sell_price': forms.NumberInput(attrs={'class': 'form-control'}),
            'strategy': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Breakout, Earnings, Reversal'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Why did you take this trade? Lessons learned?'}),
        }
