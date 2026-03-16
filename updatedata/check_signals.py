
import pandas as pd
import yfinance as yf
from datetime import timedelta

def calculate_stoch_slow(df, k_window, k_smooth, d_smooth):
    low_min = df['Low'].rolling(window=k_window).min()
    high_max = df['High'].rolling(window=k_window).max()
    
    # Fast K
    k_fast = 100 * (df['Close'] - low_min) / (high_max - low_min)
    
    # Slow K (Smooth Fast K)
    k_slow = k_fast.rolling(window=k_smooth).mean()
    
    # Slow D (Smooth Slow K)
    d_slow = k_slow.rolling(window=d_smooth).mean()
    
    return k_slow, d_slow

def check_signals(symbol):
    print(f"\n--- Checking {symbol} ---")
    df = yf.download(symbol, period="3mo", progress=False)
    if df.empty:
        print("No data.")
        return

    # Flatten MultiIndex columns if needed
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # Indicators
    df['SMA20'] = df['Close'].rolling(20).mean()
    k_short, d_short = calculate_stoch_slow(df, 5, 3, 3)
    df['k_s'] = k_short
    df['d_s'] = d_short
    
    # Check last 5 days
    last_5 = df.tail(5)
    
    for i in range(len(last_5)):
        row = last_5.iloc[i]
        date = row.name.date() if hasattr(row.name, 'date') else row.name
        
        # Need prev row for crossovers
        if i == 0: continue # Skip first of snippet? 
        # Actually need index in full df
        idx = df.index.get_loc(row.name)
        if idx < 1: continue
        prev = df.iloc[idx-1]
        
        # Prime Logic
        close = row['Close']
        sma20 = row['SMA20']
        prev_close = prev['Close']
        prev_sma20 = prev['SMA20']
        
        is_prime = (prev_close < prev_sma20) and (close > sma20)
        
        # Alpha Logic
        k = row['k_s']
        d = row['d_s']
        prev_k = prev['k_s']
        prev_d = prev['d_s']
        
        is_deep_oversold = (k <= 20)
        is_gold_cross = (prev_k < prev_d) and (k > d) and (k < 50)
        is_alpha = is_deep_oversold or is_gold_cross
        
        # Output
        sigs = []
        if is_prime: sigs.append("PRIME ⚡")
        if is_alpha: sigs.append("ALPHA ✨")
        
        print(f"Date: {date} | Price: {close:.2f} | SMA20: {sma20:.2f} | K: {k:.1f} | D: {d:.1f} | Signals: {sigs}")

symbols = ['BTBT', 'MARA', 'PLUG']
for s in symbols:
    check_signals(s)
