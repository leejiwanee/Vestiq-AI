from django.contrib import admin
from django.urls import path
from django.urls import path
from django.http import HttpResponseRedirect, JsonResponse
from django.contrib import messages
from django.shortcuts import render
from django.db import connection
from .models import Ticker, FundamentalData, PriceHistory, CronJob
from .tasks import run_update_ticker_list
from cron.daily_jobs import ensure_fundamentals_update, ensure_price_history_update

class MarketListFilter(admin.SimpleListFilter):
    title = 'Market'
    parameter_name = 'market'

    def lookups(self, request, model_admin):
        return (
            ('sp500', 'S&P 500'),
            ('nasdaq', 'NASDAQ 100'),
            ('sp500,nasdaq', 'S&P 500 & NASDAQ'),
        )

    def queryset(self, request, queryset):
        if not self.value():
            return queryset
            
        value = self.value()
        
        # If Ticker
        if hasattr(queryset.model, 'market'):
             return queryset.filter(market=value)
             
        # If Related (FundamentalData, PriceHistory)
        if hasattr(queryset.model, 'symbol'):
             return queryset.filter(symbol__market=value)
             
        return queryset

class SectorListFilter(admin.SimpleListFilter):
    title = 'Sector'
    parameter_name = 'sector'

    def lookups(self, request, model_admin):
        # Use Ticker table for sectors now
        sectors = Ticker.objects.order_by('sector').values_list('sector', flat=True).distinct()
        return [(s, s) for s in sectors if s]

    def queryset(self, request, queryset):
        if self.value():
            # If Ticker
            if hasattr(queryset.model, 'sector'):
                return queryset.filter(sector=self.value())
            # If FundamentalData / PriceHistory
            elif hasattr(queryset.model, 'symbol'):
                return queryset.filter(symbol__sector=self.value())
        return queryset

@admin.register(Ticker)
class TickerAdmin(admin.ModelAdmin):
    list_display = ('symbol', 'name', 'market', 'sector', 'industry', 'updated_at')
    search_fields = ('symbol', 'name')
    list_filter = (MarketListFilter, SectorListFilter) 
    change_list_template = "admin/updatedata/ticker/change_list.html"

    def changelist_view(self, request, extra_context=None):
        total = Ticker.objects.count()
        extra_context = extra_context or {}
        extra_context['stats'] = {'total': total}
        return super().changelist_view(request, extra_context=extra_context)

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('update-ticker-list/', self.admin_site.admin_view(self.update_ticker_list_view), name='update_ticker_list'),
            path('update-fundamentals/', self.admin_site.admin_view(self.update_fundamentals_view), name='update_fundamentals'),
            path('update-price-history/', self.admin_site.admin_view(self.update_price_history_view), name='update_price_history'),

        ]
        return custom_urls + urls

    def update_ticker_list_view(self, request):
        """
        [Manual] Truncate Ticker & Rebuild
        """
        import threading
        # Ensure we import the logic and cache helper
        from updatedata.tasks import run_update_ticker_list, _set_progress
        
        def task():
            try:
                _set_progress('progress_ticker_list', 0, "Initializing: Truncating old data...")
                
                # [User Request] Do NOT hard truncate. 
                # run_update_ticker_list handles "Soft Truncate" (deletes only obsolete tickers)
                # Ticker.objects.all().delete() # REMOVED: Preserves PriceHistory

                
                # Rebuild
                run_update_ticker_list(force_update=True)
            except Exception as e:
                print(f"Error in background ticker update: {e}")
                _set_progress('progress_ticker_list', 100, f"Error: {e}", is_finished=True)

        threading.Thread(target=task).start()
        
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({"status": "success", "message": "Ticker List Update started in background."})

        self.message_user(request, "Ticker Truncate & Rebuild started in background.", messages.SUCCESS)
        return HttpResponseRedirect("../")

    def update_fundamentals_view(self, request):
        import threading
        # Ensure we import the logic
        from updatedata.tasks import _set_progress
        
        def task():
            try:
                _set_progress('progress_fundamentals', 0, "Requesting Update...")
                ran = ensure_fundamentals_update(force=True)
                if ran is False:
                     # It was skipped (locked)
                     _set_progress('progress_fundamentals', 100, "Skipped: Already Running.", is_finished=True)
            except Exception as e:
                print(f"Error in background fundamentals update: {e}")
                _set_progress('progress_fundamentals', 100, f"Error: {e}", is_finished=True)
                
        threading.Thread(target=task).start()

        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({"status": "success", "message": "Fundamentals Update started in background."})

        self.message_user(request, "Fundamentals Update started in background.", messages.SUCCESS)
        return HttpResponseRedirect("../")

    def update_price_history_view(self, request):
        """
        [Manual] Update Price History (Today only)
        - Keeps past data.
        """
        import threading
        # Ensure we import the logic
        from cron.daily_jobs import ensure_price_history_update
        from updatedata.tasks import _set_progress
        
        def task():
            try:
                _set_progress('progress_price_history', 0, "Requesting Update...")
                ran = ensure_price_history_update(force=True)
                if ran is False:
                     _set_progress('progress_price_history', 100, "Skipped: Already Running.", is_finished=True)
            except Exception as e:
                print(f"Error in background price update: {e}")
                _set_progress('progress_price_history', 100, f"Error: {e}", is_finished=True)
                
        threading.Thread(target=task).start()

        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({"status": "success", "message": "Price History Update (Today) started in background."})

        self.message_user(request, "Price History Update (Today) started in background.", messages.SUCCESS)
        return HttpResponseRedirect("../")



@admin.register(FundamentalData)
class FundamentalDataAdmin(admin.ModelAdmin):
    list_display = (
        'get_symbol', 'date', 
        'market_cap', 'pe_ratio', 'pb_ratio', 
        'return_on_equity_ttm', 'earnings_yield_ttm', 'updated_at'
    )
    list_filter = ('date', MarketListFilter, SectorListFilter)
    
    fieldsets = (
        ('Ticker Info', {
            'fields': ('symbol', 'date', 'updated_at')
        }),
        ('Calculated Parameters (Preserved)', {
            'fields': ('pe_ratio', 'pb_ratio', 'eps_ttm', 'book_value_per_share')
        }),
        ('Valuation (FMP TTM)', {
            'fields': (
                'market_cap', 'enterprise_value_ttm', 
                'ev_to_sales_ttm', 'ev_to_ebitda_ttm',
                'ev_to_operating_cash_flow_ttm', 'ev_to_free_cash_flow_ttm'
            )
        }),
        ('Profitability & Returns', {
            'fields': (
                'earnings_yield_ttm', 'free_cash_flow_yield_ttm',
                'return_on_equity_ttm', 'return_on_assets_ttm', 'operating_return_on_assets_ttm',
                'return_on_invested_capital_ttm', 'return_on_capital_employed_ttm',
                'return_on_tangible_assets_ttm'
            )
        }),
        ('Financial Health', {
            'fields': (
                'current_ratio_ttm', 'net_debt_to_ebitda_ttm',
                'interest_burden_ttm', 'tax_burden_ttm', 'income_quality_ttm',
                'graham_number_ttm', 'graham_net_net_ttm'
            )
        }),
        ('Efficiency & Cycles', {
            'fields': (
                'days_of_sales_outstanding_ttm', 'days_of_inventory_outstanding_ttm', 'days_of_payables_outstanding_ttm',
                'operating_cycle_ttm', 'cash_conversion_cycle_ttm',
                'average_receivables_ttm', 'average_inventory_ttm', 'average_payables_ttm'
            )
        }),
        ('Capital & Assets', {
            'fields': (
                'working_capital_ttm', 'invested_capital_ttm', 
                'tangible_asset_value_ttm', 'net_current_asset_value_ttm',
                'intangibles_to_total_assets_ttm'
            )
        }),
        ('Ratios to Revenue', {
            'fields': (
                'capex_to_revenue_ttm', 
                'research_and_developement_to_revenue_ttm', 
                'sales_general_and_administrative_to_revenue_ttm',
                'stock_based_compensation_to_revenue_ttm'
            )
        }),
        ('Cash Flow & Capex', {
            'fields': (
                'free_cash_flow_to_equity_ttm', 'free_cash_flow_to_firm_ttm',
                'capex_to_operating_cash_flow_ttm', 'capex_to_depreciation_ttm'
            )
        })
    )
    search_fields = ('symbol__symbol', 'symbol__name')
    
    def get_symbol(self, obj):
        return obj.symbol.symbol
    get_symbol.short_description = 'Symbol'
    get_symbol.admin_order_field = 'symbol__symbol'

    def get_name(self, obj):
        return obj.symbol.name
    get_name.short_description = 'Name'

@admin.register(PriceHistory)
class PriceHistoryAdmin(admin.ModelAdmin):
    list_display = ('symbol', 'date', 'close', 'volume', 'change_percent')
    list_filter = ('date', MarketListFilter)
    search_fields = ('symbol__symbol',)

@admin.register(CronJob)
class CronJobAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active', 'is_running', 'locked_at', 'last_run')
    list_editable = ('is_active', 'is_running')
    
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('run-sql/', self.admin_site.admin_view(self.run_sql_view), name='run_sql'),
            path('toggle/<int:job_id>/', self.admin_site.admin_view(self.toggle_cron_view), name='toggle_cron'),
        ]
        return custom_urls + urls

    def toggle_cron_view(self, request, job_id):
        try:
            job = CronJob.objects.get(id=job_id)
            job.is_active = not job.is_active
            job.save()
            status = "Enabled" if job.is_active else "Disabled"
            messages.success(request, f"{job.name} is now {status}.")
        except CronJob.DoesNotExist:
            messages.error(request, "CronJob not found.")
        return HttpResponseRedirect(request.META.get('HTTP_REFERER', '/admin/'))

    def run_sql_view(self, request):
        table_names = connection.introspection.table_names()
        context = {
            'title': 'Run Custom SQL',
            'site_header': self.admin_site.site_header,
            'site_title': self.admin_site.site_title,
            'has_permission': True,
            'tables': table_names,
        }
        if request.method == 'POST':
            sql = request.POST.get('sql')
            context['sql'] = sql
            try:
                with connection.cursor() as cursor:
                    cursor.execute(sql)
                    if cursor.description:
                        columns = [col[0] for col in cursor.description]
                        results = cursor.fetchall()
                        context['columns'] = columns
                        context['results'] = results
                    else:
                        messages.success(request, f"Executed successfully. Rows affected: {cursor.rowcount}")
            except Exception as e:
                messages.error(request, f"SQL Error: {e}")
        
        return render(request, 'admin/updatedata/run_sql.html', context)
