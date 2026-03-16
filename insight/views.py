# insight/views.py

import json
from pathlib import Path
import pandas as pd
import yfinance as yf # New import
import numpy as np
from django.shortcuts import render,HttpResponse
from django.db import transaction
from django.db.models import Subquery, OuterRef # New imports
from updatedata.models import Ticker, FundamentalData, PriceHistory # New imports
from .models import MarketCapSnapshot
import requests
from dotenv import load_dotenv
import os
from .documents import GuruPortfolioDoc, Holding
import datetime
import time
import re
import xml.etree.ElementTree as ET
from django.utils import timezone
from datetime import datetime, timedelta
from piboufilings import get_filings
import piboufilings

load_dotenv()
# -----------------------------
# Universe 메타 정보
# -----------------------------
UNIVERSES = {
    "sp500": { "label": "S&P 500", "csv": None },
    "nasdaq100": { "label": "Nasdaq 100", "csv": None },
    "russell2000": { "label": "Russell 2000", "csv": None },
    "global": { "label": "Global Market TOP (Combined)", "csv": None },
}

UNIVERSE_CHOICES = [(k, v["label"]) for k, v in UNIVERSES.items()]
VIEW_CHOICES = [
    ("constellation", "Market Constellation"),
    ("sector", "Sector Heatmap"),
    ("factor", "Factor Grid"),
    ("risk", "Risk Radar"),
    ("flow", "Flow Orbit"),
]

# -----------------------------
# 유틸: 스냅샷 로딩 (핵심 수정 부분)
# -----------------------------
def load_snapshot(universe_key: str) -> pd.DataFrame:
    print(f"DEBUG: Loading snapshot for {universe_key}...")
    
    # 1. Fetch Tickers
    if universe_key == "global":
        qs = Ticker.objects.all()
    else:
        qs = Ticker.objects.filter(market__contains=universe_key)
        if not qs.exists():
            qs = Ticker.objects.all()
            
    # Convert Tickers to DataFrame
    # Note: We include 'id' to map ForeignKeys if needed, but 'symbol' is our join key here effectively if used consistently
    # Actually models use ForeignKey to Ticker.id. 
    # Let's fetch basic info.
    tickers_data = list(qs.values('id', 'symbol', 'name', 'sector'))
    if not tickers_data:
        return pd.DataFrame(columns=["symbol", "name", "sector", "market_cap", "change_pct"])
        
    df = pd.DataFrame(tickers_data)
    
    # 2. Fetch Latest Prices (Strategy: Fetch recent history and dedup in Pandas)
    # Using 'symbol_id' for joining is safer against ticker changes
    ticker_ids = df['id'].tolist()
    
    # Fetch price history for these tickers
    # Optimization: Filter only recent dates? Or just fetch latest by using a smart query?
    # Simple & Robust: Fetch all recent prices (e.g. last 5 days) and drop duplicates.
    # But for "latest available", we might just sort-desc by date on the whole set?
    # Querying all PriceHistory might be huge.
    # Let's use the Subquery approach JUST for filtering IDs if we have millions of rows.
    # Assuming user has manageable data (<1M rows).
    # "distinct" on fields is PostgreSQL specific. If SQLite, it fails.
    # Let's try standard Django "latest" logic via annotations? No, that was the previous failure.
    
    # NEW STRATEGY: Fetch all prices for these tickers, sort by date in DB, then Pandas dedup.
    # Use 'symbol__in'
    price_qs = PriceHistory.objects.filter(symbol_id__in=ticker_ids).order_by('-date')
    # Limit fields
    price_data = list(price_qs.values('symbol_id', 'change_percent', 'date'))
    
    if price_data:
        prices_df = pd.DataFrame(price_data)
        # Sort by date desc (already done by DB but good to ensure) -> Drop duplicates keeping first (latest)
        latest_prices = prices_df.drop_duplicates(subset=['symbol_id'], keep='first')
        
        # Merge Prices [Left Join]
        df = df.merge(latest_prices[['symbol_id', 'change_percent']], left_on='id', right_on='symbol_id', how='left')
    else:
        df['change_percent'] = 0.0

    # 3. Fetch Latest Fundamentals
    fund_qs = FundamentalData.objects.filter(symbol_id__in=ticker_ids).order_by('-date')
    fund_data = list(fund_qs.values('symbol_id', 'market_cap'))
    
    if fund_data:
        fund_df = pd.DataFrame(fund_data)
        latest_fund = fund_df.drop_duplicates(subset=['symbol_id'], keep='first')
        
        # Merge Fundamentals [Left Join]
        df = df.merge(latest_fund[['symbol_id', 'market_cap']], left_on='id', right_on='symbol_id', how='left')
    else:
        df['market_cap'] = 0.0

    # Rename and Cleanup
    df = df.rename(columns={"change_percent": "change_pct"})
    
    # Fill NaNs
    df["market_cap"] = df["market_cap"].fillna(0)
    df["change_pct"] = df["change_pct"].fillna(0.0)
    df["sector"] = df["sector"].fillna("Unknown").replace("", "Unknown")
    
    # Verify Data
    non_zeros = df[df['change_pct'] != 0].shape[0]
    print(f"DEBUG: Snapshot loaded. Rows: {len(df)}, Non-Zero Changes: {non_zeros}")
    if non_zeros > 0:
        print(f"DEBUG Sample: {df[['symbol', 'change_pct']].head(1).to_dict('records')}")
    
    # Sort
    df = df.sort_values(by="market_cap", ascending=False)
    
    return df


# -----------------------------
# Top 20 View (순수 파이썬 버전)
# -----------------------------
def market_cap_top20(request):
    
    universe_key = "sp500" 
    universe_label = "Market Leaders (Top 20)"

    # 1. DB 쿼리 (Global Search to ensure data visibility)
    # The 'sp500' tag is often missing in import, so we fallback to ALL tickers
    qs = Ticker.objects.all()
    
    # Annotate latest market_cap and change_percent
    latest_fund = FundamentalData.objects.filter(symbol=OuterRef('pk')).order_by('-date')
    latest_price = PriceHistory.objects.filter(symbol=OuterRef('pk')).order_by('-date')
    
    qs = qs.annotate(
        market_cap=Subquery(latest_fund.values('market_cap')[:1]),
        change_percent=Subquery(latest_price.values('change_percent')[:1])
    )

    # 2. Database Sort & Limit (Efficient)
    from django.db.models import F
    
    # Sort by market_cap descending at DB level
    # Use F() expression to handle sorting, nulls_last ensures None values go to bottom
    qs = qs.annotate(
        market_cap=Subquery(latest_fund.values('market_cap')[:1]),
        change_percent=Subquery(latest_price.values('change_percent')[:1])
    ).order_by(F('market_cap').desc(nulls_last=True))[:20]

    # 3. Retrieve only Top 20
    raw_data = list(qs.values(
        "symbol", "name", "sector", "market_cap", "change_percent"
    ))

    processed_rows = []
    for row in raw_data:
        mcap = row["market_cap"]
        if mcap is None: mcap = 0.0
        else: mcap = float(mcap)
        
        processed_rows.append({
            "symbol": row["symbol"],
            "name": row["name"],
            "sector": row["sector"] if row["sector"] else "Unknown",
            "market_cap": mcap, # 정렬을 위해 원본 숫자 유지
            "change_pct": row["change_percent"] if row["change_percent"] else 0.0
        })

    # Already sorted by DB, no need to sort in Python
    top20_rows = processed_rows
    for row in top20_rows:
        val = row["market_cap"]
        if val >= 1e12:   # 1조 이상 -> T (Trillion)
            row["market_cap_display"] = f"$ {val/1e12:.2f} T"
        elif val >= 1e9: # 10억 이상 -> B (Billion)
            row["market_cap_display"] = f"$ {val/1e9:.2f} B"
        elif val >= 1e6: # 100만 이상 -> M (Million)
            row["market_cap_display"] = f"$ {val/1e6:.2f} M"
        else:
            row["market_cap_display"] = f"$ {val:,.0f}"

    labels = [r["symbol"] for r in top20_rows]
    values = [r["market_cap"] for r in top20_rows]

    # 4. Rank Change Logic (Dedicated Daily History)
    # ---------------------------------------------
    # We store a full history of rankings in 'top_symbols_json' (acting as a dedicated history table).
    # Format: {"2024-05-20": ["AAPL", ...], "2024-05-21": ["MSFT", ...]}
    
    current_symbols_list = labels 
    today_str = timezone.now().date().strftime("%Y-%m-%d")
    
    with transaction.atomic():
        snapshot_obj, created = MarketCapSnapshot.objects.get_or_create(
            universe_key=universe_key,
            defaults={"top_symbols_json": {}}
        )
        
        # Load History
        history = snapshot_obj.top_symbols_json
        
        # Handle Migration (If string/list/old-dict schema exists)
        if isinstance(history, list):
            # Old schema: just a list. Reset to empty dict or save as yesterday?
            # Safer to reset to avoid confusion, or map to 'unknown_date'.
            history = {}
        elif isinstance(history, dict) and "current" in history:
            # Previous schema: {"current": [], "previous": []}
            # Migrate 'previous' to yesterday (approx) and 'current' to today?
            # Just reset for safety to ensure clean Daily schema.
            history = {}

        # Save Today's Ranking
        history[today_str] = current_symbols_list
        snapshot_obj.top_symbols_json = history
        snapshot_obj.save()
        
        # Find Comparison Date (Yesterday or Last Available)
        sorted_dates = sorted([d for d in history.keys() if d < today_str], reverse=True)
        previous_list = []
        
        if sorted_dates:
            target_date = sorted_dates[0] # The most recent past date
            previous_list = history[target_date]
            # print(f"Comparing against {target_date} data")
            
        previous_rank_map = {sym: i+1 for i, sym in enumerate(previous_list)}

    for i, row in enumerate(top20_rows):
        current_rank = i + 1
        symbol = row["symbol"]
        
        if symbol in previous_rank_map:
            prev_rank = previous_rank_map[symbol]
            # Rank Change: Positive = Improved Rank (e.g. prev 5 -> curr 3 = 5-3 = +2)
            change = prev_rank - current_rank
            row["rank_change"] = change
            row["is_new"] = False
        else:
            # If historical data exists but symbol is not in it -> New Entry
            # If NO historical data exists (first run), we don't show "New".
            if previous_list:
                row["rank_change"] = 0
                row["is_new"] = True
            else:
                row["rank_change"] = 0
                row["is_new"] = False
        
    context = {
        "universe_label": universe_label,
        "labels": json.dumps(labels),
        "values": json.dumps(values),
        "top20_rows": top20_rows,
    }
    return render(request, "insight/top20.html", context)


# -----------------------------
# 기존 Dashboard 및 Chart 함수들 (유지)
# -----------------------------
def build_constellation_payload(df: pd.DataFrame):
    if df.empty: return []
    sectors = sorted(df["sector"].unique())
    sector_index = {s: i for i, s in enumerate(sectors)}

    mcap = df["market_cap"]
    mcap_min = mcap.min()
    mcap_max = mcap.max()
    if mcap_max == mcap_min: mcap_max = mcap_min + 1

    def radius_from_mcap(v):
        # 시가총액 차이가 너무 크면(조 vs 억) 로그 스케일 등을 고려해야 하지만
        # 일단 선형으로 유지하되 최소 크기 보장
        return 6 + 24 * ((v - mcap_min) / (mcap_max - mcap_min))

    points = []
    for _, row in df.iterrows():
        s_idx = sector_index.get(row["sector"], 0)
        x = s_idx + 0.1 
        y = row["change_pct"]
        r = radius_from_mcap(row["market_cap"])

        points.append({
            "x": round(x, 3),
            "y": round(y, 3),
            "r": round(r, 2),
            "symbol": row["symbol"],
            "name": row["name"],
            "sector": row["sector"],
            "market_cap": float(row["market_cap"]),
            "change_pct": float(row["change_pct"]),
        })
    return points

def build_sector_stats(df: pd.DataFrame):
    if df.empty:
        return pd.DataFrame(columns=["sector", "total_mcap", "cap_wgt_chg", "avg_abs_chg", "net_flow"])

    # [Custom Themes] Override Sector for specific themes (Same as Vestiq Picks)
    QUANTUM_THEME = ['IONQ', 'RGTI', 'QBTS', 'QUBT', 'IBM', 'GOOGL']
    AEROSPACE_THEME = ['LMT', 'RTX', 'NOC', 'GD', 'BA', 'HII', 'LHX', 'PLTR', 'AXON', 'KTOS', 'AVAV', 'RKLB']
    
    # Override sectors in the dataframe (using .loc to avoid SettingWithCopyWarning if it's a view)
    df.loc[df['symbol'].isin(QUANTUM_THEME), 'sector'] = 'Quantum'
    df.loc[df['symbol'].isin(AEROSPACE_THEME), 'sector'] = 'Aerospace & Defense'

    g = df.groupby("sector").apply(lambda x: pd.Series({
        "total_mcap": x["market_cap"].sum(),
        "cap_wgt_chg": (x["market_cap"] * x["change_pct"]).sum() / x["market_cap"].sum() if x["market_cap"].sum() > 0 else 0,
        "avg_abs_chg": x["change_pct"].abs().mean(),
        "adv_mcap": x.loc[x["change_pct"] > 0, "market_cap"].sum(),
        "dec_mcap": x.loc[x["change_pct"] < 0, "market_cap"].sum(),
    })).reset_index()
    g["net_flow"] = g["adv_mcap"] - g["dec_mcap"]
    return g

def build_factor_grid(df: pd.DataFrame):
    if df.empty: return []
    median_mcap = df["market_cap"].median()
    
    tmp = df.copy()
    tmp["size_bucket"] = tmp["market_cap"].apply(lambda v: "Large" if v >= median_mcap else "Small")
    tmp["dir_bucket"] = tmp["change_pct"].apply(lambda v: "Up" if v >= 0 else "Down")
    
    g = tmp.groupby(["size_bucket", "dir_bucket"]).agg(
        count=("symbol", "size"),
        avg_chg=("change_pct", "mean"),
    ).reset_index()

    coord = {("Small", "Down"): (-1, -1), ("Small", "Up"): (-1, 1), ("Large", "Down"): (1, -1), ("Large", "Up"): (1, 1)}
    payload = []
    for _, row in g.iterrows():
        key = (row["size_bucket"], row["dir_bucket"])
        x, y = coord.get(key, (0,0))
        r = 8 + 4 * (row["count"] ** 0.5)
        payload.append({
            "label": f"{row['size_bucket']} · {row['dir_bucket']}",
            "x": x, "y": y, "r": r,
            "count": int(row["count"]), "avg_chg": float(row["avg_chg"]),
        })
    return payload

def build_risk_radar_payload(sector_stats: pd.DataFrame):
    if sector_stats.empty: return {"labels": [], "risk": []}
    return {"labels": sector_stats["sector"].tolist(), "risk": sector_stats["avg_abs_chg"].round(2).tolist()}

def build_flow_orbit_payload(sector_stats: pd.DataFrame):
    if sector_stats.empty: return {"labels": [], "flow": []}
    return {"labels": sector_stats["sector"].tolist(), "flow": sector_stats["net_flow"].tolist()} # float 그대로 전달

def dashboard(request):
    universe_key = request.GET.get("u", "sp500")
    if universe_key not in UNIVERSES: universe_key = "sp500"

    # view_mode is kept for backward compatibility or future toggles, but 
    # we default to "constellation" or just ignore it in the new layout if needed.
    view_mode = request.GET.get("v", "constellation")
    
    df = load_snapshot(universe_key)
    universe_label = UNIVERSES[universe_key]["label"]

    # --- 1. Top Movers Calculation (In-Memory) ---
    top_gainers = []
    top_losers = []
    market_leaders = []

    if not df.empty:
        # Top Gainers (Top 5)
        # Filter out 0% change if desired, or keep them.
        gainers_df = df.sort_values(by="change_pct", ascending=False).head(5)
        top_gainers = gainers_df.to_dict(orient="records")

        # Top Losers (Bottom 5)
        losers_df = df.sort_values(by="change_pct", ascending=True).head(5)
        top_losers = losers_df.to_dict(orient="records")

        # Market Leaders (Top 5 by Market Cap)
        # Fetch Top 10 candidates to handle exclusions (e.g. Dual class shares)
        leaders_df_candidates = df.sort_values(by="market_cap", ascending=False).head(10)
        candidates = leaders_df_candidates.to_dict(orient="records")
        
        market_leaders = []
        for c in candidates:
            # User Request: Show only Google A (GOOGL), hide Google C (GOOG)
            if c['symbol'] == 'GOOG':
                continue
            
            market_leaders.append(c)
            if len(market_leaders) >= 5:
                break

    # --- 2. Existing Visualizations ---
    constellation_data = build_constellation_payload(df)
    sector_stats = build_sector_stats(df)
    factor_grid = build_factor_grid(df)
    risk_radar = build_risk_radar_payload(sector_stats)
    flow_orbit = build_flow_orbit_payload(sector_stats)

    context = {
        "universe_key": universe_key,
        "universe_label": universe_label,
        "universe_choices": UNIVERSE_CHOICES,
        "view_mode": view_mode,
        "view_choices": VIEW_CHOICES,
        "snapshot_count": len(df),
        
        # New Data for Dashboard
        "top_gainers": top_gainers,
        "top_losers": top_losers,
        "market_leaders": market_leaders,

        # Chart JSONs
        "constellation_json": json.dumps(constellation_data),
        "sector_stats_json": json.dumps(sector_stats.to_dict(orient="records") if not sector_stats.empty else []),
        "factor_grid_json": json.dumps(factor_grid),
        "risk_radar_json": json.dumps(risk_radar),
        "flow_orbit_json": json.dumps(flow_orbit),
    }
    return render(request, "insight/index.html", context)


# --- 1. Helper Functions (API 호출) ---
def _fetch_apewisdom():
    url = "https://apewisdom.io/api/v1.0/filter/all-stocks/page/1/"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        res = requests.get(url, headers=headers, timeout=5)
        data = res.json()
        return data.get("results", []) if res.status_code == 200 else []
    except: return []

# --- 3. Insider Trading Radar ---
def _scrape_openinsider(url):
    """Helper to scrape and clean OpenInsider data"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
        resp = requests.get(url, headers=headers, timeout=10)
        dfs = pd.read_html(resp.text)
        
        df = None
        for d in dfs:
            cols = [str(c).replace('\xa0', ' ') for c in d.columns]
            if "Ticker" in cols and "Value" in cols:
                d.columns = cols
                df = d
                break
        
        if df is None: return []

        data = []
        for _, row in df.iterrows():
            # Value
            val_str = str(row.get("Value", "0")).replace('$','').replace(',','')
            try: val = float(val_str)
            except: val = 0
            
            # Price
            price_str = str(row.get("Price", "0")).replace('$','').replace(',','')
            try: price_val = float(price_str)
            except: price_val = 0.0
            
            # Date
            f_date = str(row.get("Filing Date", ""))
            if " " in f_date: f_date = f_date.split(" ")[0]

            # Title
            raw_title = row.get("Title")
            title_display = "-" if (pd.isna(raw_title) or str(raw_title).lower() == "nan" or raw_title == "") else str(raw_title)

            # Qty
            qty_str = str(row.get("Qty", "0")).replace(',', '').replace('+', '').replace('-', '')
            try: qty_val = float(qty_str)
            except: qty_val = 0
                
            # Owned
            owned_str = str(row.get("Owned", "0")).replace(',', '')
            try: owned_val = float(owned_str)
            except: owned_val = 0
            
            # Delta Own
            delta = row.get("ΔOwn", "")
            if pd.isna(delta) or delta == "": delta = "0%"
            
            # Delta Own Value for Sorting
            try:
                delta_clean = str(delta).replace('%','').replace('+','').replace('>','').replace('<','').replace(',','')
                delta_val = float(delta_clean)
            except:
                delta_val = 0.0

            data.append({
                "ticker": row.get("Ticker"),
                "company": row.get("Company Name"),
                "insider": row.get("Insider Name"),
                "title": title_display,
                "price": price_val,
                "qty": qty_val,
                "owned": owned_val,
                "delta_own": delta,
                "delta_own_val": delta_val,
                "value": val,
                "date": f_date,
                "trade_type": row.get("Trade Type"),
            })
        return data
    except Exception as e:
        print(f"Scraping Error: {e}")
        return []

def insider_analysis(request):
    """
    Insider Trading Radar
    Fetches Top 50 Buys and Top 50 Sells separately for last 30 days.
    """
    # 1. Top 50 Buys (xp=1, xs=0)
    url_buy = "http://openinsider.com/screener?s=&o=&pl=&ph=&ll=&lh=&fd=30&fdr=&td=0&tdr=&fdlyl=&fdlyh=&daysago=&xp=1&xs=0&vl=&vh=&ocl=&och=&sic1=-1&sicl=100&sich=9999&grp=0&nfl=&nfh=&nil=&nih=&nol=&noh=&v2l=&v2h=&oc2l=&oc2h=&sortcol=8&sortasc=0&cnt=50&page=1"
    
    # 2. Top 50 Sells (xp=0, xs=1)
    url_sell = "http://openinsider.com/screener?s=&o=&pl=&ph=&ll=&lh=&fd=30&fdr=&td=0&tdr=&fdlyl=&fdlyh=&daysago=&xp=0&xs=1&vl=&vh=&ocl=&och=&sic1=-1&sicl=100&sich=9999&grp=0&nfl=&nfh=&nil=&nih=&nol=&noh=&v2l=&v2h=&oc2l=&oc2h=&sortcol=8&sortasc=0&cnt=50&page=1"
    
    context = {}
    
    buys = _scrape_openinsider(url_buy)
    sells = _scrape_openinsider(url_sell)
    
    # Ensure sorted by Date desc (Newest first), then by Value desc
    buys.sort(key=lambda x: (x['date'], x['value']), reverse=True)
    sells.sort(key=lambda x: (x['date'], x['value']), reverse=True)
    
    total_buy_vol = sum(d['value'] for d in buys)
    total_sell_vol = sum(d['value'] for d in sells)
    
    # Combined for Charts (Top Movers) -> SPLIT into Buys and Sells separately
    
    # Sort by Value for Charts (Highest Value First)
    chart_buys = sorted(buys, key=lambda x: x['value'], reverse=True)[:5]
    chart_sells = sorted(sells, key=lambda x: x['value'], reverse=True)[:5]

    # --- Daily Trend Data Aggregation ---
    daily_stats = {}
    
    # Process Buys
    for b in buys:
        d = b['date']
        if d not in daily_stats: daily_stats[d] = {'buy': 0, 'sell': 0}
        daily_stats[d]['buy'] += b['value']
        
    # Process Sells
    for s in sells:
        d = s['date']
        if d not in daily_stats: daily_stats[d] = {'buy': 0, 'sell': 0}
        daily_stats[d]['sell'] += s['value']
        
    # Sort by Date (Oldest to Newest for Chart)
    sorted_dates = sorted(daily_stats.keys())
    
    trend_dates = sorted_dates
    trend_buy_vals = [daily_stats[d]['buy'] for d in sorted_dates]
    trend_sell_vals = [daily_stats[d]['sell'] for d in sorted_dates]

    context["buys"] = buys
    context["sells"] = sells
    
    context["total_buy_vol"] = total_buy_vol
    context["total_sell_vol"] = total_sell_vol
    context["buy_count"] = len(buys)
    context["sell_count"] = len(sells)
    
    # Top 5 Buys Data
    context["top_buy_tickers"] = json.dumps([x['ticker'] for x in chart_buys])
    context["top_buy_values"] = json.dumps([x['value'] for x in chart_buys])
    
    # Top 5 Sells Data
    context["top_sell_tickers"] = json.dumps([x['ticker'] for x in chart_sells])
    context["top_sell_values"] = json.dumps([x['value'] for x in chart_sells])
    
    # Daily Trend Data
    context["trend_dates"] = json.dumps(trend_dates)
    context["trend_buy_vals"] = json.dumps(trend_buy_vals)
    context["trend_sell_vals"] = json.dumps(trend_sell_vals)
    
    context["last_updated"] = datetime.now()
        
    return render(request, "insight/insider.html", context)


# --- 4. Seasonality Explorer ---
def seasonality_analysis(request):
    """
    Seasonality Explorer
    Analyzes monthly returns over the last 20 years.
    """
    ticker = request.GET.get('ticker', 'SPY').upper()
    context = {'ticker': ticker}
    
    if ticker:
        try:
            # Fetch 20 years of history
            df = yf.download(ticker, period="20y", interval="1mo", progress=False)
            
            if df.empty:
                context['error'] = f"No data found for {ticker}"
            else:
                # Calculate monthly returns
                # 'Close' might be MultiIndex if yfinance updated, handle it
                if isinstance(df.columns, pd.MultiIndex):
                    df = df['Close']
                else:
                    df = df['Close'] if 'Close' in df else df
                
                # Ensure we have a Series
                if isinstance(df, pd.DataFrame):
                    df = df.iloc[:, 0]
                    
                # Calculate % change
                returns = df.pct_change().dropna()
                
                # Group by Month
                # returns.index.month gives 1=Jan, 12=Dec
                monthly_stats = []
                from django.utils.translation import gettext as _
                import calendar
                
                # Use calendar.month_abbr for localized month names if locale is set, 
                # but better to use _() on English strings to let Django PO files handle it.
                # simpler: just list them with _()
                month_names = [
                    _("Jan"), _("Feb"), _("Mar"), _("Apr"), _("May"), _("Jun"),
                    _("Jul"), _("Aug"), _("Sep"), _("Oct"), _("Nov"), _("Dec")
                ]
                
                for m in range(1, 13):
                    m_data = returns[returns.index.month == m]
                    if m_data.empty:
                        monthly_stats.append({
                            'month': month_names[m-1],
                            'avg': 0,
                            'win_rate': 0,
                            'count': 0
                        })
                        continue
                        
                    avg_ret = m_data.mean() * 100
                    win_count = len(m_data[m_data > 0])
                    total_count = len(m_data)
                    win_rate = (win_count / total_count) * 100 if total_count > 0 else 0
                    
                    monthly_stats.append({
                        'month': month_names[m-1],
                        'avg': round(avg_ret, 2),
                        'win_rate': round(win_rate, 1),
                        'count': total_count
                    })
                
                context['monthly_stats'] = monthly_stats
                context['monthly_labels'] = json.dumps([x['month'] for x in monthly_stats])
                context['monthly_values'] = json.dumps([x['avg'] for x in monthly_stats])
                context['win_rates'] = json.dumps([x['win_rate'] for x in monthly_stats])
                
                # Best/Worst
                sorted_stats = sorted(monthly_stats, key=lambda x: x['avg'], reverse=True)
                context['best_month'] = sorted_stats[0]
                context['worst_month'] = sorted_stats[-1]

        except Exception as e:
            print(f"Seasonality Error: {e}")
            context['error'] = f"Error analyzing {ticker}: {str(e)}"
            
    return render(request, "insight/seasonality.html", context)


# --- 2. Main View ---
def wsb_analysis(request):
    """
    WSB Sentiment Analysis Dashboard
    - ApeWisdom Data Only (No Sentiment, No Integrated Tab)
    """
    
    # 1. Raw Data Fetching (Only ApeWisdom)
    aw_raw = _fetch_apewisdom()
    
    # --- Data Processing ---
    final_list = []
    
    for item in aw_raw:
        t = item.get('ticker')
        if not t: continue
        
        mentions = item.get('mentions', 0)
        upvotes = item.get('upvotes', 0)
        
        # List Row
        final_list.append({
            'ticker': t,
            'mentions': mentions,
            'upvotes': upvotes,
            'rank': item.get('rank', 0)
        })
            
    # Sort & Rank (Ensure 1..N)
    final_list.sort(key=lambda x: x['mentions'], reverse=True)
    for i, item in enumerate(final_list):
        item['rank'] = i + 1

    # --- ApeWisdom Chart Data ---
    aw_list = final_list 
    
    context = {
        # ApeWisdom List & Charts
        "aw_list": aw_list,
        "aw_labels": json.dumps([x['ticker'] for x in aw_list[:10]]),
        "aw_mentions": json.dumps([x['mentions'] for x in aw_list[:10]]),
        "aw_upvotes": json.dumps([x['upvotes'] for x in aw_list[:10]]),
    }
    
    return render(request, "insight/wsb.html", context)


# --- 5. Market 101 (Macro & Education) ---
# --- 6. Market 101 (Macro & Education) ---
def market_101_view(request):
    """
    Market 101 Dashboard (Redesigned)
    - Section 1: Daily Market Pulse (Yahoo Finance) - VIX, Oil, Yields, DXY
    - Section 2: Economic Health (FRED) - CPI, Unemployment, GDP, Yield Curve
    - Added: Market Breadth (Sector Heat), Cross-Asset Correlation, AI Insights
    """
    import requests
    import json
    import pandas as pd
    import numpy as np
    from django.conf import settings
    from django.utils.translation import gettext as _

    # --- Helper: Fetch FRED History ---
    def get_fred_series(series_id, api_key=None, limit=24):
        """
        Fetches historical observations for a FRED series.
        Returns: { 'dates': [], 'values': [], 'last_value': float, 'last_date': str }
        """
        key = getattr(settings, 'FRED_API_KEY', None) or os.getenv('FRED_API_KEY')
        if not key:
             return None

        # Sort desc to get latest first, but we want chronological for charts
        # FRED API: sort_order=desc gets newest first. limit=24 gets last 24 points.
        url = f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}&api_key={key}&file_type=json&limit={limit}&sort_order=desc"
        
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                data = r.json()
                obs = data.get('observations', [])
                if obs:
                    # Reverse to be Chronological (Oldest -> Newest) for Charts
                    obs_rev = obs[::-1]
                    dates = []
                    values = []
                    
                    for o in obs_rev:
                        try:
                            val = float(o['value'])
                            dates.append(o['date'])
                            values.append(val)
                        except (ValueError, TypeError):
                            continue
                    
                    last_val = values[-1] if values else 0.0
                    last_date = dates[-1] if dates else ""
                    
                    return {
                        'dates': dates,
                        'values': values,
                        'last_value': last_val,
                        'last_date': last_date
                    }
        except Exception as e:
            print(f"FRED Series Error ({series_id}): {e}")
        return None

    # --- Helper: KPI & Trend ---
    def calculate_kpi(data):
        if not data or not data['values']:
             return {'current': '-', 'prev': '-', 'change': 0, 'trend': 'neutral'}
        
        curr = data['values'][-1]
        prev = data['values'][-2] if len(data['values']) > 1 else curr
        
        change = curr - prev
        pct_change = (change / prev * 100) if prev != 0 else 0
        
        # Trend based on last 3 periods
        trend = 'neutral'
        if len(data['values']) >= 3:
            ma3 = sum(data['values'][-3:]) / 3
            if curr > ma3 * 1.01: trend = 'up'
            elif curr < ma3 * 0.99: trend = 'down'
            
        return {
            'current': curr,
            'prev': prev,
            'change': change,
            'pct_change': pct_change,
            'trend': trend
        }

    # --- 1. Daily Market Pulse (Yahoo) ---
    pulse_subjects = [
        {'id': 'vix', 'symbol': '^VIX', 'name': 'VIX (Fear Index)'},
        {'id': 'oil', 'symbol': 'CL=F', 'name': 'Crude Oil (WTI)'},
        {'id': 'yield10', 'symbol': '^TNX', 'name': '10Y Treasury Yield'},
        {'id': 'dxy', 'symbol': 'DX-Y.NYB', 'name': 'US Dollar Index'},
    ]
    
    symbols = [s['symbol'] for s in pulse_subjects]
    context = {'pulse_data': [], 'charts': {}}

    # Pulse Data
    try:
        df = yf.download(symbols, period="5d", interval="1d", progress=False)['Close']
        if not df.empty:
            for subj in pulse_subjects:
                sym = subj['symbol']
                if sym in df:
                    s = df[sym].dropna()
                    if not s.empty:
                        val = float(s.iloc[-1])
                        prev = float(s.iloc[-2]) if len(s) > 1 else val
                        change = ((val - prev) / prev) * 100
                        
                        subj['value'] = f"{val:.2f}"
                        subj['change'] = f"{change:+.2f}%"
                        subj['change_val'] = change
                        subj['is_up'] = change > 0
                        context['pulse_data'].append(subj)
    except Exception as e:
        print(f"Pulse Error: {e}")

    # --- 2. Market Breadth & Correlation (Yahoo) ---
    sector_etfs = ['XLK', 'XLF', 'XLV', 'XLY', 'XLP', 'XLE', 'XLI', 'XLB', 'XLRE', 'XLU', 'XLC']
    major_assets = {'SPY': 'S&P 500', 'TLT': 'Bonds (20Y)', 'GLD': 'Gold', 'USO': 'Oil', 'UUP': 'US Dollar'}
    
    breadth_score = 50 # Default Neutral
    correlations = []
    
    try:
        # Fetch Sector Data for Breadth
        sec_df = yf.download(sector_etfs, period="2d", interval="1d", progress=False)['Close']
        if not sec_df.empty and len(sec_df) >= 2:
            advancers = 0
            for col in sec_df.columns:
                if sec_df[col].iloc[-1] > sec_df[col].iloc[-2]:
                    advancers += 1
            breadth_score = (advancers / len(sector_etfs)) * 100
        
        # Fetch Asset Data for Correlation (30 Days)
        asset_df = yf.download(list(major_assets.keys()), period="1mo", interval="1d", progress=False)['Close']
        if not asset_df.empty:
            # Calculate correlation matrix
            corr_matrix = asset_df.pct_change().corr()
            # Extract correlation with SPY
            if 'SPY' in corr_matrix:
                spy_corr = corr_matrix['SPY']
                for tick, name in major_assets.items():
                    if tick == 'SPY': continue
                    if tick in spy_corr:
                        correlations.append({
                            'name': name,
                            'ticker': tick,
                            'corr': round(spy_corr[tick], 2)
                        })
    except Exception as e:
        print(f"Breadth/Corr Error: {e}")

    context['breadth_score'] = round(breadth_score)
    context['correlations'] = correlations


    # --- 3. Comparative Charts Data (FRED) ---
    limit = 60 # 5 Years
    
    chart_configs = [
        {
            'key': 'fed_battle',
            'series_a': {'id': 'FEDFUNDS', 'name': _('Fed Funds Rate')}, 
            'series_b': {'id': 'T10YIE', 'name': _('Inflation Exp (10Y)')}, 
            'series_c': {'id': 'UNRATE', 'name': _('Unemployment Rate')},
            'explanation': {
                'importance': [
                    "연준(Fed)의 마음을 읽을 수 있는 가장 중요한 차트입니다.",
                    "금리가 인플레이션 기대보다 높아야 물가가 잡힙니다."
                ],
                'interpretation': [
                    "기준금리(하늘색)가 인플레이션 기대(회색)보다 위에 있다면, 연준이 돈줄을 조이고 있다는 뜻입니다.",
                    "반대로 금리가 기대 인플레이션보다 낮아지면, 시장에 돈이 풀리기 시작한다는 신호입니다.",
                    "실업률(빨간색)이 고개를 들기 시작하면 연준은 금리 인하를 심각하게 고민하게 됩니다."
                ]
            }
        },
        {
            'key': 'recession',
            'series_a': {'id': 'T10Y2Y', 'name': _('Yield Curve (10Y-2Y)')},
            'series_b': {'id': 'BAMLH0A0HYM2', 'name': _('Credit Spread')},
            'explanation': {
                'importance': [
                    "지난 수십 년간 경기 침체(Recession)를 가장 정확하게 맞춘 '족집게' 지표입니다.",
                    "은행이 돈을 빌려줄 때의 마진(장단기 금리차)을 보여줍니다."
                ],
                'interpretation': [
                    "장단기 금리차(주황색)가 0 밑으로 떨어지면(역전), 1년 뒤쯤 경제 위기가 올 확률이 매우 높습니다.",
                    "역전됐던 금리차가 다시 0 위로 급등할 때가 진짜 위험한 시기입니다 (실물 경기 충격 시작).",
                    "크레딧 스프레드(회색)가 갑자기 솟구친다면 기업들이 돈 구하기 힘들어졌다는 뜻으로, 주식 시장엔 악재입니다."
                ]
            }
        },
        {
            'key': 'liquidity',
            'series_a': {'id': 'UMCSENT', 'name': _('Consumer Sentiment')},
            'series_b': {'id': 'M2SL', 'name': _('M2 Money Supply ($T)')},
            'explanation': {
                'importance': [
                    "주가는 결국 '돈의 양(유동성)'과 '사람들의 심리'가 결정합니다.",
                    "시장에 돈이 얼마나 풀려있는지 보여줍니다."
                ],
                'interpretation': [
                    "통화량(회색) 그래프가 우상향하면 주식 시장에 연료가 공급되고 있는 것입니다.",
                    "소비자 심리(보라색)가 바닥을 찍고 올라오면 경제가 살아나고 있다는 긍정적 신호입니다.",
                    "돈은 풀리는데 심리가 나쁘다면? 물가만 오르는 '스태그플레이션'을 조심해야 합니다."
                ]
            }
        },
        {
            'key': 'housing',
            'series_a': {'id': 'MORTGAGE30US', 'name': _('30Y Mortgage Rate')},
            'series_b': {'id': 'HOUST', 'name': _('Housing Starts')},
            'explanation': {
                'importance': [
                    "부동산은 경제의 선행 지표입니다. 집을 짓기 시작하면 가구, 가전 등 소비가 따라옵니다.",
                    "금리에 가장 민감하게 반응하는 시장입니다."
                ],
                'interpretation': [
                    "모기지 금리(하늘색)가 오르면, 시차를 두고 주택 착공(회색)이 줄어드는 것이 정상입니다.",
                    "주택 착공이 바닥을 다지고 다시 늘어나기 시작하면 경기 회복의 첫 번째 신호로 봅니다.",
                    "금리가 높은데도 집을 계속 짓는다면? 공급이 너무 부족해서 가격이 안 떨어진다는 뜻입니다."
                ]
            }
        },
        {
            'key': 'inflation_deep',
            'series_a': {'id': 'CPIAUCSL', 'name': _('CPI Index')},
            'series_b': {'id': 'PPIACO', 'name': _('PPI (Producer Price)')},
            'explanation': {
                'importance': [
                    "내 월급 빼고 다 오르는 물가, 그 추세를 확인합니다.",
                    "기업이 만드는 가격(PPI)이 오르면 결국 소비자 가격(CPI)도 오릅니다."
                ],
                'interpretation': [
                    "생산자 물가(회색)가 먼저 꺾여야 소비자 물가(초록색)도 따라서 내려갑니다.",
                    "두 그래프가 계속 가파르게 오르면 현금을 들고 있으면 손해입니다.",
                    "기업 입장에선 PPI가 낮고 CPI가 높아야 마진이 많이 남습니다."
                ]
            }
        },
        {
            'key': 'labor_demand',
            'series_a': {'id': 'PAYEMS', 'name': _('Total Nonfarm Payrolls')},
            'series_b': {'id': 'UNEMPLOY', 'name': _('Total Unemployed')},
            'explanation': {
                'importance': [
                    "미국 경제의 70%는 소비, 그 소비를 만드는 건 '월급(고용)'입니다.",
                    "일자리가 튼튼하면 경제는 쉽게 무너지지 않습니다."
                ],
                'interpretation': [
                    "실업자 수(회색)가 바닥을 찍고 급격히 늘어나면 경기 침체 경보(샴의 법칙)가 켜진 것입니다.",
                    "일자리 수(보라색)가 계속 늘고 있다면 아직 경제가 튼튼하다는 증거입니다.",
                    "두 선이 서로 가까워지는지(일자리는 줄고 실업자는 느는지) 유심히 지켜봐야 합니다."
                ]
            }
        },
        {
            'key': 'consumer_health',
            'series_a': {'id': 'RSXFS', 'name': _('Retail Sales ($M)')},
            'series_b': {'id': 'PCE', 'name': _('Personal Spending ($B)')},
            'explanation': {
                'importance': [
                    "사람들이 지갑을 여는지 닫는지 보여주는 지표입니다.",
                    "미국 경제가 '연착륙' 할 수 있을지는 여기에 달려있습니다."
                ],
                'interpretation': [
                    "소매 판매(주황색)가 꺾이지 않고 버텨줘야 기업 실적도 유지됩니다.",
                    "지출은 늘어나는데 판매량이 준다면? 물가가 비싸서 억지로 돈을 더 쓰는 상황일 수 있습니다.",
                    "두 지표가 같이 꺾인다면 경기 침체가 코앞에 왔다는 뜻입니다."
                ]
            }
        },
        {
            'key': 'production',
            'series_a': {'id': 'INDPRO', 'name': _('Industrial Production')},
            'series_b': {'id': 'TCU', 'name': _('Capacity Utilization (%)')},
            'explanation': {
                'importance': [
                    "공장이 얼마나 바쁘게 돌아가는지 보여줍니다.",
                    "경기가 좋을 땐 공장이 쉴 새 없이 돌아갑니다."
                ],
                'interpretation': [
                    "산업 생산(초록색) 그래프가 꺾이면 경기 하강이 시작되었다는 신호입니다.",
                    "공장 가동률(회색)이 80%를 넘으면 '설비 투자'를 해야 하므로 관련 주식(기계, 장비)에 호재입니다.",
                    "가동률이 너무 낮으면 경기가 차갑게 식었다는 뜻입니다."
                ]
            }
        }, 
    ]
    
    # Store KPI data for AI analysis
    macro_kpis = {} 

    for cfg in chart_configs:
        data_a = get_fred_series(cfg['series_a']['id'], limit=limit)
        data_b = get_fred_series(cfg['series_b']['id'], limit=limit)
        data_c = get_fred_series(cfg['series_c']['id'], limit=limit) if 'series_c' in cfg else None
        
        chart_payload = {
            'dates': [], 
            'series_a_name': cfg['series_a']['name'],
            'series_a_data': [],
            'series_b_name': cfg['series_b']['name'],
            'series_b_data': [],
            'has_data': False,
            'kpi_a': {},
            'kpi_b': {},
            'explanation': cfg.get('explanation', {})
        }

        if data_a and data_b:
            chart_payload['dates'] = data_a['dates']
            chart_payload['series_a_data'] = data_a['values']
            chart_payload['series_b_data'] = data_b['values']
            
            # Calculate KPIs
            chart_payload['kpi_a'] = calculate_kpi(data_a)
            chart_payload['kpi_b'] = calculate_kpi(data_b)
            
            macro_kpis[cfg['series_a']['id']] = chart_payload['kpi_a']
            macro_kpis[cfg['series_b']['id']] = chart_payload['kpi_b']

            if data_c:
                chart_payload['series_c_name'] = cfg['series_c']['name']
                chart_payload['series_c_data'] = data_c['values']
                chart_payload['kpi_c'] = calculate_kpi(data_c)
                macro_kpis[cfg['series_c']['id']] = chart_payload['kpi_c']
                
            chart_payload['has_data'] = True
            
            if cfg['series_b']['id'] == 'M2SL':
                m2_vals = [round(v/1000, 2) for v in data_b['values']]
                chart_payload['series_b_data'] = m2_vals

        context['charts'][cfg['key']] = chart_payload

    # --- 4. Vestiq Macro Matrix Generation (Structured Analysis) ---
    macro_matrix = []

    # 1. Monetary Policy
    fed_kpi = macro_kpis.get('FEDFUNDS', {})
    if fed_kpi:
        # Simplistic Logic: If Rates > Inflation (T10YIE or CPI) + 1.5%, it's Restrictive
        # We don't have direct real rate here easily without comparing synced dates, 
        # so we use a heuristic or just the rate level.
        # Let's use the rate itself for simplicity or comparison with inflation expectation if available.
        # Note: FEDFUNDS is the rate. T10YIE is expectation.
        
        rate = fed_kpi.get('current', 0)
        status = "Neutral"
        signal = "NEUTRAL"
        summary = _("Rates at {rate:.1f}% are near neutral levels.").format(rate=rate)
        
        if rate > 4.5:
            status = "Restrictive"
            signal = "BEARISH"
            summary = _("Fed policy is tight ({rate}%), creating headwinds for risk assets.").format(rate=rate)
        elif rate < 2.5:
             status = "Accommodative"
             signal = "BULLISH"
             summary = _("Low interest rates ({rate}%) are supporting asset prices.").format(rate=rate)
        
        macro_matrix.append({
            'category': _('Monetary Policy'),
            'indicator': _('Fed Stance'),
            'status': status,
            'signal': signal,
            'summary': summary
        })

    # 2. Economic Health (Recession Risk)
    rec_kpi = macro_kpis.get('T10Y2Y', {}) # Yield Curve
    if rec_kpi:
        spread = rec_kpi.get('current', 0)
        if spread < -0.1:
            status = "Inverted"
            signal = "BEARISH"
            summary = _("Yield Curve is inverted ({val}%), signaling recession risk.").format(val=spread)
        elif spread < 0.2:
            status = "Flat"
            signal = "CAUTION"
            summary = _("Yield Curve is flat, indicating economic uncertainty.")
        else:
            status = "Normal"
            signal = "BULLISH"
            summary = _("Positive spread ({val}%) supports lending and normal growth.").format(val=spread)
            
        macro_matrix.append({
            'category': _('Economic Cycle'),
            'indicator': _('Recession Risk'),
            'status': status,
            'signal': signal,
            'summary': summary
        })

    # 3. Market Sentiment (Liquidity)
    m2_kpi = macro_kpis.get('M2SL', {})
    if m2_kpi:
        trend = m2_kpi.get('trend', 'neutral')
        if trend == 'up':
            status = "Expanding"
            signal = "BULLISH"
            summary = _("Global liquidity is increasing (M2 Rising), favorable for equities.")
        elif trend == 'down':
             status = "Contracting"
             signal = "BEARISH"
             summary = _("Liquidity is drying up (QT), removing support for markets.")
        else:
             status = "Stable"
             signal = "NEUTRAL"
             summary = _("Money supply is stable. Market relies on earnings growth.")
            
        macro_matrix.append({
            'category': _('Liquidity'),
            'indicator': _('Money Supply'),
            'status': status,
            'signal': signal,
            'summary': summary
        })

    # 4. Inflation Trend
    inf_kpi = macro_kpis.get('CPIAUCSL', {})
    if inf_kpi:
        trend = inf_kpi.get('trend', 'neutral')
        val = inf_kpi.get('current', 0)
        if trend == 'down' and val < 3.5:
            status = "Cooling"
            signal = "BULLISH"
            summary = _("Inflation is trending down ({val}%), allowing Fed flexibility.").format(val=val)
        elif trend == 'up':
            status = "Heating"
            signal = "BEARISH"
            summary = _("Inflation is re-accelerating, potentially forcing rate hikes.")
        else:
            status = "Sticky"
            signal = "NEUTRAL"
            summary = _("Core inflation remains persistent at {val}%.").format(val=val)

        macro_matrix.append({
            'category': _('Inflation'),
            'indicator': _('Price Stability'),
            'status': status,
            'signal': signal,
            'summary': summary
        })

    # 5. Labor Market
    lab_kpi = macro_kpis.get('UNRATE', {})
    if lab_kpi:
        rate = lab_kpi.get('current', 0)
        trend = lab_kpi.get('trend', 'neutral')
        if rate < 4.5 and trend != 'up': 
            status = "Strong"
            signal = "BULLISH"
            summary = _("Unemployment is low ({val}%), supporting consumer spending.").format(val=rate)
        elif trend == 'up':
            status = "Cooling"
            signal = "CAUTION"
            summary = _("Unemployment is rising ({val}%), signaling reliable slowdown.").format(val=rate)
        else:
            status = "Stable"
            signal = "NEUTRAL"
            summary = _("Labor market is balanced with {val}% unemployment.").format(val=rate)
            
        macro_matrix.append({
            'category': _('Labor Market'),
            'indicator': _('Employment'),
            'status': status,
            'signal': signal,
            'summary': summary
        })

    context['macro_matrix'] = macro_matrix
    context['ai_commentary'] = [] # Clear old list to avoid confusion

    return render(request, "insight/market_101.html", context)





GURUS = {
    "buffett": {
        "name": "Warren Buffett (Berkshire)",
        "cik": "0001067983",
    },
    "dalio": {
        "name": "Ray Dalio (Bridgewater)",
        "cik": "0001350694",
    },
    "simons": {
        "name": "Jim Simons (Renaissance)",
        "cik": "0001037389",
    },
    "soros": {
        "name": "George Soros (Soros Fund)",
        "cik": "0001029160",
    },
    "drucken": {
        "name": "Stanley Druckenmiller",
        "cik": "0001536411",
    },
    "nvidia": {
        "name": "Nvidia Corp (Strategic)",
        "cik": "0001045810",
    },
    "burry": {
        "name": "Michael Burry (Scion)",
        "cik": "0001649339",
    },
    "fisher": {
        "name": "Ken Fisher (Fisher Asset)",
        "cik": "0000850529",
    },
    "wood": {
        "name": "Cathie Wood (ARK)",
        "cik": "0001697748",
    },
    "ackman": {
        "name": "Bill Ackman (Pershing Sq)",
        "cik": "0001336528",
    },
}



# ---------- XML 파싱 유틸 ----------

def clean_xml_namespaces(xml_text: str) -> str:
    """
    SEC 13F XML에서 네임스페이스/접두사를 제거해서
    'unbound prefix' 에러를 방지한다.
    - xmlns, xmlns:prefix 제거
    - <n1:tag> -> <tag>, </n1:tag> -> </tag>
    - 속성 이름의 prefix (예: xsi:schemaLocation) -> schemaLocation
    """
    # 1) xmlns / xmlns:prefix 제거
    xml_text = re.sub(r'\sxmlns(:[A-Za-z_][\w\.-]*)?="[^"]+"', "", xml_text)

    # 2) 태그 이름 앞 prefix 제거: <n1:tag>, </n1:tag>
    xml_text = re.sub(r'(</?)[A-Za-z_][\w\.-]*:', r'\1', xml_text)

    # 3) 속성 이름 앞 prefix 제거: xsi:schemaLocation="..." -> schemaLocation="..."
    xml_text = re.sub(
        r'\s([A-Za-z_][\w\.-]*):([A-Za-z_][\w\.-]*=)',
        r' \2',
        xml_text,
    )

    return xml_text


def _find_child_any_case(parent: ET.Element, *names: str):
    """자식 태그를 대소문자 무시하고 찾는 헬퍼"""
    targets = {n.lower() for n in names}
    for child in parent:
        if child.tag.lower() in targets:
            return child
    return None


def parse_13f_xml(xml_text: str):
    """
    SEC 13F XML 파싱
    return: (holdings_list, total_value)
      holdings_list = [{"ticker","name","shares","value","percent(0으로 초기화)"}...]
    """
    holdings = []
    total_val = 0.0

    try:
        clean_text = clean_xml_namespaces(xml_text)
        root = ET.fromstring(clean_text)
    except Exception as e:
        print(f"[XML Parser] Error while parsing XML: {e}")
        return [], 0.0

    # infoTable 태그 찾기 (대소문자 무시)
    info_tables = [elem for elem in root.iter() if elem.tag.lower().endswith("infotable")]

    for info in info_tables:
        try:
            # 회사명
            name_node = _find_child_any_case(info, "nameOfIssuer", "nameofissuer")
            if name_node is None or not (name_node.text and name_node.text.strip()):
                continue
            name = name_node.text.strip()
            
            cusip = None
            cusip_node = _find_child_any_case(info, "cusip")
            if cusip_node is not None and cusip_node.text:
                cusip = cusip_node.text.strip()

            # 가치 (value, $1,000 단위)
            val_node = _find_child_any_case(info, "value")
            if val_node is None or not (val_node.text and val_node.text.strip()):
                continue
            try:
                val = float(val_node.text) * 1000.0
            except ValueError:
                continue

            # 주식 수
            shares = 0
            shrs_node = _find_child_any_case(info, "shrsOrPrnAmt", "shrsorprnamt")
            if shrs_node is not None:
                ssh_node = _find_child_any_case(shrs_node, "sshPrnamt", "sshprnamt")
                if ssh_node is not None and ssh_node.text:
                    try:
                        shares = int(float(ssh_node.text))
                    except ValueError:
                        shares = 0

            total_val += val
            ticker_display = name[:12].strip()

            holdings.append({
                "ticker": ticker_display,
                "cusip": cusip,
                "name": name,
                "shares": shares,
                "value": val,
                "percent": 0.0,
            })
        except Exception as e:
            print(f"[XML Parser] Row error: {e}")
            continue

    return holdings, total_val


# ---------- index.json 내 파일들 중 best XML 선택 ----------

def _try_parse_from_file_list(cik_int: str, acc_no_dashes: str, file_list: list, headers: dict):
    """
    index.json에 있는 파일들 중에서
    - infotable / info / 13f 를 포함하는 xml 위주로
    - 모든 후보를 파싱해 보고
    - '보유 종목 수가 가장 많은 파일'을 최종 선택한다.
    """
    base_url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_no_dashes}"

    candidates = []

    # 1) 'infotable' 포함 xml
    for f in file_list:
        name = f["name"]
        lower = name.lower()
        if lower.endswith(".xml") and "infotable" in lower:
            candidates.append(name)

    # 2) '13f' / 'info' 포함 xml
    for f in file_list:
        name = f["name"]
        lower = name.lower()
        if lower.endswith(".xml") and ("13f" in lower or "info" in lower):
            if name not in candidates:
                candidates.append(name)

    # 3) 나머지 모든 xml
    for f in file_list:
        name = f["name"]
        lower = name.lower()
        if lower.endswith(".xml") and name not in candidates:
            candidates.append(name)

    # 4) txt 도 마지막에
    for f in file_list:
        name = f["name"]
        lower = name.lower()
        if lower.endswith(".txt") and name not in candidates:
            candidates.append(name)

    if not candidates:
        return [], 0.0, None

    best_holdings = []
    best_total = 0.0
    best_file = None

    for fname in candidates:
        xml_url = f"{base_url}/{fname}"
        print(f"[EDGAR] [Try] Downloading candidate file: {xml_url}")
        try:
            time.sleep(0.3)
            res = requests.get(
                xml_url,
                headers={**headers, "Host": "www.sec.gov"},
                timeout=15,
            )
            if res.status_code != 200:
                print(f"[EDGAR] [Skip] HTTP {res.status_code} for {fname}")
                continue

            holdings, total_val = parse_13f_xml(res.text)
            print(f"[EDGAR] [Parsed] {fname}: {len(holdings)} rows, total={total_val}")

            # 🔥 종목 수가 가장 많은 파일을 선택
            if holdings and len(holdings) > len(best_holdings):
                best_holdings = holdings
                best_total = total_val
                best_file = fname

        except Exception as e:
            print(f"[EDGAR] [Error] While parsing {fname}: {e}")
            continue

    if best_holdings:
        print(f"[EDGAR] [OK] Picked best file: {best_file} with {len(best_holdings)} holdings")
    else:
         print("[EDGAR] [Fail] No valid holdings from any candidate file")

    return best_holdings, best_total, best_file



# ---------- submissions JSON에서 서로 다른 분기 2개 찾기 ----------

def _get_recent_13f_indices(recent):
    from datetime import datetime, date

    forms = recent.get("form", [])
    acc_nums = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])
    report_dates = recent.get("reportDate", [])

    filings = []
    for i, form in enumerate(forms):
        if form not in ("13F-HR", "13F-HR/A"):
            continue
        rd = report_dates[i] if report_dates and i < len(report_dates) else "-"
        filings.append({
            "idx": i,
            "form": form,
            "acc": acc_nums[i],
            "primary": primary_docs[i],
            "report_date": rd,
        })

    # reportDate 로 그룹핑
    by_date = {}
    for f in filings:
        by_date.setdefault(f["report_date"], []).append(f)

    def parse_rd(rd):
        try:
            return datetime.strptime(rd, "%Y-%m-%d").date()
        except Exception:
            return date.min

    # reportDate 기준 내림차순 정렬 (가장 최근 2개 분기)
    sorted_dates = sorted(by_date.keys(), key=parse_rd, reverse=True)

    indices = []
    for rd in sorted_dates[:2]:
        group = by_date[rd]
        # 같은 분기 안에서는 HR/A를 우선, 그다음 최근 filing
        group.sort(key=lambda f: (f["form"] != "13F-HR/A", -f["idx"]))
        pick = group[0]
        indices.append(
            (pick["idx"], pick["acc"], pick["primary"], pick["report_date"])
        )

    return indices



# ---------- 개별 13F filing 스냅샷 가져오기 ----------

def _fetch_single_13f_snapshot(cik_int: str, accession_num: str, headers_base: dict):
    """
    단일 13F filing (accession_num)에 대해:
    - index.json에서 파일 목록 조회
    - _try_parse_from_file_list로 holdings/total_val 파싱
    return: (holdings_list, total_val)
    """
    acc_no_dashes = accession_num.replace("-", "")

    index_json_url = (
        f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_no_dashes}/index.json"
    )
    print(f"[EDGAR] [index] {index_json_url}")

    time.sleep(0.2)
    res_idx = requests.get(
        index_json_url,
        headers={**headers_base, "Host": "www.sec.gov"},
        timeout=10,
    )
    if res_idx.status_code != 200:
        print(f"[EDGAR] index.json request failed: {res_idx.status_code}")
        return [], 0.0

    file_list = res_idx.json().get("directory", {}).get("item", [])
    if not file_list:
        print("[EDGAR] No files found in index.json")
        return [], 0.0

    holdings, total_val, used_file = _try_parse_from_file_list(
        cik_int=cik_int,
        acc_no_dashes=acc_no_dashes,
        file_list=file_list,
        headers=headers_base,
    )
    if not holdings:
        print("[EDGAR] Parsed holdings is empty from all candidate files.")
        return [], 0.0

    # 🔥 여기서 같은 종목끼리 합산
    holdings = aggregate_holdings_by_security(holdings)
    total_val = sum(h["value"] for h in holdings)

    print(f"[EDGAR] Successfully parsed from file: {used_file} "
          f"(after aggregation: {len(holdings)} rows)")

    return holdings, total_val



# ---------- 현재 vs 직전 분기 diff 계산 ----------

def compute_holdings_changes(current_list, previous_list, share_threshold=0.01):
    """
    current_list / previous_list:
      {"cusip","ticker","name","shares","value","percent"} 의 dict 리스트

    분류 기준:
      - New    : 이전 분기 shares == 0, 현재 > 0
      - Exited : 이전 > 0, 현재 == 0
      - Increased : shares 가 의미 있게 증가 (share_threshold 이상)
      - Decreased : shares 가 의미 있게 감소
    ↑/↓ 판정은 'shares' 로, 금액 표시/정렬은 'value' 로.
    """

    # 공통: key 매핑 (CUSIP 우선, 없으면 ticker/name)
    def to_map(lst):
        m = {}
        for h in lst:
            key = (h.get("cusip") or "").strip()
            if not key:
                key = (h.get("ticker") or h.get("name") or "").strip().upper()
            if key:
                m[key] = h
        return m

    curr_map = to_map(current_list)
    prev_map = to_map(previous_list)

    new_positions = []
    exited_positions = []
    increased = []
    decreased = []

    all_keys = set(curr_map.keys()) | set(prev_map.keys())

    for key in all_keys:
        ch = curr_map.get(key)
        ph = prev_map.get(key)

        curr_sh = (ch.get("shares") if ch else 0) or 0
        prev_sh = (ph.get("shares") if ph else 0) or 0
        curr_val = (ch.get("value") if ch else 0.0) or 0.0
        prev_val = (ph.get("value") if ph else 0.0) or 0.0

        name = (ch or ph).get("name")
        ticker = (ch or ph).get("ticker")

        # 1) 신규 / 완전 매도
        if prev_sh == 0 and curr_sh > 0:
            new_positions.append({
                "name": name,
                "ticker": ticker,
                "prev_value": 0.0,
                "curr_value": curr_val,
                "diff_value": curr_val,
                "diff_pct": None,
                "share_diff": curr_sh,
                "share_pct": None,
                "curr_shares": curr_sh,
                "prev_shares": 0,
            })
            continue

        if prev_sh > 0 and curr_sh == 0:
            exited_positions.append({
                "name": name,
                "ticker": ticker,
                "prev_value": prev_val,
                "curr_value": 0.0,
                "diff_value": -prev_val,
                "diff_pct": -100.0 if prev_val > 0 else None,
                "share_diff": -prev_sh,
                "share_pct": -100.0,
                "curr_shares": 0,           # ⬅ 추가
                "prev_shares": prev_sh,
            })
            continue

        # 2) 둘 다 보유 → 증감 판정 (shares 기준)
        if prev_sh == 0 and curr_sh == 0:
            continue  # 둘 다 0이면 뭔가 이상한 케이스

        share_diff = curr_sh - prev_sh
        share_pct = (share_diff / prev_sh * 100.0) if prev_sh > 0 else None
        value_diff = curr_val - prev_val
        value_pct = (value_diff / prev_val * 100.0) if prev_val > 0 else None

        # threshold(1%) 이하면 거의 안 바뀐 걸로 보고 무시
        if prev_sh > 0:
            rel_change = abs(share_diff) / prev_sh
            if rel_change < share_threshold:
                continue

        rec = {
    "name": name,
    "ticker": ticker,
    "prev_value": prev_val,
    "curr_value": curr_val,
    "diff_value": value_diff,
    "diff_pct": value_pct,
    "share_diff": share_diff,
    "share_pct": share_pct,
    "curr_shares": curr_sh,     # ⬅ 추가
    "prev_shares": prev_sh,     # ⬅ 추가
}


        if share_diff > 0:
            increased.append(rec)
        elif share_diff < 0:
            decreased.append(rec)

    # 정렬: 금액 기준으로 큰 것부터
    new_positions.sort(key=lambda x: x["curr_value"], reverse=True)
    exited_positions.sort(key=lambda x: x["prev_value"], reverse=True)
    increased.sort(key=lambda x: x["diff_value"], reverse=True)
    decreased.sort(key=lambda x: x["diff_value"])  # value 기준 가장 많이 줄어든 것부터

    return {
        "new_positions": new_positions,
        "exited_positions": exited_positions,
        "increased": increased,
        "decreased": decreased,
    }



# ---------- 최신 분기 스냅샷을 MongoDB에 저장 ----------

def _fetch_and_save_mongo(guru_key: str):
    """
    - SEC submissions API 사용해서 최신 13F-HR / 13F-HR/A 찾기
    - 해당 filing을 파싱해 MongoDB(GuruPortfolioDoc)에 저장 (스냅샷 1개)
    """
    target = GURUS[guru_key]
    cik_str = target["cik"]
    cik_int = str(int(cik_str))

    headers_base = {
        "User-Agent": "QuantDeckProject (admin@quantdeck.com)",
        "Accept-Encoding": "gzip, deflate",
    }

    print(f"[EDGAR] 1. Fetching Filing List for {guru_key}...")

    try:
        url_submissions = f"https://data.sec.gov/submissions/CIK{cik_str}.json"
        res = requests.get(
            url_submissions,
            headers={**headers_base, "Host": "data.sec.gov"},
            timeout=10,
        )
        if res.status_code != 200:
            print(f"[EDGAR] submissions request failed: {res.status_code}")
            return None

        data = res.json()
        recent = data["filings"]["recent"]

        indices = _get_recent_13f_indices(recent)
        if not indices:
            print("[EDGAR] No 13F-HR / 13F-HR/A filing found.")
            return None

        # 최신 분기
        _, latest_acc_num, _, latest_report_date = indices[0]

        # 🔍 DB에 이미 같은 report_date 로 저장되어 있으면 그냥 리턴
        existing = GuruPortfolioDoc.objects(guru_key=guru_key).first()
        if existing and existing.report_date == latest_report_date:
            print("[EDGAR] already up-to-date:", latest_report_date)
            return existing

        # 최신 분기 스냅샷 파싱
        holdings_list, total_val = _fetch_single_13f_snapshot(
            cik_int=cik_int,
            accession_num=latest_acc_num,
            headers_base=headers_base,
        )
        if not holdings_list:
            print("[EDGAR] No holdings parsed for latest filing.")
            return None

        # 비중 계산 및 정렬
        if total_val > 0:
            for h in holdings_list:
                h["percent"] = (h["value"] / total_val) * 100.0

        holdings_list.sort(key=lambda x: x["value"], reverse=True)

        # MongoEngine EmbeddedDocument 변환 (최대 300개)
        saved_holdings = []
        for h in holdings_list[:300]:
            saved_holdings.append(
                Holding(
                    ticker=h["ticker"],
                    cusip=h.get("cusip"),
                    name=h["name"],
                    shares=h["shares"],
                    value=h["value"],
                    percent=h["percent"],
                )
            )

        doc = GuruPortfolioDoc.objects(guru_key=guru_key).first()
        if not doc:
            doc = GuruPortfolioDoc(guru_key=guru_key)

        doc.name = target["name"]
        doc.report_date = latest_report_date
        doc.holdings = saved_holdings
        doc.total_value = total_val
        doc.count = len(holdings_list)
        doc.updated_at = datetime.datetime.now()
        doc.save()

        print(f"[EDGAR] [Success] Saved {doc.count} holdings for {guru_key}")
        return doc

    except Exception as e:
        print(f"[EDGAR Process Error] {e}")
        return None


# ---------- 직전 분기 holdings 가져오기 (DB 저장 X) ----------

def _fetch_prev_quarter_holdings(guru_key: str):
    """
    해당 guru의 '직전 분기' 13F holdings(dict 리스트)를 SEC에서 직접 가져온다.
    DB에는 저장하지 않고 diff 계산용으로만 사용.
    """
    target = GURUS[guru_key]
    cik_str = target["cik"]
    cik_int = str(int(cik_str))

    headers_base = {
        "User-Agent": "QuantDeckProject (admin@quantdeck.com)",
        "Accept-Encoding": "gzip, deflate",
    }

    try:
        url_submissions = f"https://data.sec.gov/submissions/CIK{cik_str}.json"
        res = requests.get(
            url_submissions,
            headers={**headers_base, "Host": "data.sec.gov"},
            timeout=10,
        )
        if res.status_code != 200:
            print(f"[EDGAR] submissions request failed (prev): {res.status_code}")
            return None

        data = res.json()
        recent = data["filings"]["recent"]

        indices = _get_recent_13f_indices(recent)
        if len(indices) < 2:
            print("[EDGAR] No previous 13F filing found.")
            return None

        # 두 번째가 직전 분기
        _, prev_acc_num, prev_primary, prev_report_date = indices[1]
        print(f"[EDGAR] prev quarter report_date={prev_report_date}, acc={prev_acc_num}")

        prev_holdings_raw, prev_total = _fetch_single_13f_snapshot(
            cik_int=cik_int,
            accession_num=prev_acc_num,
            headers_base=headers_base,
        )
        if not prev_holdings_raw:
            print("[EDGAR] prev_holdings_raw is empty")
            return None

        # 🔥 여기서도 반드시 집계된 버전이 나오도록 (이미 _fetch_single_13f_snapshot 안에서 aggregate 호출했다면 이 줄은 생략)
        prev_holdings = prev_holdings_raw
        print(f"[EDGAR] prev_holdings count after agg: {len(prev_holdings)}")

        return prev_holdings

    except Exception as e:
        print(f"[EDGAR Prev Process Error] {e}")
        return None


def aggregate_holdings_by_security(holdings):
    """
    같은 종목(CUSIP 기준, 없으면 이름/티커)을 하나로 합쳐서
    shares, value 를 합산한다.
    """
    grouped = {}

    for h in holdings:
        cusip = (h.get("cusip") or "").strip().upper()
        name = (h.get("name") or "").strip()
        ticker = (h.get("ticker") or "").strip()

        # key: CUSIP 우선, 없으면 NAME, 그것도 없으면 TICKER
        key = cusip or name.upper() or ticker.upper()
        if not key:
            continue

        if key not in grouped:
            # 원본 한 줄을 복사해서 시작
            grouped[key] = {
                "cusip": cusip or None,
                "ticker": ticker,
                "name": name,
                "shares": h.get("shares") or 0,
                "value": h.get("value") or 0.0,
                "percent": 0.0,  # 나중에 다시 계산
            }
        else:
            g = grouped[key]
            g["shares"] += h.get("shares") or 0
            g["value"] += h.get("value") or 0.0

    return list(grouped.values())



def institutional_holdings(request):
    # 1) guru 선택 (기본: buffett)
    guru_key = request.GET.get("guru", "buffett")
    if guru_key not in GURUS:
        guru_key = "buffett"

    # 2) MongoDB에서 기존 포트폴리오 조회 + 필요하면 SEC에서 업데이트
    portfolio = GuruPortfolioDoc.objects(guru_key=guru_key).first()

    should_update = False
    if not portfolio:
        should_update = True
    else:
        diff = datetime.now() - portfolio.updated_at
        if diff.days >= 1:
            should_update = True

    if should_update:
        new_doc = _fetch_and_save_mongo(guru_key)
        if new_doc:
            portfolio = new_doc

    holdings = []
    chart_labels = []
    chart_series = []
    changes = None
    share_change_labels = []
    share_change_values = []

    meta_info = {
        "name": GURUS[guru_key]["name"],
        "date": "-",
        "total_value": 0,
        "count": 0,
    }

    if portfolio:
        holdings = list(portfolio.holdings)
        meta_info = {
            "name": portfolio.name,
            "date": portfolio.report_date,
            "total_value": portfolio.total_value,
            "count": portfolio.count,
        }

        # 도넛 차트용 (Top10 + Others)
        if holdings:
            holdings_sorted = sorted(holdings, key=lambda h: h.value, reverse=True)
            top_10 = holdings_sorted[:10]
            others = holdings_sorted[10:]

            for h in top_10:
                chart_labels.append(h.ticker or h.name[:12])
                chart_series.append(h.value or 0.0)

            if others:
                others_value = sum(h.value or 0.0 for h in others)
                chart_labels.append("Others")
                chart_series.append(others_value)

    # 3) 이전 분기 diff 계산 (shares 기준)
    prev_holdings = None
    if holdings:
        prev_holdings = _fetch_prev_quarter_holdings(guru_key)

    if prev_holdings:
        current_list = [
            {
                "cusip": getattr(h, "cusip", None),
                "ticker": h.ticker,
                "name": h.name,
                "shares": h.shares or 0,
                "value": h.value or 0.0,
                "percent": h.percent or 0.0,
            }
            for h in holdings
        ]

        if len(prev_holdings) >= len(current_list) * 0.5:
            changes = compute_holdings_changes(current_list, prev_holdings, share_threshold=0.001)

    # 4) Shares Change Bar Chart + 하이라이트용 티커 리스트
    new_tickers = []
    exit_tickers = []
    increased_tickers = []
    decreased_tickers = []

    if changes:
        combined = []

        # New
        for item in changes.get("new_positions", []):
            t = item.get("ticker")
            if t:
                new_tickers.append(t)
            combined.append(item)

        # Exited
        for item in changes.get("exited_positions", []):
            t = item.get("ticker")
            if t:
                exit_tickers.append(t)
            combined.append(item)

        # Increased
        for item in changes.get("increased", []):
            t = item.get("ticker")
            if t:
                increased_tickers.append(t)
            combined.append(item)

        # Decreased
        for item in changes.get("decreased", []):
            t = item.get("ticker")
            if t:
                decreased_tickers.append(t)
            combined.append(item)

        # 바차트: 절대 share 변화량 큰 순으로 Top 10
        combined.sort(key=lambda x: abs(x.get("share_diff") or 0), reverse=True)
        top_n = combined[:10]

        for item in top_n:
            label = item.get("ticker") or (item.get("name") or "")[:12]
            share_change_labels.append(label)
            share_change_values.append(item.get("share_diff") or 0)

    # 5) 템플릿으로 전달
    context = {
        "gurus": GURUS,
        "current_guru": guru_key,
        "current_guru_name": GURUS[guru_key]["name"],
        "meta": meta_info,
        "holdings": holdings,  # 이제 그냥 원래 holdings 그대로 전달
        "chart_labels": json.dumps(chart_labels),
        "chart_series": json.dumps(chart_series),
        "share_change_labels": json.dumps(share_change_labels),
        "share_change_values": json.dumps(share_change_values),
        "changes": changes,
        # 🔥 하이라이트용 티커 리스트들
        "new_tickers": new_tickers,
        "exit_tickers": exit_tickers,
        "increased_tickers": increased_tickers,
        "decreased_tickers": decreased_tickers,
    }

    return render(request, "insight/13f.html", context)

from django.shortcuts import render
from django.http import JsonResponse
from sec_edgar_downloader import Downloader
from bs4 import BeautifulSoup
import os
import glob
from django.conf import settings
from google import genai
from ai_advisor.prompts import get_earnings_summary_prompt
MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

def _client():
    key = os.getenv("GEMINI2_API_KEY")
    if not key:
        return None  # Or handle error appropriately
    return genai.Client(api_key=key)

def get_earnings_dates(symbol):
    """
    Fetch earnings dates using yfinance.
    Returns (latest_date, yoy_date) as datetime objects or None.
    """
    import yfinance as yf
    try:
        ticker = yf.Ticker(symbol)
        # Try to get earnings dates from calendar or earnings_dates
        # 1. Try earnings_dates DataFrame (contains past and future)
        ed = ticker.earnings_dates
        if ed is not None and not ed.empty:
            now = pd.Timestamp.now(tz=ed.index.tz)
            # Filter for past dates
            past_earnings = ed[ed.index < now]
            if not past_earnings.empty:
                latest_date = past_earnings.index[0]
                # Find YoY date (approx 1 year ago)
                # Look for a date roughly 365 days ago +/- 30 days
                target_yoy = latest_date - pd.Timedelta(days=365)
                yoy_date = None
                
                # Find closest date in past_earnings to target_yoy
                # Simple approach: iterate and find min distance
                min_diff = pd.Timedelta(days=45) # Max 45 days diff
                for date in past_earnings.index:
                    diff = abs(date - target_yoy)
                    if diff < min_diff:
                        min_diff = diff
                        yoy_date = date
                
                return latest_date.to_pydatetime(), yoy_date.to_pydatetime() if yoy_date else None

        # 2. Fallback to simple calendar (might only have next earnings)
        # Usually not useful for past earnings, so we rely on earnings_dates
        return None, None
    except Exception as e:
        print(f"Error fetching earnings dates for {symbol}: {e}")
        return None, None


def get_sorted_8k_files(symbol):
    """
    Finds and sorts 8-K filings for a symbol by 'FILED AS OF DATE' or 'CONFORMED PERIOD OF REPORT'.
    Returns a list of file paths sorted by date descending.
    """
    search_path = settings.BASE_DIR / "temp_sec" / "sec-edgar-filings" / symbol / "8-K" / "*" / "full-submission.txt"
    files = glob.glob(str(search_path))
    
    if not files:
        return []

    file_dates = []
    
    for fpath in files:
        try:
            date_val = 0
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                # Read first 2k bytes usually enough for header
                head = f.read(2000)
                
                # Try finding FILED AS OF DATE
                m = re.search(r"FILED AS OF DATE:\s+(\d+)", head)
                if m:
                    date_val = int(m.group(1))
                else:
                    # Fallback to CONFORMED PERIOD OF REPORT
                    m2 = re.search(r"CONFORMED PERIOD OF REPORT:\s+(\d+)", head)
                    if m2:
                        date_val = int(m2.group(1))
            
            file_dates.append((date_val, fpath))
        except Exception:
             # If read fails, treat as oldest
            file_dates.append((0, fpath))
            
    # Sort by date descending
    file_dates.sort(key=lambda x: x[0], reverse=True)
    
    return [x[1] for x in file_dates]


def earnings_report(request):
    if request.method == "POST":
        symbol = request.POST.get("symbol", "").upper().strip()
        if not symbol:
            return render(request, "insight/earnings.html", {"error": "Please enter a symbol."})

        try:
            # 0. Clear existing 8-K files for this symbol to prevent stale data
            import shutil
            symbol_8k_dir = settings.BASE_DIR / "temp_sec" / "sec-edgar-filings" / symbol / "8-K"
            if symbol_8k_dir.exists():
                try:
                    shutil.rmtree(symbol_8k_dir)
                except Exception as e:
                    print(f"Cleanup error: {e}")

            # 1. Download Latest 10 8-K Filings Directly
            start_time = time.time()
            # method signature: Downloader(company_name, email_address, download_folder=...)
            dl = Downloader("Vestiq AI", "admin@vestiq.com", settings.BASE_DIR / "temp_sec")
            try:
                dl.get("8-K", symbol, limit=10, include_amends=False) 
            except Exception as e:
                print(f"SEC Download Error: {e}")
                
            # 1.5 Get sorted files by DATE (Robust)
            files = get_sorted_8k_files(symbol)
            
            if not files:
                return render(request, "insight/earnings.html", {"error": f"No 8-K filings found for {symbol}. Symbol might be incorrect or no recent filings."})

            # 2. Find "Results of Operations" (Item 2.02)
            earnings_files = []
            
            for fpath in files:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    content_head = f.read(50000) # Read enough to find items
                    if re.search(r"Item\s+2\.02", content_head, re.IGNORECASE):
                        earnings_files.append(fpath)
            
            # Helper to extract text from HTML content
            def extract_text_from_html(html_content):
                soup = BeautifulSoup(html_content, "html.parser")
                return soup.get_text(separator="\n", strip=True)

            # Helper to process a single file
            def process_file(fpath):
                text_content = ""
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                
                # 1. Main 8-K
                main_match = re.search(r"<DOCUMENT>\s*<TYPE>8-K(?:.|\n)*?<TEXT>(.*?)</TEXT>", content, re.DOTALL | re.IGNORECASE)
                if main_match:
                    text_content += "--- MAIN 8-K BODY ---\n" + extract_text_from_html(main_match.group(1)) + "\n\n"

                # 2. Exhibits
                exhibit_matches = re.finditer(r"<DOCUMENT>\s*<TYPE>(EX-99\.\d+)(?:.|\n)*?<TEXT>(.*?)</TEXT>", content, re.DOTALL | re.IGNORECASE)
                for m in exhibit_matches:
                    dtype = m.group(1)
                    html_content = m.group(2)
                    text_content += f"--- {dtype} (Exhibit) ---\n" + extract_text_from_html(html_content) + "\n\n"
                return text_content

            # Select the files to analyze
            current_text = ""
            previous_text = ""
            
            # Logic: If we found explicit Earnings 8-Ks, use the latest one.
            if earnings_files:
                current_text = process_file(earnings_files[0])
            else:
                 # Fallback to latest file if no Item 2.02 found
                 current_text = process_file(files[0])
            
            # Process Previous Report (if available)
            if len(earnings_files) >= 2:
                previous_text = process_file(earnings_files[1])

            if not current_text:
                return render(request, "insight/earnings.html", {"error": "No 8-K content found for this symbol."})

            # Limit text length
            current_text = current_text[:80000] 
            previous_text = previous_text[:40000] # Smaller limit for previous report to save tokens

            # 3.5 Fetch Market Data (yfinance)
            import yfinance as yf
            market_data = {}
            try:
                ticker = yf.Ticker(symbol)
                info = ticker.info
                market_data = {
                    "currentPrice": info.get("currentPrice"),
                    "trailingPE": info.get("trailingPE"),
                    "forwardPE": info.get("forwardPE"),
                    "priceToBook": info.get("priceToBook"),
                    "targetMeanPrice": info.get("targetMeanPrice"),
                    "targetHighPrice": info.get("targetHighPrice"),
                    "targetLowPrice": info.get("targetLowPrice"),
                    "numberOfAnalystOpinions": info.get("numberOfAnalystOpinions"),
                    "recommendationKey": info.get("recommendationKey"),
                }
            except Exception as e:
                print(f"Failed to fetch market data for {symbol}: {e}")

            # 4. AI Summary
            if settings.GEMINI_ENABLED:
                client = _client()
                prompt = get_earnings_summary_prompt(symbol, current_text, previous_text, market_data)
                response = client.models.generate_content(model=MODEL, contents=prompt)
                raw_text = getattr(response, "text", "")
                
                # Extract JSON
                import json
                cleaned_text = raw_text.strip()
                if "```json" in cleaned_text:
                    cleaned_text = re.sub(r"^```json|```$", "", cleaned_text, flags=re.MULTILINE).strip()
                elif "```" in cleaned_text:
                    cleaned_text = re.sub(r"^```|```$", "", cleaned_text, flags=re.MULTILINE).strip()
                
                try:
                    summary_data = json.loads(cleaned_text)
                except json.JSONDecodeError:
                    summary_data = {"summary": raw_text, "sentiment": "Neutral", "key_takeaways": [], "financial_highlights": []}
            else:
                summary_data = {"summary": "Gemini API is not enabled.", "sentiment": "Neutral"}

            data_json = json.dumps(summary_data)
            return render(request, "insight/earnings.html", {"symbol": symbol, "data": summary_data, "data_json": data_json})

        except Exception as e:
            return render(request, "insight/earnings.html", {"error": str(e)})

    return render(request, "insight/earnings.html")


def earnings_source(request, symbol):
    """Serve the downloaded 8-K HTML file."""
    symbol = symbol.upper()
    
    # Use the same robust sorting logic
    files = get_sorted_8k_files(symbol)
    
    if not files:
        # from django.http import HttpResponse # Removed to fix UnboundLocalError
        return HttpResponse("Source file not found.", status=404)
        
    # We ideally want the 'Earnings' file (Item 2.02)
    # But since we don't know for sure which one the AI analyzed without re-parsing,
    # we will try to return the latest Item 2.02 if present, otherwise the absolute latest file.
    # This matches the logic in earnings_report where we prioritize earnings_files[0].
    
    target_file = files[0] # Default to latest
    
    for fpath in files:
        try:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                head = f.read(50000)
                if re.search(r"Item\s+2\.02", head, re.IGNORECASE):
                    target_file = fpath
                    break
        except: continue
    
    try:
        with open(target_file, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        return HttpResponse(content, content_type="text/plain") 
    except Exception as e:
        return HttpResponse(f"Error reading file: {e}", status=500)


def email_earnings_report(request):
    """Generate PDF and email the earnings report."""
    if request.method == "POST":
        symbol = request.POST.get("symbol")
        email = request.POST.get("email")
        data_json = request.POST.get("data")
        
        if not symbol or not email or not data_json:
            return HttpResponse("Missing data.", status=400)
            
        try:
            data = json.loads(data_json)
            
            # Generate PDF
            from io import BytesIO
            from .pdf_utils import generate_earnings_pdf
            from django.core.mail import EmailMessage
            
            buffer = BytesIO()
            generate_earnings_pdf(buffer, symbol, data)
            pdf_content = buffer.getvalue()
            buffer.close()
            
            # Send Email
            subject = f"Earnings Report: {symbol} - Vestiq AI"
            body = f"Please find attached the AI-generated earnings report for {symbol}.\n\nBest regards,\nVestiq Team"
            
            email_msg = EmailMessage(
                subject,
                body,
                settings.EMAIL_HOST_USER, # From
                [email], # To
            )
            email_msg.attach(f"{symbol}_Earnings_Report.pdf", pdf_content, "application/pdf")
            email_msg.send()
            
            # Return success (could be a redirect or a JSON response for AJAX)
            # For simplicity, redirect back to earnings page with a success message (via session or query param)
            # But since we don't have easy session setup here, let's just render a simple success page or redirect
            return render(request, "insight/earnings.html", {"symbol": symbol, "data": data, "data_json": data_json, "success": "Email sent successfully!"})
            
        except Exception as e:
            return HttpResponse(f"Error sending email: {e}", status=500)
            
    return HttpResponse("Invalid request.", status=400)


# --- 5. Correlation Matrix Heatmap ---
def correlation_matrix(request):
    """
    Correlation Matrix Heatmap
    Analyzes correlation between selected stocks over the last 6 months.
    """
    default_tickers = "AAPL,MSFT,TSLA,GLD,TLT"
    tickers_str = request.GET.get('tickers', default_tickers)
    
    # Clean and split tickers
    tickers = [t.strip().upper() for t in tickers_str.split(',') if t.strip()]
    # Limit to 10 to prevent abuse/performance issues
    tickers = tickers[:10]
    
    context = {
        'tickers_str': ",".join(tickers),
        'default_tickers': default_tickers
    }
    
    if tickers:
        try:
            # Fetch 6 months of history
            # yfinance download accepts list of tickers
            data = yf.download(tickers, period="6mo", interval="1d", progress=False)
            
            if data.empty:
                context['error'] = "No data found for selected tickers."
            else:
                # Handle MultiIndex columns if multiple tickers
                # If only 1 ticker, columns are just 'Open', 'High', etc.
                # If multiple, columns are ('Adj Close', 'AAPL'), etc.
                
                # We want 'Adj Close' or 'Close'
                price_data = None
                if 'Adj Close' in data:
                    price_data = data['Adj Close']
                elif 'Close' in data:
                    price_data = data['Close']
                else:
                    # Fallback if structure is different
                    price_data = data
                
                # If single ticker, price_data is Series (or DataFrame with 1 col)
                # We need DataFrame to calculate correlation (though 1 ticker corr is 1.0)
                if isinstance(price_data, pd.Series):
                    price_data = price_data.to_frame(name=tickers[0])
                
                # Calculate Daily Returns
                returns = price_data.pct_change().dropna()
                
                # Calculate Correlation Matrix
                corr_matrix = returns.corr()
                
                # Prepare data for heatmap
                # We need: labels (x/y axis), and values (z)
                labels = corr_matrix.columns.tolist()
                
                # Convert to list of dicts for template/JS
                # Format: { x: "AAPL", y: "MSFT", v: 0.85 }
                heatmap_data = []
                for i, row_ticker in enumerate(labels):
                    for j, col_ticker in enumerate(labels):
                        val = corr_matrix.iloc[i, j]
                        heatmap_data.append({
                            'x': col_ticker,
                            'y': row_ticker,
                            'v': round(val, 2)
                        })
                
                context['labels'] = json.dumps(labels)
                context['heatmap_data'] = json.dumps(heatmap_data)
                
        except Exception as e:
            print(f"Correlation Error: {e}")
            context['error'] = f"Error analyzing data: {str(e)}"
            
    return render(request, "insight/correlation.html", context)

# -----------------------------
# Sector Leaders
# -----------------------------
# -----------------------------
# Sector Leaders
# -----------------------------
def sector_leaders_view(request):
    """
    Displays daily sector performance and leaders.
    Model: SectorPerformance
    """
    from .models import SectorPerformance
    from datetime import date, timedelta
    
    # 1. Get selected date or latest date
    selected_date_str = request.GET.get('date')
    
    if selected_date_str:
        try:
            target_date = date.fromisoformat(selected_date_str)
        except ValueError:
            # Invalid date format, fallback to latest
            latest_obj = SectorPerformance.objects.order_by('-date').first()
            target_date = latest_obj.date if latest_obj else date.today()
    else:
        # Get latest available date
        latest_obj = SectorPerformance.objects.order_by('-date').first()
        if not latest_obj:
            return render(request, "insight/sector_leaders.html", {"error": "No data available."})
        target_date = latest_obj.date
    
    # 2. Fetch all sectors for that date
    sectors = SectorPerformance.objects.filter(date=target_date)
    
    if not sectors.exists():
        return render(request, "insight/sector_leaders.html", {
            "error": f"No data available for {target_date}.",
            "date": target_date
        })
    
    # Ensure sorted by performance (desc)
    sorted_sectors = sorted(sectors, key=lambda x: x.change_percent, reverse=True)
    
    # 3. Get available dates for date picker (last 14 days)
    available_dates = SectorPerformance.objects.values_list('date', flat=True).distinct().order_by('-date')[:14]
    
    # 4. Translation Map
    TRANS_MAP = {
        "Technology": "기술 (Technology)",
        "Financial Services": "금융 (Financials)",
        "Consumer Cyclical": "임의소비재 (Cyclical)",
        "Consumer Defensive": "필수소비재 (Defensive)",
        "Healthcare": "헬스케어 (Healthcare)",
        "Basic Materials": "소재 (Materials)",
        "Communication Services": "통신서비스 (Communication)",
        "Industrials": "산업재 (Industrials)",
        "Energy": "에너지 (Energy)",
        "Utilities": "유틸리티 (Utilities)",
        "Real Estate": "부동산 (Real Estate)",
        "Quantum": "퀀텀 (Quantum)",
        "Aerospace & Defense": "항공우주 & 방산 (Aerospace & Defense)",
    }
    
    # --- New: Fetch History for Sparklines (Last 30 Days) ---
    today = date.today()
    start_date = today - timedelta(days=45) # Fetch a bit more to be safe
    
    # Bulk fetch all sector history for this date range
    hist_qs = SectorPerformance.objects.filter(date__gte=start_date, date__lte=target_date).order_by('date')
    
    # Group by sector
    from collections import defaultdict
    sector_history = defaultdict(list)
    for h in hist_qs:
        sector_history[h.sector].append({
            'date': h.date.isoformat(),
            'val': h.change_percent
        })
        
    for s in sorted_sectors:
        # Use get with default to original name if not found
        s.sector_display = TRANS_MAP.get(s.sector, s.sector)
        
        # Attach history for chart
        raw_hist = sector_history.get(s.sector, [])
        # Ensure sorted by date
        # (It should be due to DB query, but let's be safe if dict order varies)
        # We only need the values for sparkline, but let's pass date/val pairs
        s.history_json = json.dumps(raw_hist)
        # Also calculate simple trend? (Already visually done by chart)

    # --- New: Identify 2-Week Consensus Leader (Top 5) ---
    consensus_leaders = []
    
    if hist_qs.exists():
        trend_start = target_date - timedelta(days=14)
        trend_qs = hist_qs.filter(date__gte=trend_start)
        
        sector_scores = defaultdict(float)
        for h in trend_qs:
            sector_scores[h.sector] += h.change_percent
            
        if sector_scores:
            # Sort by total score desc
            sorted_scores = sorted(sector_scores.items(), key=lambda x: x[1], reverse=True)[:5]
            
            for rank, (sec_key, score) in enumerate(sorted_scores, 1):
                consensus_leaders.append({
                    'rank': rank,
                    'name': TRANS_MAP.get(sec_key, sec_key),
                    'score': round(score, 2),
                    'key': sec_key
                })

    context = {
        "date": target_date,
        "sectors": sorted_sectors,
        "available_dates": list(available_dates),
        "available_dates_json": json.dumps([d.isoformat() for d in available_dates]), 
        "consensus_leaders": consensus_leaders, # Updated to List
    }
    return render(request, "insight/sector_leaders.html", context)

def update_sector_leaders_manual(request):
    """
    Manually triggers the Sector Leaders update (Async/Threaded).
    Updates last 14 days to ensure trend data is accurate.
    """
    from django.contrib import messages
    from django.shortcuts import redirect
    from django.http import JsonResponse
    from .services import update_daily_sector_performance
    from datetime import timedelta, date
    import threading
    from updatedata.tasks import _set_progress
    
    # Check if user is authenticated
    if not request.user.is_authenticated:
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
             return JsonResponse({'status': 'error', 'message': 'Please log in.'}, status=403)
        messages.error(request, "Please log in to refresh data.")
        return redirect("insight:sector_leaders")
        
    def _run_task():
        cache_key = 'progress_sector_leaders'
        _set_progress(cache_key, 0, "Initializing Sector Update...")
        
        try:
            today = date.today()
            trading_days = []
            days_checked = 0
            
            # Collect 10 trading days (skip weekends)
            while len(trading_days) < 10 and days_checked < 20:  # Safety limit
                target = today - timedelta(days=days_checked)
                # Skip weekends (Saturday=5, Sunday=6)
                if target.weekday() < 5:
                    trading_days.append(target)
                days_checked += 1
            
            total_days = len(trading_days)
            
            for i, target in enumerate(trading_days):
                # Calculate progress: 0 to 90%
                pct = int((i / total_days) * 90)
                _set_progress(cache_key, pct, f"Updating sectors for {target} ({i+1}/{total_days})...")
                
                update_daily_sector_performance(target)
                
            _set_progress(cache_key, 100, "Sector Leaders update complete!", is_finished=True)
            
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            print(f"Sector update error: {error_details}")
            _set_progress(cache_key, 100, f"Error: {e}", is_finished=True)

    t = threading.Thread(target=_run_task)
    t.daemon = True
    t.start()
    
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'status': 'success', 'message': 'Sector update started.'})
        
    messages.success(request, "Sector update started in background.")
    return redirect("insight:sector_leaders")



def earnings_v2(request):
    """
    AI Earnings Analysis 2.0
    Uses FMP 'sec-filings-8k' info + Scrapes SEC Link + Gemini Analysis.
    Distinguishes actual Earnings Report (Item 2.02) using Earnings Calendar.
    """
    symbol = request.GET.get('symbol', '').upper().strip()
    context = {'symbol': symbol}
    
    if symbol:
        API_KEY = os.getenv("FMP_API_KEY")
        if not API_KEY:
            context['error'] = "API Key not found."
            return render(request, "insight/earnings_v2.html", context)
            
        today = datetime.now()
        
        # 1. Fetch Earnings Calendar (To find the latest PAST earnings date)
        # We fetch a few records because the top one might be a future estimate.
        cal_url = f"https://financialmodelingprep.com/api/v3/historical/earning_calendar/{symbol}?limit=10&apikey={API_KEY}"
        earnings_date_str = None
        
        try:
            cal_resp = requests.get(cal_url, timeout=5)
            cal_data = cal_resp.json()
            if isinstance(cal_data, list):
                # Sort by date desc just in case
                cal_data.sort(key=lambda x: x.get('date', ''), reverse=True)
                
                # Find the first date that is <= Today
                today_date = datetime.now().date()
                for event in cal_data:
                    d_str = event.get('date')
                    if d_str:
                        d_obj = datetime.strptime(d_str, "%Y-%m-%d").date()
                        if d_obj <= today_date:
                            earnings_date_str = d_str
                            break
        except Exception as e:
            print(f"Calendar fetch failed: {e}")

        # 2. Fetch 8-K Filings
        # Adjust 'from' date to be slightly *before* the confirmed earnings date needed, 
        # to ensure we capture it even if it was > 90 days ago.
        # Fallback to 90 days if no earnings date found.
        target_date_obj = datetime.strptime(earnings_date_str, "%Y-%m-%d").date() if earnings_date_str else (today - timedelta(days=90)).date()
        search_from_date = target_date_obj - timedelta(days=5) 
        
        from_str = search_from_date.strftime("%Y-%m-%d")
        to_str = today.strftime("%Y-%m-%d")

        url = f"https://financialmodelingprep.com/stable/sec-filings-8k?from={from_str}&to={to_str}&page=0&limit=40&symbol={symbol}&apikey={API_KEY}"
        
        try:
            resp = requests.get(url, timeout=10)
            data = resp.json()
            
            if isinstance(data, list) and len(data) > 0:
                data.sort(key=lambda x: x.get('filingDate', ''), reverse=True)
                
                target_filing = None
                other_filings = []
                
                if earnings_date_str:
                    e_date = datetime.strptime(earnings_date_str, "%Y-%m-%d").date()
                    
                    # Logic: 
                    # 1. Any filing NEWER than the earnings window is "Other" (e.g. later contract).
                    # 2. The filing IN the earnings window is "Target".
                    # 3. Any filing OLDER is ignored or "Other".
                    
                    for f in data:
                        f_date_str = f.get('filingDate', '').split(' ')[0]
                        f_date = datetime.strptime(f_date_str, "%Y-%m-%d").date()
                        diff = (f_date - e_date).days
                        
                        # Check match (0 to +4 days from Earnings Date)
                        if 0 <= diff <= 4:
                            if not target_filing:
                                target_filing = f
                            else:
                                # If we already have target, this might be a second filing same day? 
                                # usually latest is better, loop is desc.
                                other_filings.append(f)
                        elif f_date > e_date:
                            # Newer filing -> Other List
                            other_filings.append(f)
                        else:
                             # Older filing -> Other List
                             other_filings.append(f)
                else:
                    target_filing = data[0]
                    other_filings = data[1:]

                # Context Assignment
                # If we found a strict earnings match, show it.
                # If not, fall back to the absolute latest but mark unconfirmed.
                if target_filing:
                    context['filing'] = target_filing
                    context['is_confirmed_earnings'] = True if earnings_date_str else False
                else:
                    context['filing'] = data[0] # Fallback to latest available
                    context['is_confirmed_earnings'] = False
                    # Remove the fallback one from others list if it was placed there (if logic was weird)
                    if data[0] in other_filings:
                        other_filings.remove(data[0])

                context['other_filings'] = other_filings[:15]
                
                # 3. Fetch Text & AI Analyze (Only for the main target)
                main_filing = context['filing']
                final_link = main_filing.get('finalLink') or main_filing.get('link')
                raw_text = ""
                
                if final_link:
                    try:
                        sec_headers = {
                            "User-Agent": "VestiqResearch jiwanlee123@gmail.com",
                            "Host": "www.sec.gov"
                        }
                        sec_resp = requests.get(final_link, headers=sec_headers, timeout=15)
                        if sec_resp.status_code == 200:
                            soup = BeautifulSoup(sec_resp.content, "html.parser")
                            for script in soup(["script", "style"]):
                                script.decompose()
                            raw_text = soup.get_text(separator="\n")
                            raw_text = "\n".join([line.strip() for line in raw_text.splitlines() if line.strip()])
                            raw_text = raw_text[:60000]
                    except Exception as e:
                        print(f"Error fetching SEC text: {e}")

                # TEMPORARY: Gemini Disabled requested by user.
                # Just return raw text for verification.
                if raw_text:
                    context['ai_report'] = (
                        "### [System] AI Analysis Temporarily Disabled for Testing\n\n"
                        "**Raw 8-K Extraction Preview:**\n\n"
                        "```\n" + raw_text[:4000] + "\n```\n\n"
                        "Please check the 'View Full Source' link for the complete document."
                    )
                else:
                    context['ai_report'] = "Could not retrieve filing text for analysis. Please view the full source link."

                # if raw_text and settings.GEMINI_ENABLED:
                #     try:
                #         client = _client()
                #         if client:
                #             doc_type = "Earnings Report" if context.get('is_confirmed_earnings') else "8-K Filing"
                #             prompt = (
                #                 f"You are a professional financial analyst. Analyze the following {doc_type} for {symbol}.\n"
                #                 f"Reporting Date: {main_filing.get('filingDate')}\n"
                #                 f"Confirmed Earnings Date: {earnings_date_str if earnings_date_str else 'Unconfirmed'}\n\n"
                #                 f"Filing Content:\n{raw_text}\n\n"
                #                 "Instructions:\n"
                #                 "1. Provide a 'Professional & Pretty' report.\n"
                #                 f"2. Clearly state: 'This is the Earnings Report for the period ending [Date]' if applicable.\n"
                #                 "3. Use Markdown (## Headers, **Bold**, bullets).\n"
                #                 "4. Structure: 'Executive Summary', 'Key Material Events', 'Financial Impact', 'Analyst Verdict'.\n"
                #             )
                #             response = client.models.generate_content(model=MODEL, contents=prompt)
                #             context['ai_report'] = getattr(response, "text", "AI Generation Failed.")
                #         else:
                #             context['ai_report'] = "Gemini Client Error."
                #     except Exception as e:
                #         context['ai_report'] = f"AI Error: {e}"
                # else:
                #    context['ai_report'] = "Could not retrieve filing text for analysis. Please view the full source link."

            else:
                context['error'] = f"No 8-K filings found for {symbol} around {from_str}."
                
        except Exception as e:
            context['error'] = f"Error fetching data: {e}"
            
    return render(request, "insight/earnings_v2.html", context)


# -----------------------------
# Earnings Calendar (Professional UI)
# -----------------------------
from .models import EarningsCalendar

def fetch_earnings_calendar(from_date: str, to_date: str, force: bool = False):
    """
    Fetches earnings calendar from FMP and saves to DB.
    force=True: Deletes existing data for the range before fetching (Refresh).
    """
    api_key = os.getenv("FMP_API_KEY")
    if not api_key:
        print("API Key missing")
        return

    # 1. Truncate if forced (Manual Refresh)
    # 1. Truncate if forced (Manual Refresh)
    if force:
        print(f"Force Refresh: Clearing ALL Earnings data (Full Truncate)")
        EarningsCalendar.objects.all().delete()

    url = f"https://financialmodelingprep.com/stable/earnings-calendar?from={from_date}&to={to_date}&apikey={api_key}"
    print(f"Fetching Earnings Calendar: {url}")
    
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        
        if isinstance(data, list):
            for item in data:
                symbol = item.get('symbol')
                date_str = item.get('date')
                if not symbol or not date_str:
                    continue
                # 2. Filter Nulls (Smart Logic)
                # Past (< Today): Must have Actuals.
                # Future (>= Today): Must have Estimates.
                
                # We need "Today" in EST (market time) or UTC? 
                # Ideally Market Time. Let's use simple local date for now, or timezone.now().date()
                today = timezone.now().date()
                try:
                    e_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                except:
                    continue

                eps_est = item.get('epsEstimated')
                rev_est = item.get('revenueEstimated')
                eps_act = item.get('epsActual')
                rev_act = item.get('revenueActual')

                # STRICT LOGIC (User Request):
                # "If ANY null in expected values, do not save."
                # 1. Future (> Today): Must have Estimates.
                # 2. Past/Today (<= Today): Must have ACTUALS. 
                #    (This effectively hides pending earnings for Today until they report.)

                if e_date > today:
                    # Future: Strict Estimates Check
                    if eps_est is None or rev_est is None:
                        continue
                else:
                    # Past or Today: Ultra-Strict Check
                    # Must have ACTUALS (to show results) AND ESTIMATES (to show Beat/Miss).
                    # If ANY of the 4 values is missing, we discard it.
                    if (eps_act is None or rev_act is None) or (eps_est is None or rev_est is None):
                        continue

                EarningsCalendar.objects.update_or_create(
                    symbol=symbol,
                    date=date_str,
                    defaults={
                        'eps_actual': eps_act,
                        'eps_estimated': eps_est,
                        'revenue_actual': rev_act,
                        'revenue_estimated': rev_est,
                        'time': item.get('time'),
                        'updated_at': timezone.now()
                    }
                )
    except Exception as e:
        print(f"Error fetching earnings calendar: {e}")

def earnings_calendar_view(request):
    """
    Displays Earnings Calendar.
    Sorted by Market Cap.
    """
    today = datetime.now().date()
    
    # Simple default: Today to Today + 14 days (Focus on Upcoming + Today's Results)
    # If today is earnings day, results might not be out yet (BMO yes, AMC no)
    default_start = today
    default_end = today + timedelta(days=14)
    
    start_date_str = request.GET.get('start_date', default_start.strftime('%Y-%m-%d'))
    end_date_str = request.GET.get('end_date', default_end.strftime('%Y-%m-%d'))
    
    # Check for Manual Refresh
    refresh = request.GET.get('refresh', 'false')
    
    if refresh == 'true':
        fetch_earnings_calendar(start_date_str, end_date_str, force=True)
    
    # Query DB
    earnings = EarningsCalendar.objects.filter(
        date__range=[start_date_str, end_date_str]
    ).order_by('date', 'symbol') # Initial sort
    
    # --- Data Injection (Rich Dashboard Data) ---
    from updatedata.models import FundamentalData, Ticker, PriceHistory
    
    # 1. Get List of Symbols
    symbols = [e.symbol for e in earnings]
    
    # 2. Fetch Ticker Names & Meta (Sector/Industry + Logo)
    ticker_qs = Ticker.objects.filter(symbol__in=symbols).values('symbol', 'name', 'sector', 'industry', 'image')
    meta_map = {t['symbol']: t for t in ticker_qs}

    # 3. Fetch Fundamental Data (Market Cap, PE Ratio, PB Ratio)
    # We want the LATEST available data irrespective of earnings date for "Current Stats"
    fds = FundamentalData.objects.filter(symbol__symbol__in=symbols).values(
        'symbol__symbol', 'market_cap', 'pe_ratio', 'pb_ratio'
    ).order_by('symbol__symbol', '-date')
    
    fd_map = {}
    for fd in fds:
        sym = fd['symbol__symbol']
        if sym not in fd_map:
            fd_map[sym] = fd
            
    # 4. Inject into Earnings Objects
    for e in earnings:
        # A. Meta
        meta = meta_map.get(e.symbol, {})
        e.name = meta.get('name', "")
        e.sector = meta.get('sector', "")
        e.industry = meta.get('industry', "")
        e.logo = meta.get('image', "")
        
        # B. Fundamentals
        fd = fd_map.get(e.symbol, {})
        e.market_cap = fd.get('market_cap', 0)
        e.pe_ratio = fd.get('pe_ratio', None)
        e.pb_ratio = fd.get('pb_ratio', None)
        
        # Init placeholder for chart
        e.sparkline = []

    # 5. Group by Date & Sort
    earnings_dict = {}
    for e in earnings:
        d_str = e.date.strftime('%Y-%m-%d')
        if d_str not in earnings_dict:
            earnings_dict[d_str] = []
        earnings_dict[d_str].append(e)
        
    for day_list in earnings_dict.values():
        day_list.sort(key=lambda x: x.market_cap or 0, reverse=True)

    # 6. Fetch Price History (Sparklines) for TOP companies only
    # Strategy: For each day, take top 3 companies. Fetch last 14 days history.
    top_symbols = []
    for day_list in earnings_dict.values():
        # Top 5 per day to be safe for Hero section
        for e in day_list[:5]:
            top_symbols.append(e.symbol)
            
    # Fetch History for these symbols
    # Limit to last 30 days to ensure coverage
    history_start = today - timedelta(days=20)
    prices = PriceHistory.objects.filter(
        symbol__symbol__in=top_symbols,
        date__gte=history_start
    ).values('symbol__symbol', 'date', 'close').order_by('symbol__symbol', 'date')
    
    # Build Price Map: { 'AAPL': [150, 151, ...] }
    price_map = {}
    for p in prices:
        sym = p['symbol__symbol']
        if sym not in price_map:
            price_map[sym] = []
        price_map[sym].append(p['close'])
        
    # Inject Sparklines
    for e in earnings:
        if e.symbol in price_map:
            # Take last 10 points for a clean sparkline
            e.sparkline = price_map[e.symbol][-10:]

    
    # 6. Generate Full Date Range (for Calendar Grid)
    s_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    e_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
    
    calendar_data = [] # List of {'date_obj': date, 'data': [...]}
    current = s_date
    while current <= e_date:
        d_str = current.strftime('%Y-%m-%d')
        day_data = earnings_dict.get(d_str, [])
        
        if 'start_date' not in request.GET:
             # Initial Load Logic: Filter "Upcoming" (Future) dates
             # Keep only "High Quality" -> Market Cap > 10B (10,000,000,000) AND Logo exists
             if current > datetime.now().date():
                 filtered_day = []
                 for e in day_data:
                     # Check Market Cap (e.market_cap is float or None)
                     mcap = e.market_cap or 0
                     has_logo = True if e.logo else False
                     
                     if mcap > 10_000_000_000 and has_logo:
                         filtered_day.append(e)
                 day_data = filtered_day

        calendar_data.append({
            'date': current,
            'date_str': d_str,
            'day': current.day,
            'weekday': current.strftime('%a'),
            'earnings': day_data
        })
        current += timedelta(days=1)
        
    context = {
        'calendar_data': calendar_data,
        'start_date': start_date_str,
        'end_date': end_date_str,
    }
    
    return render(request, "insight/earnings_calendar.html", context)


# -----------------------------
# API: Sector Constituent Details
# -----------------------------
def api_sector_details(request, sector_name):
    """
    Returns full list of stocks for a given sector name (Standard or Custom Theme).
    JSON: [{symbol, name, price, change, market_cap}, ...]
    """
    from .services import themes
    from django.http import JsonResponse
    from django.db.models import F
    
    # 1. Determine Ticker Set
    if sector_name in themes:
        # Custom Theme (Exact Match)
        symbols = themes[sector_name]
        qs = Ticker.objects.filter(symbol__in=symbols)
    else:
        # Standard Sector (Try Exact Match first)
        qs = Ticker.objects.filter(sector=sector_name)
        if not qs.exists():
            # Fallback for mapped names (e.g. Technology -> Information Technology)
            # Simple fuzzy lookup
            qs = Ticker.objects.filter(sector__icontains=sector_name)
    
    if not qs.exists():
        return JsonResponse({'error': 'Sector not found'}, status=404)

    # 2. Annotate Latest Data
    # Reuse Subquery logic for efficiency
    latest_fund = FundamentalData.objects.filter(symbol=OuterRef('pk')).order_by('-date')
    latest_price = PriceHistory.objects.filter(symbol=OuterRef('pk')).order_by('-date')
    
    qs = qs.annotate(
        market_cap=Subquery(latest_fund.values('market_cap')[:1]),
        price=Subquery(latest_price.values('close')[:1]),
        change_percent=Subquery(latest_price.values('change_percent')[:1]),
        company_name=F('name')
    )
    
    # 3. Serialize
    data = []
    # Fetch all at once
    rows = qs.values('symbol', 'company_name', 'price', 'change_percent', 'market_cap')
    
    for row in rows:
        mcap = row['market_cap'] if row['market_cap'] else 0
        price = row['price'] if row['price'] else 0
        change = row['change_percent'] if row['change_percent'] else 0
        
        data.append({
            'symbol': row['symbol'],
            'name': row['company_name'],
            'price': float(price),
            'change': float(change),
            'market_cap': float(mcap)
        })
        
    # Sort by Market Cap Descending
    data.sort(key=lambda x: x['market_cap'], reverse=True)
    
    return JsonResponse({'sector': sector_name, 'constituents': data})
