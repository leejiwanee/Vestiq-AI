from django.shortcuts import render, get_object_or_404, redirect
import yfinance as yf
from django.utils import timezone
from decimal import Decimal
from django.views.generic import ListView, CreateView, UpdateView, DeleteView, DetailView, TemplateView
import json
from datetime import timedelta, datetime
import calendar
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from .models import TradeRecord, TradeTransaction
from .forms import TradeForm
from django.db.models import Sum
from django.http import JsonResponse
from django.conf import settings
import requests
from updatedata.models import Ticker, PriceHistory
from .services import analyze_trade

def get_calendar_context(user, year, month):
    """Helper to generate calendar grid data for a specific month."""
    # 1. Fetch Data
    buy_txs = TradeTransaction.objects.filter(
        trade__user=user,
        type='BUY',
        date__year=year,
        date__month=month
    ).select_related('trade')
    
    sell_trades = TradeRecord.objects.filter(
        user=user,
        sell_date__year=year,
        sell_date__month=month
    )
    
    # 2. Organize data by day
    daily_data = {}
    
    # Process Buys
    for tx in buy_txs:
        day = tx.date.day
        if day not in daily_data:
            daily_data[day] = {'buys': [], 'sells': [], 'pl': 0, 'invested': 0}
        
        daily_data[day]['buys'].append(tx)
        daily_data[day]['invested'] += tx.amount
        
    # Process Sells
    for trade in sell_trades:
        day = trade.sell_date.day
        if day not in daily_data:
            daily_data[day] = {'buys': [], 'sells': [], 'pl': 0, 'invested': 0}
        
        if trade.profit_amount:
            trade.abs_profit = abs(trade.profit_amount)
        
        daily_data[day]['sells'].append(trade)
        if trade.profit_amount:
            daily_data[day]['pl'] += trade.profit_amount

    # 3. Build Calendar Grid
    cal = calendar.Calendar(firstweekday=6) # Sunday first
    month_days = cal.monthdayscalendar(year, month)
    
    calendar_rows = []
    today = timezone.now().date()
    
    for week in month_days:
        week_data = []
        for day in week:
            if day == 0:
                week_data.append(None) # Empty day
            else:
                data = daily_data.get(day, {})
                is_today = (year == today.year and month == today.month and day == today.day)
                
                week_data.append({
                    'day': day,
                    'is_today': is_today,
                    'buys': data.get('buys', []),
                    'sells': data.get('sells', []),
                    'pl': data.get('pl', 0),
                    'invested': data.get('invested', 0),
                    'has_activity': bool(data)
                })
        calendar_rows.append(week_data)
        
    return calendar_rows

class TradeListView(LoginRequiredMixin, ListView):
    model = TradeRecord
    template_name = 'trades/trade_list.html'
    context_object_name = 'trades'

    def get_queryset(self):
        # Base Queryset: filter by user and strict ordering
        return TradeRecord.objects.filter(user=self.request.user).order_by('-buy_date')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # --- 0. Date Filtering Logic ---
        today = timezone.now().date()
        year_param = self.request.GET.get('year')
        month_param = self.request.GET.get('month')
        
        try:
            selected_year = int(year_param) if year_param else today.year
            selected_month = int(month_param) if month_param else today.month
        except ValueError:
            selected_year = today.year
            selected_month = today.month
            
        if selected_month < 1 or selected_month > 12: 
            selected_month = today.month

        # Filter Trades (Journal) for this specific month
        # Note: We filter by buy_date or sell_date? Usually Journal is by entry activity or just presence.
        # User requested: "First photo section always shows current month only" implies Filtering.
        # Let's show trades that were Bought OR Sold in this month? Or just strictly one?
        # Standard Ledger practice: Show entries (transactions) in that month.
        # But our TradeRecord is a full trade cycle.
        # Let's filter by BUY DATE in this month for "New Positions" and SELL DATE for "Closed".
        # Creating a combined list might be complex for the template.
        # Simplest approach for "Journal": Show trades initiated (Buy Date) in this month.
        # OR match the Calendar logic: Activity.
        # Let's stick to: "Active in this month" or just "Buy Date in this month"? 
        # User likely wants to see what happened.
        # Let's filter by: Trades where Buy Date is in Month OR Sell Date is in Month.
        # context['filtered_trades'] = ...
        
        # Actually, standard behavior for "Monthly Journal" is typically "Trades closed in this month" + "Trades opened in this month".
        # Let's just filter the main `trades` list by Buy Date for now as it's the primary timeline anchor.
        # User said "records... first photo section... always current month".
        # Let's filter by Buy Date descending.
        
        # Wait, if I filter the main list, I lose "Open Trades" for the Wallet calculation!
        # Context 'trades' comes from get_queryset which is ALL trades.
        # I should NOT filter get_queryset if I need global stats, OR I should do separate queries.
        # Doing separate queries is cleaner.
        
        all_trades = TradeRecord.objects.filter(user=self.request.user)
        
        # 1. Wallet Logic (Global Open Trades)
        # --- 1. Wallet Logic (Global Open Trades) ---
        # Data Ladder Strategy: DB -> yfinance -> FMP
        open_trades = [t for t in all_trades if not t.sell_date]
        tickers_needed = list(set(t.ticker for t in open_trades))
        prices = {}
        
        if tickers_needed:
            # Level 1: Check Local DB (PriceHistory)
            db_found = []
            for ticker in tickers_needed:
                try:
                    latest_ph = PriceHistory.objects.filter(symbol__symbol=ticker).order_by('-date').first()
                    if latest_ph and latest_ph.close:
                        prices[ticker] = Decimal(str(latest_ph.close))
                        db_found.append(ticker)
                except Exception:
                    pass
            
            # Level 2: yfinance for missing
            yf_needed = list(set(tickers_needed) - set(db_found))
            if yf_needed:
                try:
                    if len(yf_needed) == 1:
                        top = yf_needed[0]
                        # Try fast_info first
                        price = yf.Ticker(top).fast_info.get('last_price')
                        if not price:
                            # Fallback to download (slower but more robust)
                            df = yf.download(top, period="1d", progress=False)
                            if not df.empty:
                                val = df['Close'].iloc[-1]
                                price = val.item() if hasattr(val, 'item') else val
                        
                        if price:
                            prices[top] = Decimal(str(price))
                    else:
                        ticker_str = " ".join(yf_needed)
                        ytickers = yf.Tickers(ticker_str)
                        for ticker in yf_needed:
                            try:
                                price = ytickers.tickers[ticker].fast_info.get('last_price')
                                if not price:
                                     # Individual fallback for failed items in batch
                                     df = yf.download(ticker, period="1d", progress=False)
                                     if not df.empty:
                                         val = df['Close'].iloc[-1]
                                         price = val.item() if hasattr(val, 'item') else val
                                
                                if price:
                                    prices[ticker] = Decimal(str(price))
                            except Exception:
                                pass
                except Exception:
                    pass

        total_invested = Decimal('0.00')
        total_valuation = Decimal('0.00')
        total_realized_profit = Decimal('0.00') # Lifetime realized

        for trade in open_trades:
            if trade.ticker in prices:
                current_price = prices[trade.ticker]
                trade.current_price = current_price
                if trade.buy_price and trade.invested_amount:
                    quantity = trade.invested_amount / trade.buy_price
                    current_value = quantity * current_price
                    trade.unrealized_profit = current_value - trade.invested_amount
                    if trade.invested_amount:
                        trade.unrealized_percent = (trade.unrealized_profit / trade.invested_amount) * 100
                    total_invested += trade.invested_amount
                    total_valuation += current_value
            else:
                total_invested += trade.invested_amount
                total_valuation += trade.invested_amount

        for trade in all_trades:
            if trade.sell_date and trade.profit_amount:
                total_realized_profit += trade.profit_amount

        cash_balance = Decimal(str(self.request.session.get('cash_balance', 0)))
        total_unrealized_profit = total_valuation - total_invested
        total_valuation_final = cash_balance + total_invested + total_unrealized_profit

        context['total_invested'] = total_invested
        context['total_valuation'] = total_valuation_final
        context['cash_balance'] = cash_balance
        context['total_unrealized_profit'] = total_unrealized_profit
        context['total_realized_profit'] = total_realized_profit

        # --- 2. Month-over-Month Stats (Selected Month vs Previous) ---
        # Previous Month Calculation
        if selected_month == 1:
            prev_year_mom = selected_year - 1
            prev_month_mom = 12
        else:
            prev_year_mom = selected_year
            prev_month_mom = selected_month - 1
            
        current_month_pl = TradeRecord.objects.filter(
            user=self.request.user,
            sell_date__year=selected_year,
            sell_date__month=selected_month
        ).aggregate(Sum('profit_amount'))['profit_amount__sum'] or Decimal('0.00')
        
        previous_month_pl = TradeRecord.objects.filter(
            user=self.request.user,
            sell_date__year=prev_year_mom,
            sell_date__month=prev_month_mom
        ).aggregate(Sum('profit_amount'))['profit_amount__sum'] or Decimal('0.00')
        
        context['current_month_pl'] = current_month_pl
        context['previous_month_pl'] = previous_month_pl
        
        if previous_month_pl != 0:
            context['mom_delta'] = current_month_pl - previous_month_pl
        else:
             context['mom_delta'] = current_month_pl 

        # --- 3. Calendar & Navigation Context ---
        context['calendar_rows'] = get_calendar_context(self.request.user, selected_year, selected_month)
        
        # Calc Nav Dates
        first_day = datetime(selected_year, selected_month, 1).date()
        if selected_month == 12:
            next_month_date = datetime(selected_year + 1, 1, 1).date()
        else:
            next_month_date = datetime(selected_year, selected_month + 1, 1).date()
            
        if selected_month == 1:
            prev_month_date = datetime(selected_year - 1, 12, 1).date()
        else:
            prev_month_date = datetime(selected_year, selected_month - 1, 1).date()
            
        context['selected_date'] = first_day
        context['next_year'] = next_month_date.year
        context['next_month'] = next_month_date.month
        context['prev_year'] = prev_month_date.year
        context['prev_month'] = prev_month_date.month
        
        # --- 4. Filtered Journal Trades ---
        # Show trades that:
        # 1. Were bought in this month
        # 2. Were sold in this month
        # 3. Are still open (no sell_date) and were bought before or in this month
        from datetime import datetime as dt
        from django.db.models import Q
        
        selected_month_start = dt(selected_year, selected_month, 1).date()
        if selected_month == 12:
            selected_month_end = dt(selected_year + 1, 1, 1).date()
        else:
            selected_month_end = dt(selected_year, selected_month + 1, 1).date()
        
        context['trades'] = all_trades.filter(
            Q(buy_date__year=selected_year, buy_date__month=selected_month) |  # Bought this month
            Q(sell_date__year=selected_year, sell_date__month=selected_month) |  # Sold this month
            Q(sell_date__isnull=True, buy_date__lt=selected_month_end)  # Open trades bought before or in this month
        ).distinct().order_by('-buy_date')
        
        
        return context

class TradeCreateView(LoginRequiredMixin, CreateView):
    model = TradeRecord
    form_class = TradeForm
    template_name = 'trades/trade_form.html'
    success_url = reverse_lazy('trade_list')

    def form_valid(self, form):
        form.instance.user = self.request.user
        try:
            current_cash = float(self.request.session.get('cash_balance', 0))
            invested = float(form.instance.invested_amount)
            self.request.session['cash_balance'] = current_cash - invested
        except (ValueError, TypeError):
            pass
        return super().form_valid(form)

class TradeUpdateView(LoginRequiredMixin, UpdateView):
    model = TradeRecord
    form_class = TradeForm
    template_name = 'trades/trade_form.html'
    success_url = reverse_lazy('trade_list')

    def get_queryset(self):
        return TradeRecord.objects.filter(user=self.request.user)

class TradeDeleteView(LoginRequiredMixin, DeleteView):
    model = TradeRecord
    template_name = 'trades/trade_confirm_delete.html'
    success_url = reverse_lazy('trade_list')

    def get_queryset(self):
        return TradeRecord.objects.filter(user=self.request.user)

class TradeCloseView(LoginRequiredMixin, UpdateView):
    model = TradeRecord
    fields = ['sell_date', 'sell_price']
    template_name = 'trades/trade_close.html'
    success_url = reverse_lazy('trade_list')

    def get_queryset(self):
        return TradeRecord.objects.filter(user=self.request.user, sell_date__isnull=True)

    def form_valid(self, form):
        try:
            trade = form.instance
            sell_price = form.cleaned_data.get('sell_price')
            if sell_price and trade.buy_price and trade.invested_amount:
                quantity = float(trade.invested_amount) / float(trade.buy_price)
                proceeds = quantity * float(sell_price)
                current_cash = float(self.request.session.get('cash_balance', 0))
                self.request.session['cash_balance'] = current_cash + proceeds
        except Exception as e:
            print(f"Error updating cash on close: {e}")
        return super().form_valid(form)

    def get_initial(self):
        initial = super().get_initial()
        initial['sell_date'] = timezone.now().date()
        try:
            ticker = self.object.ticker
            price = yf.Ticker(ticker).fast_info['last_price']
            if price:
                initial['sell_price'] = round(price, 2)
        except Exception:
            pass
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        trade = self.object
        if trade.buy_price and trade.invested_amount:
            context['quantity'] = trade.invested_amount / trade.buy_price
        return context

class TradeDetailView(LoginRequiredMixin, DetailView):
    model = TradeRecord
    template_name = 'trades/trade_detail.html'
    context_object_name = 'trade'

    def get_queryset(self):
        return TradeRecord.objects.filter(user=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        trade = self.object
        if not trade.transactions.exists():
            TradeTransaction.objects.create(
                trade=trade,
                date=trade.buy_date,
                type='BUY',
                price=trade.buy_price,
                amount=trade.invested_amount,
                quantity=trade.invested_amount / trade.buy_price if trade.buy_price else 0
            )

        start_date = trade.buy_date
        end_date = trade.sell_date if trade.sell_date else timezone.now().date()
        if end_date < start_date:
            end_date = start_date

        try:
            yf_end = end_date + timedelta(days=1)
            df = yf.download(trade.ticker, start=start_date, end=yf_end, progress=False)
            
            if not df.empty:
                transactions = trade.transactions.all().order_by('date')
                dates = []
                values = []
                invested_data = []
                history_table = []
                
                tx_by_date = {}
                for tx in transactions:
                    tx_date_str = tx.date.strftime('%Y-%m-%d')
                    if tx_date_str not in tx_by_date:
                        tx_by_date[tx_date_str] = []
                    tx_by_date[tx_date_str].append(tx)

                for index, row in df.iterrows():
                    date_str = index.strftime('%Y-%m-%d')
                    date_obj = index.date()
                    daily_txs = transactions.filter(date__lte=date_obj)
                    
                    day_quantity = Decimal('0.00')
                    day_invested = Decimal('0.00')
                    
                    for tx in daily_txs:
                        if tx.type == 'BUY':
                            day_quantity += tx.quantity
                            day_invested += tx.amount
                        elif tx.type == 'SELL':
                            day_quantity -= tx.quantity
                            if day_quantity > 0:
                                avg_price = day_invested / (day_quantity + tx.quantity)
                                day_invested -= tx.quantity * avg_price
                        elif tx.type == 'SPLIT':
                            if tx.quantity:
                                day_quantity = day_quantity * tx.quantity

                    close_price = Decimal(str(row['Close'].iloc[0])) if hasattr(row['Close'], 'iloc') else Decimal(str(row['Close']))
                    daily_value = day_quantity * close_price
                    daily_pl = daily_value - day_invested
                    daily_pl_pct = (daily_pl / day_invested * 100) if day_invested > 0 else 0
                    
                    dates.append(date_str)
                    values.append(float(daily_value))
                    invested_data.append(float(day_invested))
                    
                    day_transactions = tx_by_date.get(date_str, [])
                    tx_type = ", ".join([t.type for t in day_transactions]) if day_transactions else ""
                    
                    history_table.append({
                        'date': date_str,
                        'type': tx_type,
                        'price': close_price,
                        'quantity': day_quantity,
                        'invested': day_invested,
                        'value': daily_value,
                        'pl': daily_pl,
                        'pl_pct': daily_pl_pct
                    })
                
                context['history_table'] = history_table[::-1]
                context['chart_labels'] = json.dumps(dates)
                context['chart_data'] = json.dumps(values)
                context['invested_data'] = json.dumps(invested_data)
                
                if values:
                    current_val = Decimal(str(values[-1]))
                    initial_val = Decimal(str(invested_data[-1])) if invested_data else Decimal('0.00')
                    total_return = current_val - initial_val
                    return_pct = (total_return / initial_val) * 100 if initial_val != 0 else 0
                    context['total_return'] = round(total_return, 2)
                    context['return_pct'] = round(return_pct, 2)
                    context['current_value'] = round(current_val, 2)

        except Exception as e:
            print(f"Error fetching history for {trade.ticker}: {e}")
            context['error'] = str(e)
            
        return context

class TradeAddView(LoginRequiredMixin, CreateView):
    model = TradeTransaction
    fields = ['date', 'price', 'amount']
    template_name = 'trades/trade_add.html'
    
    def get_success_url(self):
        return reverse_lazy('trade_history', kwargs={'pk': self.kwargs['pk']})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['trade'] = get_object_or_404(TradeRecord, pk=self.kwargs['pk'], user=self.request.user)
        return context

    def form_valid(self, form):
        trade = get_object_or_404(TradeRecord, pk=self.kwargs['pk'], user=self.request.user)
        form.instance.trade = trade
        form.instance.type = 'BUY'
        try:
            current_cash = float(self.request.session.get('cash_balance', 0))
            amount = float(form.instance.amount)
            self.request.session['cash_balance'] = current_cash - amount
        except (ValueError, TypeError):
            pass
        response = super().form_valid(form)
        trade.update_totals()
        return response

class TradeCalendarView(LoginRequiredMixin, TemplateView):
    template_name = 'trades/trade_calendar.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        today = timezone.now().date()
        year_param = self.request.GET.get('year')
        month_param = self.request.GET.get('month')
        
        try:
            selected_year = int(year_param) if year_param else today.year
            selected_month = int(month_param) if month_param else today.month
        except ValueError:
            selected_year = today.year
            selected_month = today.month
            
        if selected_month < 1 or selected_month > 12: selected_month = today.month
        
        # Calc prev/next for nav
        first_day = datetime(selected_year, selected_month, 1).date()
        if selected_month == 12:
            next_month_date = datetime(selected_year + 1, 1, 1).date()
        else:
            next_month_date = datetime(selected_year, selected_month + 1, 1).date()
        if selected_month == 1:
            prev_month_date = datetime(selected_year - 1, 12, 1).date()
        else:
            prev_month_date = datetime(selected_year, selected_month - 1, 1).date()

        context['selected_year'] = selected_year
        context['selected_month'] = selected_month
        context['current_date'] = first_day
        context['prev_year'] = prev_month_date.year
        context['prev_month'] = prev_month_date.month
        context['next_year'] = next_month_date.year
        context['next_month'] = next_month_date.month
        
        context['calendar_rows'] = get_calendar_context(self.request.user, selected_year, selected_month)
        
        return context

def analyze_trade_view(request, pk):
    if request.method != "POST":
        return JsonResponse({"error": "POST request required"}, status=405)
    trade = get_object_or_404(TradeRecord, pk=pk, user=request.user)
    if not trade.sell_date:
        return JsonResponse({"error": "Trade must be closed to analyze."}, status=400)
    analysis = analyze_trade(trade)
    trade.ai_analysis = analysis
    trade.save()
    return JsonResponse({"analysis": analysis})

def update_cash_balance(request):
    if request.method == "POST":
        try:
            import json
            data = json.loads(request.body)
            cash_value = data.get('cash_balance', 0)
            request.session['cash_balance'] = float(cash_value)
            return JsonResponse({"success": True, "cash_balance": float(cash_value)})
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)
    return JsonResponse({"error": "POST required"}, status=405)
