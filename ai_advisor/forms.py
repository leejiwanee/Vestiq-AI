from django import forms
from .models import InvestmentProfile
from django.utils.translation import gettext_lazy as _

class InvestmentForm(forms.ModelForm):
    class Meta:
        model = InvestmentProfile
        fields = [
            'total_amount', 'monthly_contribution', 'risk_tolerance', 
            'duration_months', 'target_return', 'investment_goal'
        ]
        widgets = {
            'total_amount': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': _('e.g. 10000')}),
            'monthly_contribution': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': _('e.g. 500 (0 if none)')}),
            'risk_tolerance': forms.Select(attrs={'class': 'form-select'}),
            'duration_months': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': _('Months (e.g. 36)')}),
            'target_return': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': _('e.g. 10 (10% per year)')}),
            'investment_goal': forms.Select(attrs={'class': 'form-select'}),
        }
        labels = {
            'total_amount': _('Initial Investment ($)'),
            'monthly_contribution': _('Monthly Contribution ($)'),
            'risk_tolerance': _('Risk Tolerance'),
            'duration_months': _('Investment Duration (Months)'),
            'target_return': _('Target Annual Return (%)'),
            'investment_goal': _('Investment Goal'),
        }