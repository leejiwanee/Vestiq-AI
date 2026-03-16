from django.shortcuts import render, redirect
from django.conf import settings
from django.http import JsonResponse
from django.db.models import Q
from updatedata.models import Ticker, FundamentalData
import requests
import yfinance as yf
from datetime import datetime, timedelta

def index(request):
    """Search Input Page"""
    return render(request, 'search/index.html')

def profile(request, symbol):
    """Company Profile Dashboard"""
    symbol = symbol.upper()
    
    # 1. Fetch Ticker from DB
    ticker = Ticker.objects.filter(symbol=symbol).first()
    
    profile_data = {}
    fundamentals = {}
    
    if ticker:
        profile_data = {
            'name': ticker.name,
            'sector': ticker.sector,
            'industry': ticker.industry,
            'description': ticker.description,
            'ceo': ticker.ceo,
            'website': getattr(ticker, 'website', None), # Safely get website
            'image': ticker.image,
            'exchange': getattr(ticker, 'exchange', ticker.market), # Use market if exchange missing
            'price_range': getattr(ticker, 'price_range', None), # 52 Week Range
        }
        
        # Latest Fundamentals from DB
        fund = ticker.fundamentals.order_by('-date').first()
        if fund:
            fundamentals = {
                'market_cap': fund.market_cap,
                'pe': fund.pe_ratio,
                'eps': fund.eps_ttm,
                'pbr': fund.pb_ratio,
                'roe': fund.return_on_equity_ttm,
            }
            
        # [NEW] Latest Price from DB (Required for 52-week range & header)
        latest_price = ticker.price_history.order_by('-date').first()
        if latest_price:
            profile_data['price'] = latest_price.close
            profile_data['changes'] = latest_price.change_amount
            profile_data['change_p'] = latest_price.change_percent
            
    # 2. FMP Fallback / Live Data
    if not profile_data or not fundamentals:
        try:
            fmp_key = settings.FMP_API_KEY
            if fmp_key:
                # Profile
                p_url = f"https://financialmodelingprep.com/stable/profile?symbol={symbol}&apikey={fmp_key}"
                p_res = requests.get(p_url, timeout=5).json()
                if p_res:
                    p = p_res[0]
                    profile_data.update({
                        'name': p.get('companyName'),
                        'sector': p.get('sector'),
                        'industry': p.get('industry'),
                        'description': p.get('description'),
                        'ceo': p.get('ceo'),
                        'website': p.get('website'),
                        'image': p.get('image'),
                        'exchange': p.get('exchangeShortName'),
                        'price': p.get('price'),
                        'changes': p.get('change'),
                        'price_range': p.get('range'), # Map 'range' to 'price_range'
                    })
                    

                
                # Fundamentals (Key Metrics)
                # Fetch if completely missing OR if critical fields (like EPS) are missing
                if not fundamentals or fundamentals.get('eps') is None:
                    m_url = f"https://financialmodelingprep.com/stable/key-metrics-ttm?symbol={symbol}&apikey={fmp_key}"
                    m_res = requests.get(m_url, timeout=5).json()
                    if m_res:
                        m = m_res[0]
                        # Merge: Overwrite or set if missing. 
                        # Since we only entered here if data was missing/incomplete, using live data is safe.
                        fundamentals.update({
                            'market_cap': m.get('marketCap'),
                            'pe': m.get('peRatioTTM'),
                            'eps': m.get('netIncomePerShareTTM'), # Approx
                            'pbr': m.get('pbRatioTTM'),
                            'roe': m.get('returnOnEquityTTM'),
                        })
        except Exception as e:
            print(f"FMP Fetch Error: {e}")

    # --- ROBUST RANGE PARSING (moved here to apply to both DB and API data) ---
    # Ensure year_low/high are available for the template
    pr = profile_data.get('price_range')
    if pr and '-' in str(pr):
        try:
            # Handle cases like "10.5-20.3" or "10.5 - 20.3"
            parts = str(pr).split('-')
            if len(parts) == 2:
                 profile_data['year_low'] = float(parts[0].strip())
                 profile_data['year_high'] = float(parts[1].strip())
        except (ValueError, AttributeError):
            pass # Fail silently, template handles missing data

    # 3. News (FMP Stock News)
    news_list = []
    try:
        fmp_key = settings.FMP_API_KEY
        if fmp_key:
            # FMP - Stock News (Updated to Stable Endpoint)
            # User Request: Increase limit to 20
            news_url = f"https://financialmodelingprep.com/stable/news/stock?symbols={symbol}&limit=20&apikey={fmp_key}"
            print(f"DEBUG: Fetching News from {news_url}")
            news_res = requests.get(news_url, timeout=5).json()
            print(f"DEBUG: News Response Type: {type(news_res)}, Len: {len(news_res) if isinstance(news_res, list) else 'N/A'}")
            
            if isinstance(news_res, list):
                for item in news_res:
                    news_list.append({
                        'title': item.get('title'),
                        'image': item.get('image'),
                        'site': item.get('site'),
                        'date': item.get('publishedDate', '')[:10], # YYYY-MM-DD
                        'link': item.get('url'),
                        'text': item.get('text')
                    })
    except Exception as e:
        print(f"News Fetch Error: {e}")

    # 4. FMP Financial Statements (Income, Balance, CashFlow)
    financial_stmts = {}
    try:
        fmp_key = settings.FMP_API_KEY
        if fmp_key:
            def get_fmp_data(endpoint, period='annual', limit=10, version='v3'): # Fetch more for growth calc
                # Determine Base URL
                if version == 'stable':
                    base_url = "https://financialmodelingprep.com/stable"
                else:
                    base_url = f"https://financialmodelingprep.com/api/{version}"

                # Construct URL with Query Parameters (Path params /SYMBOL triggered 403 Legacy Error)
                url = f"{base_url}/{endpoint}?symbol={symbol}&period={period}&limit={limit}&apikey={fmp_key}"
                
                try:
                    res = requests.get(url, timeout=5)
                    if res.status_code != 200:
                         print(f"FMP Error [{res.status_code}] on {url}: {res.text[:100]}")
                    if res.status_code == 200:
                        data = res.json()
                        if not data: print(f"FMP Warning: Empty Data from {url}")
                        return data
                except Exception as e:
                    print(f"FMP Exception on {url}: {e}")
                return []

            def calc_growth(current, prev):
                if not prev or prev == 0: return 0
                return ((current - prev) / abs(prev)) * 100

            # Helper to get value safe
            def gv(d, k): return d.get(k) or 0

            # A. Income Statement
            raw_inc_annual = get_fmp_data('income-statement', 'annual', 10, version='stable')
            raw_inc_quarter = get_fmp_data('income-statement', 'quarter', 10, version='stable')
            
            # Helper for naming
            import re
            def to_snake(name):
                s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
                return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()

            # A. Income Statement
            raw_inc_annual = get_fmp_data('income-statement', 'annual', 10, version='stable')
            raw_inc_quarter = get_fmp_data('income-statement', 'quarter', 10, version='stable')
            
            def map_income(data):
                mapped = []
                for i in range(len(data)):
                    curr = data[i]
                    prev = data[i+1] if i+1 < len(data) else {}
                    
                    # 1. Auto-map ALL fields to snake_case
                    item = {to_snake(k): v for k, v in curr.items()}
                    
                    # 2. Universal Trend Calculation
                    for k, v in curr.items():
                        if isinstance(v, (int, float)) and k not in ['calendarYear', 'cik']:
                            prev_val = prev.get(k)
                            if prev_val is not None and isinstance(prev_val, (int, float)) and prev_val != 0:
                                trend = ((v - prev_val) / abs(prev_val)) * 100
                                item[f"{to_snake(k)}_trend"] = round(trend, 1)
                            else:
                                item[f"{to_snake(k)}_trend"] = 0

                    # 3. Add Custom Calculated Fields (overwrites if collision, or adds new)
                    item.update({
                        'revenue_growth': calc_growth(gv(curr, 'revenue'), gv(prev, 'revenue')),
                        'gross_growth': calc_growth(gv(curr, 'grossProfit'), gv(prev, 'grossProfit')),
                        'op_income_growth': calc_growth(gv(curr, 'operatingIncome'), gv(prev, 'operatingIncome')),
                        'net_income_growth': calc_growth(gv(curr, 'netIncome'), gv(prev, 'netIncome')),
                        
                        # Short aliases for template convenience (optional, since auto-map handles full names)
                        'rd_expenses': curr.get('researchAndDevelopmentExpenses'),
                        'sga_expenses': curr.get('sellingGeneralAndAdministrativeExpenses'),
                        'op_expenses': curr.get('operatingExpenses'),
                        'op_income': curr.get('operatingIncome'),
                        
                        # Margin Analysis
                        'gross_margin': (gv(curr, 'grossProfit') / gv(curr, 'revenue') * 100) if gv(curr, 'revenue') else 0,
                        'operating_margin': (gv(curr, 'operatingIncome') / gv(curr, 'revenue') * 100) if gv(curr, 'revenue') else 0,
                        'net_margin': (gv(curr, 'netIncome') / gv(curr, 'revenue') * 100) if gv(curr, 'revenue') else 0,
                    })
                    mapped.append(item)
                return mapped

            financial_stmts['income'] = {
                'annual': map_income(raw_inc_annual), # Pass full list, slice in template if needed
                'quarter': map_income(raw_inc_quarter)
            }

            # B. Balance Sheet
            raw_bal_annual = get_fmp_data('balance-sheet-statement', 'annual', 10, version='stable')
            raw_bal_quarter = get_fmp_data('balance-sheet-statement', 'quarter', 10, version='stable')

            def map_balance(data):
                mapped = []
                for i in range(len(data)):
                    curr = data[i]
                    prev = data[i+1] if i+1 < len(data) else {}
                    
                     # 1. Auto-map ALL fields to snake_case
                    item = {to_snake(k): v for k, v in curr.items()}
                    
                    # 2. Universal Trend Calculation
                    for k, v in curr.items():
                        if isinstance(v, (int, float)) and k not in ['calendarYear', 'cik']:
                            prev_val = prev.get(k)
                            if prev_val is not None and isinstance(prev_val, (int, float)) and prev_val != 0:
                                trend = ((v - prev_val) / abs(prev_val)) * 100
                                item[f"{to_snake(k)}_trend"] = round(trend, 1)
                            else:
                                item[f"{to_snake(k)}_trend"] = 0

                    # 3. Add specific aliases if needed for existing charts
                    item['cash'] = curr.get('cashAndCashEquivalents')  # For Financial Health chart
                    item['total_debt'] = curr.get('totalDebt')  # For Financial Health chart
                    item['short_term_debt'] = curr.get('shortTermDebt')
                    item['long_term_debt'] = curr.get('longTermDebt')
                    item['total_current_assets'] = curr.get('totalCurrentAssets')
                    item['total_current_liabilities'] = curr.get('totalCurrentLiabilities')
                    
                    mapped.append(item)
                return mapped

            financial_stmts['balance'] = {
                'annual': map_balance(raw_bal_annual),
                'quarter': map_balance(raw_bal_quarter)
            }

            # C. Cash Flow
            raw_cf_annual = get_fmp_data('cash-flow-statement', 'annual', 10, version='stable')
            raw_cf_quarter = get_fmp_data('cash-flow-statement', 'quarter', 10, version='stable')

            def map_cashflow(data):
                mapped = []
                for i in range(len(data)):
                    curr = data[i]
                    prev = data[i+1] if i+1 < len(data) else {}
                    
                    # 1. Auto-map all
                    item = {to_snake(k): v for k, v in curr.items()}
                    
                    # 2. Universal Trend Calculation
                    for k, v in curr.items():
                        if isinstance(v, (int, float)) and k not in ['calendarYear', 'cik']:
                            prev_val = prev.get(k)
                            if prev_val is not None and isinstance(prev_val, (int, float)) and prev_val != 0:
                                trend = ((v - prev_val) / abs(prev_val)) * 100
                                item[f"{to_snake(k)}_trend"] = round(trend, 1)
                            else:
                                item[f"{to_snake(k)}_trend"] = 0
                    
                    # 3. Add Calculated
                    item.update({
                        'ocf_growth': calc_growth(gv(curr, 'netCashProvidedByOperatingActivities'), gv(prev, 'netCashProvidedByOperatingActivities')),
                        'fcf_growth': calc_growth(gv(curr, 'freeCashFlow'), gv(prev, 'freeCashFlow')),
                        # Aliases
                        'operating_cf': curr.get('netCashProvidedByOperatingActivities'),
                        'investing_cf': curr.get('netCashUsedForInvestingActivities'),
                        'financing_cf': curr.get('netCashUsedProvidedByFinancingActivities'),
                        'free_cash_flow': curr.get('freeCashFlow'),
                    })
                    mapped.append(item)
                return mapped

            financial_stmts['cashflow'] = {
                'annual': map_cashflow(raw_cf_annual),
                'quarter': map_cashflow(raw_cf_quarter)
            }

            # D. Revenue Segmentation
            try:
                # Use 'stable' endpoint for segments
                print(f"DEBUG: Fetching Segments for {symbol}")
                prod_seg_raw = get_fmp_data('revenue-product-segmentation', 'annual', 1, version='stable')
                geo_seg_raw = get_fmp_data('revenue-geographic-segmentation', 'annual', 1, version='stable')
                
                print(f"DEBUG: Prod Seg Raw: {prod_seg_raw}")
                print(f"DEBUG: Geo Seg Raw: {geo_seg_raw}")
                
                # Extract and prepare segment data
                # FMP returns: [{'date': '2024-01-28', 'symbol': 'NVDA', 'data': {'Compute': 113000, ...}}]
                product_segments = {}
                geo_segments = {}
                
                if prod_seg_raw and len(prod_seg_raw) > 0:
                    prod_entry = prod_seg_raw[0]
                    # Check if 'data' field exists (nested structure)
                    if 'data' in prod_entry and isinstance(prod_entry['data'], dict):
                        product_segments = prod_entry  # Keep full object with date
                    elif isinstance(prod_entry, dict):
                        # Sometimes data is directly in the object
                        # Filter out metadata fields
                        data_only = {k: v for k, v in prod_entry.items() if k not in ['date', 'symbol', 'cik', 'period']}
                        if data_only:
                            product_segments = {
                                'date': prod_entry.get('date', 'N/A'),
                                'symbol': prod_entry.get('symbol', symbol),
                                'data': data_only
                            }
                
                if geo_seg_raw and len(geo_seg_raw) > 0:
                    geo_entry = geo_seg_raw[0]
                    if 'data' in geo_entry and isinstance(geo_entry['data'], dict):
                        geo_segments = geo_entry
                    elif isinstance(geo_entry, dict):
                        data_only = {k: v for k, v in geo_entry.items() if k not in ['date', 'symbol', 'cik', 'period']}
                        if data_only:
                            geo_segments = {
                                'date': geo_entry.get('date', 'N/A'),
                                'symbol': geo_entry.get('symbol', symbol),
                                'data': data_only
                            }
                
                financial_stmts['segments'] = {
                    'product': product_segments,
                    'geo': geo_segments
                }
                
                print(f"DEBUG: Final Prod Seg: {product_segments}")
                print(f"DEBUG: Final Geo Seg: {geo_segments}")
                
            except Exception as e:
                print(f"Segmentation Fetch Error: {e}")
                import traceback
                traceback.print_exc()
                financial_stmts['segments'] = {'product': {}, 'geo': {}}
                
    except Exception as e:
        print(f"Financials Fetch Error: {e}")

    context = {
        'symbol': symbol,
        'profile': profile_data,
        'fundamentals': fundamentals,
        'news_list': news_list,
        'financial_stmts': financial_stmts, # Passed to template
        'periods': ['annual', 'quarter'] # Added for template loops
    }
    
    return render(request, 'search/profile.html', context)
