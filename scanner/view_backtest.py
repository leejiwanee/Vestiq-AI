from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.utils import timezone
from datetime import datetime, timedelta
import pandas as pd
import json
from .models import DailyPick
from updatedata.models import PriceHistory

@csrf_exempt
def api_backtest_picks(request):
    """
    API to simulate returns for Vestiq Picks over a specific holding period.
    Body: pick_date(range), hold_days
    """
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    try:
        data = json.loads(request.body)
        start_date_str = data.get('start_date')
        end_date_str = data.get('end_date')
        hold_days = int(data.get('hold_days', 5))

        # Parse Dates
        if not start_date_str or not end_date_str:
            # Default to last 30 days
            end_dt = timezone.now().date()
            start_dt = end_dt - timedelta(days=30)
        else:
            start_dt = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_dt = datetime.strptime(end_date_str, '%Y-%m-%d').date()

        # 1. Fetch Picks
        picks = DailyPick.objects.filter(date__range=(start_dt, end_dt)).order_by('date')
        
        if not picks.exists():
            return JsonResponse({
                "stats": {
                    "total_trades": 0, 
                    "win_rate": 0, 
                    "avg_return": 0, 
                    "cum_return": 0
                },
                "trades": []
            })

        # 2. Bulk Fetch Prices for "Sell Dates"
        # We need to calculate Sell Date for each pick
        # Sell Date = Pick Date + hold_days (Business Days)
        
        # Max needed date range optimization
        # Max Sell Date ~= End Date + hold_days + buffer
        max_lookahead = end_dt + timedelta(days=hold_days * 2 + 10)
        
        all_symbols = set(p.symbol for p in picks)
        
        # Fetch Price History for all these symbols from Start to Max Lookahead
        # We need Adjusted Close ideally, but Close is what we have.
        qs = PriceHistory.objects.filter(
            symbol__symbol__in=all_symbols,
            date__gte=start_dt,
            date__lte=max_lookahead
        ).values('symbol__symbol', 'date', 'close')

        # Create Price Map: (Symbol, Date) -> Close
        price_map = {}
        for row in qs:
            price_map[(row['symbol__symbol'], row['date'])] = row['close']

        # Use Pandas for Business Day offsets
        # Create a date range index for business days
        bday_dates = pd.date_range(start=start_dt, end=max_lookahead, freq='B').date
        bday_list = bday_dates.tolist()
        
        # Helper to find Nth business day after a date
        def get_sell_date(start_d, n):
            try:
                # Find the first business day >= start_d
                start_idx = -1
                for i, d in enumerate(bday_list):
                    if d >= start_d:
                        start_idx = i
                        break
                
                if start_idx == -1: return None
                
                sell_idx = start_idx + n
                if sell_idx < len(bday_list):
                    return bday_list[sell_idx]
            except:
                pass
            return None

        trades_result = []
        
        for p in picks:
            sell_date = get_sell_date(p.date, hold_days)
            # If sell date is in future (or very recent/today where data might be missing), allow it?
            # For backtest, we skip if we don't have price yet.
            if not sell_date:
                continue

            # Look for price on Sell Date
            found_price = None
            actual_sell_date = sell_date
            
            # Simple fallback search for price (e.g. data gap)
            for offset in range(3):
                check_date = sell_date + timedelta(days=offset)
                if (p.symbol, check_date) in price_map:
                    found_price = price_map[(p.symbol, check_date)]
                    actual_sell_date = check_date
                    break
            
            if found_price is None:
                continue 

            # Calculate Return
            buy_price = p.price
            if not buy_price or buy_price <= 0:
                continue # Skip invalid data

            pnl_pct = (found_price - buy_price) / buy_price * 100
            
            trades_result.append({
                "date": p.date.strftime('%Y-%m-%d'),
                "symbol": p.symbol,
                "symbol": p.symbol,
                "strategy": p.strategy.replace(' Aggressive', '').replace(' Defensive', '').replace(', Kumo Break', '').replace('Kumo Break', '').strip(', '),
                "buy_price": buy_price,
                "sell_date": actual_sell_date.strftime('%Y-%m-%d'),
                "sell_price": found_price,
                "return_pct": round(pnl_pct, 2),
                "win": pnl_pct > 0
            })

        # 3. Aggregate Stats & Build Chart Data
        if not trades_result:
            return JsonResponse({
                "stats": {
                    "total_trades": 0, "win_rate": 0, "avg_return": 0, "cum_return": 0
                }, 
                "trades": [],
                "chart": []
            })
            
        df = pd.DataFrame(trades_result)
        total_trades = len(df)
        win_count = len(df[df['return_pct'] > 0])
        win_rate = (win_count / total_trades * 100) if total_trades > 0 else 0
        avg_ret = df['return_pct'].mean()
        cumulative_return = df['return_pct'].sum()

        # Build Equity Curve (Cumulative Sum by Sell Date)
        # We use Sell Date because that's when PnL is realized
        df['sell_date'] = pd.to_datetime(df['sell_date'])
        df = df.sort_values('sell_date')
        
        # Group by date to sum daily pnl
        daily_pnl = df.groupby('sell_date')['return_pct'].sum().reset_index()
        daily_pnl['cum_sum'] = daily_pnl['return_pct'].cumsum()
        
        chart_data = []
        for _, row in daily_pnl.iterrows():
            chart_data.append({
                "date": row['sell_date'].strftime('%Y-%m-%d'),
                "value": round(row['cum_sum'], 2)
            })

        return JsonResponse({
            "stats": {
                "total_trades": total_trades,
                "win_rate": round(win_rate, 1),
                "avg_return": round(avg_ret, 2),
                "cum_return": round(cumulative_return, 2)
            },
            "trades": trades_result,
            "chart": chart_data
        })

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return JsonResponse({"error": str(e)}, status=500)
