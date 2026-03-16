import logging
import time
import requests
import datetime
from django.conf import settings
from django.utils import timezone
from .models import SectorPerformance
from urllib.parse import quote

logger = logging.getLogger('insight')
# --- Custom Themes Definition ---
# Manually define themes by Symbol or Keyword
themes = {
    "Quantum": ["IONQ", "RGTI", "QBTS", "QUBT", "ARQQ", "QMCO", "IBM", "GOOGL"],
    "Aerospace & Defense": ["GE", "RTX", "BA", "LMT", "NOC", "GD", "LHX", "TDG", "HEI", "HII", "TXT", "AVAV", "RKLB"],
    
    # User Requested Themes
    "Bitcoin & Crypto": ["MSTR", "COIN", "RIOT", "MARA", "CLSK", "BTBT", "HUT", "BITF", "HOOD", "SQ", "BMNR"],
    
    # Additional Suggested Themes
    "AI Semiconductor / Hardware": ["NVDA", "AMD", "AVGO", "MRVL", "ARM", "MU", "APH", "ALAB", "CRDO", "ASML", "AMAT", "LRCX", "KLAC", "CDNS", "TSM", "INTC", "NXPI", "AMBA", "LSCC", "QCOM", "SNPS", "TXN"],
    "AI Infrastructure / Datacenter": ["ANET", "CSCO", "CLS", "FN", "VRT", "MOD", "TT", "CARR", "JCI", "ETN", "GEV", "HUBB", "PWR", "POWL", "EME", "CEG", "VST", "NEE"],
    "AI Cloud": ["MSFT", "GOOGL", "AMZN", "ORCL", "CRWV", "IREN", "IBM", "NBIS", "SNOW", "NET"],
    "AI Software": ["PLTR", "NOW", "CRM", "ADBE", "INTU", "PATH", "AI", "APP", "SOUN", "GOOGL", "MSFT", "TSLA", "AMZN", "META", "RDDT", "UPST", "TEM", "RXRX"],
    "AI Physical & Robotics": ["TER", "ROK", "ABBNY", "ISRG", "BSX", "DE", "ZBRA", "SERV", "RR", "SYM", "TSLA", "GXO", "AVAV", "XPEV"],
    "MEGA 7": ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "META"],
    "OTT": ["NFLX", "DIS", "WBD", "PARA", "ROKU", "CMCSA", "FUBO", "SPOT"],
    "Clean Energy & EV": ["TSLA", "RIVN", "LCID", "NIO", "XPEV", "ENPH", "SEDG", "FSLR", "RUN", "CHPT", "PLUG"],
    "Cybersecurity": ["CRWD", "PANW", "ZS", "FTNT", "S", "OKTA", "NET", "TENB", "CYBR", "RPD"]
}

def update_daily_sector_performance(target_date=None):
    """
    Updates SectorPerformance model by aggregating LOCALLY stored data.
    Source: Ticker, FundamentalData, PriceHistory.
    Triggered daily after market close.
    """
    from updatedata.models import Ticker, FundamentalData, PriceHistory
    from django.db.models import Subquery, OuterRef, F, FloatField, ExpressionWrapper, Q
    import pandas as pd
    import numpy as np
    
    
    # 0. Determine Date
    if target_date is None:
        latest_ph = PriceHistory.objects.order_by('-date').first()
        if latest_ph:
            target_date = latest_ph.date
        else:
            target_date = datetime.date.today()
        
    logger.info(f"[Sector Leaders] Starting Update. Target Date: {target_date} (Wall: {datetime.date.today()})")
    
    # Init Log
    log_file = "logs/sector.log"
    with open(log_file, "a") as f:
        f.write(f"[{datetime.datetime.now()}] Starting Sector Leaders Update. Target Date: {target_date}\n")

    # Delete existing data for this date to prevent duplicates
    deleted_today_count, _ = SectorPerformance.objects.filter(date=target_date).delete()
    # [Fix] Explicitly delete old deprecated sector names (legacy cleanup)
    SectorPerformance.objects.filter(date=target_date, sector="AI & Robotics").delete()
    SectorPerformance.objects.filter(date=target_date, sector="Artificial Intelligence").delete()
    
    if deleted_today_count > 0:
        logger.info(f"[Sector Leaders] Deleted {deleted_today_count} existing records for {target_date}")
    
    # Auto-cleanup: Keep only 2 weeks (14 days) of data (ONLY if running for 'latest', skip for backfill safety)
    if target_date >= datetime.date.today() - datetime.timedelta(days=1):
         two_weeks_ago = target_date - datetime.timedelta(days=14)
         deleted_old_count, _ = SectorPerformance.objects.filter(date__lt=two_weeks_ago).delete()
         if deleted_old_count > 0:
             logger.info(f"[Sector Leaders] Deleted {deleted_old_count} old records (before {two_weeks_ago})")

    # [CRITICAL] Check if market data exists for this day
    # If it's a weekend or holiday, PriceHistory will be empty.
    # We must NOT create a 0.00% record, otherwise the dashboard will show it as 'Latest'.
    # [CRITICAL] Check if market data exists for this day
    # If it's a weekend or holiday, PriceHistory will be empty.
    # We must NOT create a 0.00% record, otherwise the dashboard will show it as 'Latest'.
    # [Fix] Use a threshold (e.g. 20) instead of exists() to avoid single-ticker glitches (e.g., one OTC stock updating early)
    ph_count = PriceHistory.objects.filter(date=target_date).count()
    if ph_count < 20:
        logger.info(f"[Sector Leaders] Insufficient PriceHistory found for {target_date} (Count: {ph_count}). Skipping to prevent empty data.")
        with open(log_file, "a") as f:
            f.write(f"[{datetime.datetime.now()}] Skipped {target_date}: Insufficient PriceHistory ({ph_count}).\n")
        return



    
    all_theme_symbols = []
    for syms in themes.values():
        all_theme_symbols.extend(syms)

    # 1. Fetch Active Tickers with Sector OR in Themes
    tickers = Ticker.objects.filter(
        Q(sector__isnull=False) & ~Q(sector="") | Q(symbol__in=all_theme_symbols)
    ).distinct()
    
    # 2. Annotate with Market Cap & Change % SPECIFIC to target_date
    if target_date:
        # Strict Match for Price History on that date
        daily_price = PriceHistory.objects.filter(symbol=OuterRef('pk'), date=target_date)
        # Latest Fundamental Data (Relaxed: Use ANY latest available, even if future relative to target, to ensure backfill works)
        latest_fund = FundamentalData.objects.filter(symbol=OuterRef('pk')).order_by('-date')
    else:
        # Fallback (Should utilize target_date logic above, but safety net)
        daily_price = PriceHistory.objects.filter(symbol=OuterRef('pk')).order_by('-date')
        latest_fund = FundamentalData.objects.filter(symbol=OuterRef('pk')).order_by('-date')
    
    qs = tickers.annotate(
        market_cap=Subquery(latest_fund.values('market_cap')[:1]),
        price=Subquery(daily_price.values('close')[:1]),
        change_pct=Subquery(daily_price.values('change_percent')[:1]),
        company_name=F('name')
    ).values('symbol', 'company_name', 'sector', 'market_cap', 'price', 'change_pct')
    
    # Convert to DataFrame for easier grouping/sorting
    df = pd.DataFrame.from_records(qs)
    
    if df.empty:
        logger.warning("[Sector Leaders] No local data found. Skipping.")
        return

    # Data Type Conversions & Cleaning
    df['market_cap'] = pd.to_numeric(df['market_cap'], errors='coerce').fillna(0)
    df['change_pct'] = pd.to_numeric(df['change_pct'], errors='coerce').fillna(0)
    df['price'] = pd.to_numeric(df['price'], errors='coerce').fillna(0)
    
    # Filter garbage (optional: ignore tiny caps?)
    df = df[df['market_cap'] > 0]
    
    # 3. Group by Sector
    grouped = [group for _, group in df.groupby('sector') if group['sector'].iloc[0]] # Filter out empty sector string if any
    
    
    for theme_name, symbols in themes.items():
        # Filter df for these symbols
        theme_df = df[df['symbol'].isin(symbols)].copy()
        if not theme_df.empty:
            # Fake a 'group' tuple structure or just process it manually
            # Let's attach metadata so the loop below handles it
            theme_df['sector'] = theme_name # Override sector for grouping
            grouped.append(theme_df)


    # 4. Fetch Sector PE from FMP API (User Request)
    fmp_pe_map = {}
    try:
        api_key = settings.FMP_API_KEY
        if api_key:
            # Fetch both NASDAQ and NYSE to ensure coverage
            for exchange in ['NASDAQ', 'NYSE']:
                url = f"https://financialmodelingprep.com/stable/sector-pe-snapshot?date={target_date}&exchange={exchange}&apikey={api_key}"
                try:
                    response = requests.get(url, timeout=10)
                    if response.status_code == 200:
                        pe_data = response.json()
                        for item in pe_data:
                            sector = item.get('sector')
                            pe = item.get('pe')
                            # stored per sector (overwrite if exists, maybe average ideally but overwrite is okay for now)
                            if sector and pe:
                                fmp_pe_map[sector] = float(pe) 
                        logger.info(f"[Sector Leaders] Fetched PE data for {len(pe_data)} sectors from {exchange}.")
                    else:
                        logger.error(f"[Sector Leaders] Failed to fetch PE from {exchange}: {response.text}")
                except Exception as e:
                    logger.error(f"[Sector Leaders] Error fetching {exchange}: {e}")

            logger.info(f"[Sector Leaders] Final PE Map Keys: {list(fmp_pe_map.keys())}")

    except Exception as e:
        logger.error(f"[Sector Leaders] Error fetching FMP PE data: {e}")

    # 5. Save to DB with PE Ratio
    updated_count = 0
    
    for group in grouped:
        if group.empty: continue
        
    for group in grouped:
        if group.empty: continue
        
        # Get sector name from the first row (we overrode it for themes)
        sector_name = group['sector'].iloc[0]
        
        try:
            # A. Calculate Sector Performance
            total_cap = group['market_cap'].sum()
            if total_cap > 0:
                group['weighted_change'] = group['change_pct'] * (group['market_cap'] / total_cap)
                sector_change = group['weighted_change'].sum()
            else:
                sector_change = group['change_pct'].mean()
            
            # B. Identify Leaders
            leaders_df = group.sort_values(by='market_cap', ascending=False).head(5)
            leaders_data = []
            for _, row in leaders_df.iterrows():
                leaders_data.append({
                    'symbol': row['symbol'],
                    'company_name': row['company_name'],
                    'price': float(row['price']),
                    'change': float(row['change_pct']),
                    'mkt_cap': float(row['market_cap'])
                })
                
            # C. Identify Top Gainers
            gainers_df = group.sort_values(by='change_pct', ascending=False).head(5)
            gainers_data = []
            for _, row in gainers_df.iterrows():
                gainers_data.append({
                    'symbol': row['symbol'],
                    'company_name': row['company_name'],
                    'price': float(row['price']),
                    'change': float(row['change_pct'])
                })

            # D. Get PE Ratio (Map FMP Sector -> Local GICS Sector if possible)
            # FMP Sectors: "Technology", "Financial Services", etc.
            # Local Sectors: "Information Technology", "Financials", etc. (GICS)
            # We try direct match first, then mapping if needed. This step might need refinement based on actual data
            # For now, simplistic mapping or direct retrieval.
            # WARNING: FMP uses different names than GICS often.
            
            sector_pe = fmp_pe_map.get(sector_name)

            # E. Custom Theme PE Calculation (if not in FMP map)
            if sector_pe is None and sector_name in themes.keys():
                # For custom themes like "Quantum", calculate median PE of components
                # We need PE from FundamentalData for these symbols
                theme_symbols = themes[sector_name]
                # We already have data in 'df' but we need PE. 
                # Let's simple fetch PE from FundamentalData for these symbols
                from updatedata.models import FundamentalData
                pe_values = FundamentalData.objects.filter(
                    symbol__symbol__in=theme_symbols, 
                    pe_ratio__isnull=False
                ).values_list('pe_ratio', flat=True)

                if pe_values:
                    # Filter out negative or extreme PEs if desired, or just take median
                    valid_pes = [p for p in pe_values if p > 0]
                    if not valid_pes:
                        valid_pes = list(pe_values)
                    
                    if valid_pes:
                        sector_pe = float(np.median(valid_pes))

            # F. Mapping for standard sectors
            if sector_pe is None:
                mapping = {
                    "Information Technology": "Technology",
                    "Financials": "Financial Services",
                    "Consumer Discretionary": "Consumer Cyclical",
                    "Consumer Staples": "Consumer Defensive",
                    "Health Care": "Healthcare",
                    "Materials": "Basic Materials",
                    "Communication Services": "Communication Services",
                    "Communication": "Communication Services", # Fix for 'Communication' vs 'Communication Services'
                }
                mapped_name = mapping.get(sector_name)
                if mapped_name:
                    sector_pe = fmp_pe_map.get(mapped_name)
                
                # If still None, try to derive from components like we did for themes
                if sector_pe is None and not group.empty:
                     # Try to get PE from FundamentalData for top 10 components
                     top_symbols = group.sort_values(by='market_cap', ascending=False).head(10)['symbol'].tolist()
                     from updatedata.models import FundamentalData
                     pe_values = FundamentalData.objects.filter(
                        symbol__symbol__in=top_symbols, 
                        pe_ratio__isnull=False
                     ).values_list('pe_ratio', flat=True)
                     if pe_values:
                        valid_pes = [p for p in pe_values if p > 0]
                        if not valid_pes:
                            valid_pes = list(pe_values)
                        
                        if valid_pes:
                            sector_pe = float(np.median(valid_pes))

            
            # Save to DB
            SectorPerformance.objects.update_or_create(
                date=target_date,
                sector=str(sector_name),
                defaults={
                    'change_percent': round(sector_change, 2),
                    'rank': 0, 
                    'pe_ratio': sector_pe, # Can be None
                    'leaders_data': leaders_data,
                    'gainers_data': gainers_data,
                    'updated_at': timezone.now()
                }
            )
            updated_count += 1
            
        except Exception as e:
            logger.error(f"[Sector Leaders] Error processing {sector_name}: {e}")
            continue

    # 6. Update Ranks based on Performance
    todays_sectors = SectorPerformance.objects.filter(date=target_date).order_by('-change_percent')
    for rank, obj in enumerate(todays_sectors, 1):
        obj.rank = rank
        obj.save(update_fields=['rank'])

    logger.info(f"[Sector Leaders] Successfully updated {updated_count} sectors from Local DB.")
    with open("logs/sector.log", "a") as f:
        f.write(f"[{datetime.datetime.now()}] Completed. Updated {updated_count} sectors.\n")
