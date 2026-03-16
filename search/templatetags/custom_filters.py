from django import template

register = template.Library()

@register.filter
def format_usd(value):
    """
    Format large numbers in English with $ prefix
    Examples:
        2900000000 -> $2.90B
        566000000 -> $566.0M
        12500 -> $12.5K
    """
    try:
        num = float(value)
    except (ValueError, TypeError):
        return '-'
    
    if num == 0:
        return '$0'
    
    abs_num = abs(num)
    sign = '-' if num < 0 else ''
    
    if abs_num >= 1e9:
        # Billions - show 2 decimal places
        return f"{sign}${abs_num / 1e9:.2f}B"
    elif abs_num >= 1e6:
        # Millions - show 1 decimal place
        return f"{sign}${abs_num / 1e6:.1f}M"
    elif abs_num >= 1e3:
        # Thousands - show 1 decimal place
        return f"{sign}${abs_num / 1e3:.1f}K"
    else:
        # Less than thousand - show whole number
        return f"{sign}${abs_num:.0f}"
