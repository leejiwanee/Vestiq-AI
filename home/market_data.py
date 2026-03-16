# home/market_data.py
import yfinance as yf
import pandas as pd

NY_TZ = "America/New_York"

INDEXES = {
    "^GSPC": {"label": "S&P 500"},
    "^IXIC": {"label": "Nasdaq"},
    "^DJI":  {"label": "Dow"},
    "^VIX":  {"label": "VIX"},
}

def fetch_index_history(symbol: str, period="3mo", interval="1d") -> pd.DataFrame:
    df = yf.download(
        symbol, period=period, interval=interval,
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

def get_indexes_snapshot(period="3mo", interval="1d"):
    """Return lightweight chart payloads + current stats for the Home dashboard."""
    items = []
    for sym, meta in INDEXES.items():
        try:
            df = fetch_index_history(sym, period=period, interval=interval)
            if df.empty: 
                continue
            close = df["Close"]
            # Build compact payload for Plotly
            payload = {
                "x": [d.isoformat() for d in close.index.to_pydatetime()],
                "y": [float(v) for v in close.round(2).tolist()],
                "label": meta["label"],
                "symbol": sym,
                "last": float(close.iloc[-1]),
                "chgpct": float((close.iloc[-1] / close.iloc[0] - 1) * 100),
            }
            items.append(payload)
        except Exception:
            # skip any failed index gracefully
            pass
    return items
