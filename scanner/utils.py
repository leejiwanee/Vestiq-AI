import pandas as pd
import yfinance as yf
from ta.volatility import BollingerBands
from ta.momentum import RSIIndicator

NY_TZ = "America/New_York"

def fetch_daily_df(symbol: str, period: str = "3mo") -> pd.DataFrame:
    df = yf.download(
        symbol, period=period, interval="1d",
        auto_adjust=True, progress=False, threads=False
    )
    if df.empty or "Close" not in df.columns:
        return pd.DataFrame()

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(-1)

    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    df.index = df.index.tz_convert(NY_TZ)
    return df

def with_indicators(df: pd.DataFrame) -> pd.DataFrame:
    close = df["Close"].copy()
    bb = BollingerBands(close=close, window=20, window_dev=2)
    rsi = RSIIndicator(close=close, window=14)
    out = df.copy()
    out["bb_bbm"] = bb.bollinger_mavg()
    out["bb_bbh"] = bb.bollinger_hband()
    out["bb_bbl"] = bb.bollinger_lband()
    out["rsi"] = rsi.rsi()
    return out.dropna()

def latest_signal_row(df: pd.DataFrame):
    if df.empty:
        return None, False
    latest = df.iloc[-1]
    cond = (latest["Close"] <= latest["bb_bbl"]) and (latest["rsi"] < 30)
    return latest, cond

def get_options_chain(symbol: str):
    """
    Fetches the nearest 3 expiration options chains for a symbol using yfinance.
    Returns a list of dicts: [{'expiration': date, 'calls': [], 'puts': []}, ...], or None if error.
    """
    try:
        ticker = yf.Ticker(symbol)
        expirations = ticker.options
        
        if not expirations:
            return None
            
        # Get nearest 3 expirations (or fewer if not available)
        target_expirations = expirations[:3]
        results = []

        # Helper to format rows
        def format_opts(df):
            if df.empty: return []
            # Fill NaN
            df = df.fillna(0)
            records = []
            for _, row in df.iterrows():
                records.append({
                    "contractSymbol": row.get('contractSymbol'),
                    "strike": float(row.get('strike', 0)),
                    "lastPrice": float(row.get('lastPrice', 0)),
                    "bid": float(row.get('bid', 0)),
                    "ask": float(row.get('ask', 0)),
                    "change": float(row.get('change', 0)),
                    "percentChange": float(row.get('percentChange', 0)),
                    "volume": int(row.get('volume', 0)),
                    "openInterest": int(row.get('openInterest', 0)),
                    "impliedVolatility": float(row.get('impliedVolatility', 0)),
                    "inTheMoney": bool(row.get('inTheMoney', False)),
                })
            return records
        
        for exp_date in target_expirations:
            try:
                chain = ticker.option_chain(exp_date)
                results.append({
                    "expiration": exp_date,
                    "calls": format_opts(chain.calls),
                    "puts": format_opts(chain.puts)
                })
            except Exception as e:
                print(f"Error fetching options for {symbol} on {exp_date}: {e}")
                continue

        return results if results else None
        
    except Exception as e:
        print(f"Error fetching options for {symbol}: {e}")
        return None
