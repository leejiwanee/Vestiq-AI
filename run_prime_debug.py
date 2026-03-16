
import yfinance as yf
import pandas as pd
import numpy as np

def analyze_ticker(symbol):
    print(f"\nAnalyzing {symbol}...")
    try:
        df = yf.download(symbol, period="6mo", interval="1d", progress=False)
    except Exception as e:
        print(f"Error downloading {symbol}: {e}")
        return

    if df.empty:
        print("No data found.")
        return

    # Flatten columns
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # Calculate Indicators
    df['SMA20'] = df['Close'].rolling(window=20).mean()
    df['SMA50'] = df['Close'].rolling(window=50).mean()
    
    # RSI
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))

    # Bollinger Bands
    std20 = df['Close'].rolling(20).std()
    df['BB_Upper'] = df['SMA20'] + (std20 * 2.0)
    
    # VolMA
    df['VolMA20'] = df['Volume'].rolling(20).mean()
    
    # Get latest rows
    l = df.iloc[-1]
    p = df.iloc[-2]
    
    print(f"Date: {l.name.date()}")
    print(f"Close: {l['Close']:.2f}, Open: {l['Open']:.2f}")
    print(f"Prev Close: {p['Close']:.2f}, Prev Open: {p['Open']:.2f}")
    print(f"SMA20: {l['SMA20']:.2f}, SMA50: {l['SMA50']:.2f}")
    print(f"RSI: {l['RSI']:.2f}")
    if pd.isna(l['SMA20']) or pd.isna(l['SMA50']):
        print("Not enough data for MA.")
        return
    
    # --- Prime Logic Check ---
    
    # 1. Trend
    is_uptrend = (l['SMA50'] > p['SMA50']) and (l['Close'] > l['SMA50'])
    print(f"[Trend] SMA50 Rising & >SMA50: {is_uptrend} (SMA50: {l['SMA50']:.2f} > {p['SMA50']:.2f})")

    # 2. Setup (Touch)
    c_p_touch = l['Low'] <= (l['SMA20'] * 1.025)
    print(f"[Touch] Low ({l['Low']:.2f}) <= SMA20*1.025 ({l['SMA20'] * 1.025:.2f}): {c_p_touch}")

    # 3. Trigger (Reversal)
    prev_red = p['Close'] < p['Open']
    curr_green = l['Close'] > l['Open']
    reversal = prev_red and curr_green
    print(f"[Reversal] Prev Red ({prev_red}) -> Curr Green ({curr_green}): {reversal}")
    
    # 4. Trigger (Piercing)
    piercing = (l['Open'] < l['SMA20']) and (l['Close'] > l['SMA20']) and curr_green
    print(f"[Piercing] Open < SMA20 < Close: {piercing}")
    
    # 5. RSI
    c_p_val = l['RSI'] <= 60
    print(f"[RSI] RSI ({l['RSI']:.2f}) <= 60: {c_p_val}")

    is_prime = (is_uptrend and c_p_touch and (reversal or piercing) and c_p_val)
    
    print(f"IS PRIME? {is_prime}")

if __name__ == "__main__":
    analyze_ticker("NVDA")
    analyze_ticker("AMD")
