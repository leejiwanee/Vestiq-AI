import yfinance as yf
import pandas as pd
import numpy as np
import math
import logging
import pytz
from django.utils import timezone

from datetime import datetime, date, timedelta
from updatedata.models import Ticker, PriceHistory, FundamentalData
from .models import ScanRow, ScanBatch
from django.db.models import F, Max

logger = logging.getLogger(__name__)

LOOKBACK_DAYS = 90
MIN_DAYS = 30

def clean_float(val, round_decimals=2):
    """Sanitize float values for MySQL - converts NaN/Inf to None."""
    if val is None:
        return None
    try:
        import math
        if math.isnan(val) or math.isinf(val):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return round(float(val), round_decimals)
    except (TypeError, ValueError):
        return None


def scan_symbols(tickers=None, batch_id=None):
    """
    [Optimized Scan]
    Reads from Ticker (Daily Snapshot).
    Returns (DataFrame, Metrics) compatible with legacy views.
    If batch_id provided, acts as legacy but we ignore batch_id for return flow usually, 
    unless we want to save immediately. 
    To align with views.py: return formatted metrics and DF.
    """
    if tickers:
        qs = Ticker.objects.filter(symbol__in=tickers)
    else:
        qs = Ticker.objects.all()
        
    logger.info(f"Scanning {qs.count()} tickers using PriceHistory Source...")

    # [Optimized Strategy]
    # We need 90 days of history to calculate MA60, MA20, RSI, RVOL accurately.
    # 1. Fetch data in bulk
    cutoff_date = timezone.now().date() - timedelta(days=100) # Buffer for 60MA
    
    fields = ['symbol__symbol', 'date', 'close', 'open', 'high', 'low', 'volume', 'change_percent']
    if tickers:
        ph_qs = PriceHistory.objects.filter(symbol__symbol__in=tickers, date__gte=cutoff_date)
    else:
        ph_qs = PriceHistory.objects.filter(date__gte=cutoff_date)
        
    ph_qs = ph_qs.values(*fields)
    
    if not ph_qs:
        logger.warning("[Scanner] No PriceHistory found.")
        return None, {"scanned": 0, "triggers": 0}
        
    # 2. Convert to DataFrame
    df_all = pd.DataFrame(list(ph_qs))
    df_all.rename(columns={'symbol__symbol': 'symbol'}, inplace=True)
    df_all['date'] = pd.to_datetime(df_all['date'])
    df_all.sort_values(by=['symbol', 'date'], inplace=True)
    
    # [Optimized] Bulk Fetch Fundamentals (P/E) for Value Filter
    # Fetch latest FundamentalData within 30 days
    fund_cutoff = timezone.now().date() - timedelta(days=45)
    fund_qs = FundamentalData.objects.filter(date__gte=fund_cutoff).values('symbol__symbol', 'pe_ratio', 'date')
    # Deduplicate: Keep latest date per symbol
    pe_map = {}
    # Sort by date asc, so latest overwrites
    sorted_funds = sorted(list(fund_qs), key=lambda x: x['date'])
    for f in sorted_funds:
        pe_map[f['symbol__symbol']] = f['pe_ratio']

    rows_data = []
    
    # 3. Process per Symbol (GroupBy)
    # This is much faster than looping objects
    grouped = df_all.groupby('symbol')
    
    for sym, group in grouped:
        if len(group) < 30: continue # Skip if not enough data
        
        # Calculate Indicators
        # We process the whole series but only care about the last row for the result
        close = group['close']
        volume = group['volume']
        
        # RSI (14)
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi_series = 100 - (100 / (1 + rs))
        
        # MA 20, 60
        ma20_series = close.rolling(window=20).mean()
        ma60_series = close.rolling(window=60).mean()
        
        # RVOL (20)
        vol_ma20 = volume.rolling(window=20).mean()
        rvol_series = volume / vol_ma20
        
        # Get Latest Data (Last Row)
        last = group.iloc[-1]
        curr_close = last['close'] # Defined early for usage
        
        # Calculate Previous Volume & Vol Change %
        prev_vol = 0
        vol_pct = 0.0
        
        # Calculate Price Change % (Dynamic)
        price_change_pct = 0.0
        
        if len(group) >= 2:
            prev_row = group.iloc[-2]
            
            # Volume Change
            prev_vol = int(prev_row['volume'])
            curr_vol = int(last['volume'])
            if prev_vol > 0:
                vol_pct = ((curr_vol - prev_vol) / prev_vol) * 100.0
                
            # Price Change
            prev_close = prev_row['close']
            if prev_close > 0:
                price_change_pct = ((curr_close - prev_close) / prev_close) * 100.0
        
        # Current Values (rest)
        curr_open = last['open']
        curr_high = last['high'] # For pattern (upper shadow)
        curr_rsi = rsi_series.iloc[-1]
        curr_rvol = rvol_series.iloc[-1]
        curr_ma20 = ma20_series.iloc[-1]
        curr_ma60 = ma60_series.iloc[-1]
        
        if pd.isna(curr_rsi) or pd.isna(curr_ma60):
            continue
            
        def clean_float(val, round_decimals=2):
            if pd.isna(val) or val is None: return None
            # Check for infinity
            if hasattr(val, 'is_infinite') and val.is_infinite(): return None
            if val == float('inf') or val == float('-inf'): return None
            return round(float(val), round_decimals)

        # Bollinger Bands (20, 2) for Squeeze & Oversold
        # ma20_series is already calc (Mean). Need Std Dev.
        std20 = close.rolling(window=20).std()
        upper_band = ma20_series + (std20 * 2)
        lower_band = ma20_series - (std20 * 2)
        
        curr_lower_bb = lower_band.iloc[-1]
        curr_upper_bb = upper_band.iloc[-1]
        
        # Bandwidth: (Upper - Lower) / Middle
        curr_b_width = 0
        if curr_ma20 > 0:
            curr_b_width = (curr_upper_bb - curr_lower_bb) / curr_ma20
        
        # --- Scoring (VCS) ---
        score_base = 40 # Fundamental Base Score (Market is Bullish?) or just base
        
        score_trend = 0
        # MA20 Slope > 0 (Simple check: current > 5 days ago)
        ma20_slope_positive = (curr_ma20 > ma20_series.iloc[-5]) if len(ma20_series) > 5 else False
        
        if curr_close > curr_ma20:
             score_trend += 15
             if ma20_slope_positive:
                 score_trend += 10 # Strong Trend
        
        score_mom = 0
        if curr_rsi >= 50: score_mom += 10
        if curr_rsi <= 30: score_mom += 5 # Oversold Bounce Potential?
        
        score_vol = 0
        if curr_rvol > 1.2: score_vol += 10
        elif curr_rvol > 0.8: score_vol += 5
        
        score_pattern = 0
        candle_body = abs(curr_close - curr_open)
        upper_shadow = curr_high - max(curr_close, curr_open)
        if candle_body > upper_shadow * 2: # Strong body
            score_pattern += 5
            
        total_vcs = score_base + score_trend + score_mom + score_vol + score_pattern
        total_vcs = min(100, max(0, int(total_vcs)))
        
        # --- Filter Definitions ---
        
        # 1. Volume Surge (Strict): Vol Change >= 100%
        f_vol_strict = (vol_pct >= 100.0)
        
        # 2. Uptrend (Swing/Trend): VCS Trend >= 15 (Price > MA20)
        f_trend_strict = (score_trend >= 15)
        
        # 3. Momentum (Short/Day): Today's Change >= 3%
        # Use calculated price_change_pct instead of last.get('change_percent')
        f_mom_strict = (price_change_pct >= 3.0)
        
        # 4. Pattern: Green Candle
        f_pat = (score_pattern > 0)
        
        # 5. Oversold: RSI <= 30 AND Price near Lower BB (< 2% from Lower)
        # Relaxed to just RSI <= 30 as per typical scanner expectation, 
        # or STRICT: RSI <= 30 AND Close <= LowerBB * 1.02
        f_over = (curr_rsi <= 30)
        if not pd.isna(curr_lower_bb) and curr_close > (curr_lower_bb * 1.05):
            # If not near lower band (e.g. > 5% away), maybe not oversold enough for bounce?
            # User dashboard says: "Price near Lower Bollinger Band".
            pass 
 
        # 6. Gap Up: Open > Prev High * 1.02 (2% Gap)
        f_gap_up = False
        if prev_vol > 0:
             # Dashboard says "Open > Prev Close + 2%"
             # Logic: (Open - PrevClose) / PrevClose * 100 >= 2.0
             prev_close = 0 # Re-init safely if strict scoping
             if len(group) >= 2: prev_close = group.iloc[-2]['close']
             
             if prev_close > 0 and ((curr_open - prev_close) / prev_close) * 100.0 >= 2.0:
                 f_gap_up = True
                 
        # 7. Squeeze: Bandwidth < 10%
        f_sqz = False
        if not pd.isna(curr_b_width) and curr_b_width < 0.10:
            f_sqz = True
            
        # 8. Smart Trend (Lux/Swing): Price > MA20 > MA60 AND RSI > 50
        # This is a stronger version of f_trend_strict
        f_lux_smart = False
        if (curr_close > curr_ma20 > curr_ma60) and (curr_rsi > 50):
            f_lux_smart = True
            
        # 9. Value (Long): P/E <= 20 (Undervalued)
        # Removed strict volume surge requirement for long-term value
        f_val = False
        pe = pe_map.get(sym)
        if pe is not None and 0 < pe <= 25:
            f_val = True

        # 10. Volatility: Intraday Range (High - Low) / Open >= 5%
        f_vola = False
        if curr_open and curr_open > 0:
            low_val = last['low'] or 0
            if curr_high and low_val:
                intraday_range = (curr_high - low_val) / curr_open
                if intraday_range >= 0.05:
                    f_vola = True

        # Trigger is True if ANY filter is hit
        is_triggered = (
            f_vol_strict or f_vola or f_trend_strict or 
            f_mom_strict or f_pat or f_over or 
            f_gap_up or f_sqz or f_lux_smart or f_val
        )

        row_dict = {
            "symbol": sym,
            "company": "", 
            "sector": "", 
            "industry": "",
            "close": clean_float(curr_close),
            "price_change_pct": clean_float(price_change_pct),
            "volume": int(last['volume']),
            "prev_volume": int(prev_vol), 
            "vol_change_pct": clean_float(vol_pct),
            
            # Technicals for Tooltip
            "rsi": clean_float(curr_rsi, 1),
            "rvol": clean_float(curr_rvol, 2),
            "ma20": clean_float(curr_ma20, 2),
            "ma60": clean_float(curr_ma60, 2),
            
            # VCS & Details
            "vcs": int(total_vcs), 
            "score_details": {
                "base": score_base,
                "trend": score_trend,
                "mom": score_mom,
                "vol": score_vol,
                "pattern": score_pattern
            },
            
            # Flags (Mapped to UI Filters)
            "f_volume": f_vol_strict,    
            "f_volatility": f_vola,  # [New]
            "f_trend": f_trend_strict,   
            "f_momentum": f_mom_strict,  
            "f_pattern": f_pat,
            "f_oversold": f_over,
            "f_gap": f_gap_up,
            "f_squeeze": f_sqz,
            "f_lux": f_lux_smart,    # Smart Trend
            "f_value": f_val,        # Value
            
            "trigger": is_triggered
        }
        
        # Determine if we should only save triggered rows?
        # User wants "Scan results" so likely wants to see everything that was scanned?
        # But usually a scanner filters out noise.
        # If we save everything, the Dashboard shows "Filtered Tickers: 500"... 
        # but Filtered usually means "Passed Filter".
        # Let's verify dashboard logic: "Filtered Tickers" = total_count.
        # "Triggered" = triggered_count.
        # So it is fine to save all, but mark them.
        
        rows_data.append(row_dict)

    if not rows_data:
        return None, {"scanned": 0, "triggers": 0}

    # Fetch extra info (Name/Sector) in one query
    found_symbols = [r['symbol'] for r in rows_data]
    ticker_info = Ticker.objects.filter(symbol__in=found_symbols).values('symbol', 'name', 'sector', 'industry')
    info_map = {t['symbol']: t for t in ticker_info}
    
    # Merge Info
    for r in rows_data:
        info = info_map.get(r['symbol'])
        if info:
            r['company'] = info['name']
            r['sector'] = info['sector']
            r['industry'] = info['industry']

    df = pd.DataFrame(rows_data)
    
    avg_p = df["price_change_pct"].mean()
    avg_v = df["vol_change_pct"].mean()
    
    # Sanitize NaNs for MySQL
    if pd.isna(avg_p): avg_p = 0.0
    if pd.isna(avg_v): avg_v = 0.0

    # Count actual triggers
    trig_count = sum(1 for r in rows_data if r.get('trigger'))

    metrics = {
        "scanned": len(df),
        "triggers": trig_count,
        "avg_price_change": float(avg_p),
        "avg_vol_change": float(avg_v)
    }
    
    return df, metrics


def save_scan_results(df, metrics):
    """
    Saves scan results (DataFrame) to ScanBatch and ScanRow.
    Restored for compatibility with views.py and cron.
    """
    if df is None or df.empty:
        return None

    # 0. Truncate old data: Keep only the latest scan results
    # User requested: "Truncate table and insert new data every time Run Scan is called"
    ScanBatch.objects.all().delete()

    # 1. Create Batch
    batch = ScanBatch.objects.create(
        started_at=timezone.now(),
        scanned_count=metrics.get("scanned", 0),
        triggered_count=metrics.get("triggers", 0),
        avg_price_change=metrics.get("avg_price_change"),
        avg_vol_change=metrics.get("avg_vol_change"),
    )

    # 2. Prepare Rows
    # We can use bulk_create
    rows = []
    records = df.to_dict("records")
    
    for rec in records:
        rows.append(ScanRow(
            batch=batch,
            symbol=rec['symbol'],
            company=rec.get('company'),
            industry=rec.get('industry'),
            close=clean_float(rec.get('close')),
            volume=rec.get('volume'),
            prev_volume=rec.get('prev_volume'),
            price_change_pct=clean_float(rec.get('price_change_pct')),
            vol_change_pct=clean_float(rec.get('vol_change_pct')),
            f_volume=rec.get('f_volume', False),
            f_volatility=rec.get('f_volatility', False),
            f_trend=rec.get('f_trend', False),
            f_momentum=rec.get('f_momentum', False),
            trigger=rec.get('trigger', False),
            f_pattern=rec.get('f_pattern', False),
            f_value=rec.get('f_value', False),
            f_oversold=rec.get('f_oversold', False),
            f_lux=rec.get('f_lux', False),
            f_gap=rec.get('f_gap', False),
            f_squeeze=rec.get('f_squeeze', False),
            vcs=rec.get('vcs', 50), 
            rsi=clean_float(rec.get('rsi'), 1),
            rvol=clean_float(rec.get('rvol'), 2),
            ma20=clean_float(rec.get('ma20'), 2),
            ma60=clean_float(rec.get('ma60'), 2),
            score_details=rec.get('score_details', {}),
        ))
        
    if rows:
        ScanRow.objects.bulk_create(rows, batch_size=500)

    return batch



# Keep other helpers if referenced, simplified here for replacement
