# scripts/update_snapshots.py
"""
S&P 500 / Nasdaq 100 / Russell 1000
Fetches constituents from Wikipedia and updates snapshots using yfinance (for fundamentals).
Generates:
  data/sp500_snapshot.csv
  data/nasdaq100_snapshot.csv
  data/russell1000_snapshot.csv
"""

import io
import pathlib
import warnings
import time
import pandas as pd
import requests
import urllib3
import yfinance as yf
from insight.utils import safe_yf_download, safe_get_fast_info

BASE_DIR = pathlib.Path(__file__).resolve().parents[1] / "insight"
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36 Vestiq/1.0"
    )
}

def fetch_constituents(url: str):
    """
    Fetch constituents from Wikipedia.
    Returns DataFrame with columns: symbol, name, sector
    """
    print(f"[fetch] {url}")
    resp = requests.get(url, headers=HEADERS, verify=False, timeout=15)
    resp.raise_for_status()

    html_io = io.StringIO(resp.text)
    tables = pd.read_html(html_io)

    candidate = None

    for i, t in enumerate(tables):
        if isinstance(t.columns, pd.MultiIndex):
            cols = [str(c[-1]).strip() for c in t.columns]
            t.columns = cols
        else:
            cols = [str(c).strip() for c in t.columns]

        has_symbol = any(c in cols for c in ("Symbol", "Ticker"))
        has_name = any(c in cols for c in ("Security", "Company", "Name"))
        has_sector_like = any(("Sector" in c) or ("Industry" in c) for c in cols)

        if has_symbol and has_name and has_sector_like:
            candidate = t
            break

    if candidate is None:
        raise RuntimeError("Could not find constituent table.")

    cols = [str(c).strip() for c in candidate.columns]
    candidate.columns = cols

    def find_col(candidates):
        for want in candidates:
            for col in candidate.columns:
                if col == want or want in col:
                    return col
        return None

    sym_col = find_col(["Symbol", "Ticker"])
    name_col = find_col(["Security", "Company", "Name"])
    sector_col = find_col(["GICS Sector", "Sector", "ICB Industry", "Industry"])

    if not sym_col or not name_col or not sector_col:
        raise RuntimeError(f"Missing columns: {sym_col}, {name_col}, {sector_col}")

    df = candidate[[sym_col, name_col, sector_col]].copy()
    df = df.rename(columns={sym_col: "symbol", name_col: "name", sector_col: "sector"})

    df["symbol"] = df["symbol"].astype(str).str.strip().str.upper()
    df["name"] = df["name"].astype(str).str.strip()
    df["sector"] = df["sector"].astype(str).str.strip()

    df = df.dropna(subset=["symbol"])
    return df

def build_snapshot(df: pd.DataFrame, outfile: pathlib.Path):
    """
    df: columns = symbol, name, sector
    outfile: path to save csv
    Uses yfinance to fetch price and market cap.
    """
    symbols = df["symbol"].tolist()
    print(f"[snapshot] {outfile.name}  Symbols: {len(symbols)}")

    rows = []
    
    # Batch processing
    BATCH_SIZE = 50
    total_batches = (len(symbols) + BATCH_SIZE - 1) // BATCH_SIZE

    for i in range(0, len(symbols), BATCH_SIZE):
        batch_df = df.iloc[i : i + BATCH_SIZE]
        batch_symbols = batch_df["symbol"].tolist()
        tickers_str = " ".join(batch_symbols)
        
        print(f"  Processing batch {i//BATCH_SIZE + 1}/{total_batches}...")

        # 1) Price Download (2 days)
        try:
            price = safe_yf_download(
                tickers=tickers_str,
                period="2d",
                interval="1d",
                group_by="ticker",
                auto_adjust=False,
                threads=True, 
                progress=False,
            )
        except Exception as e:
            print(f"  Error downloading batch: {e}")
            price = pd.DataFrame()

        # 2) Market Cap (fast_info)
        tickers_yf = yf.Tickers(tickers_str)
        
        multi = isinstance(price.columns, pd.MultiIndex)

        for _, row in batch_df.iterrows():
            sym = row["symbol"]
            name = row["name"]
            sector = row["sector"]
            
            # 1) Change %
            change_pct = 0.0
            last_close = None
            try:
                if multi:
                    if sym in price.columns.get_level_values(0):
                        sub = price[sym]
                    else:
                        sub = None
                else:
                    if len(batch_symbols) == 1 and not price.empty:
                         sub = price
                    elif sym in price.columns: 
                         sub = price[sym]
                    else:
                         sub = None

                if sub is not None and not sub.empty:
                    if "Adj Close" in sub.columns:
                        closes = sub["Adj Close"]
                    else:
                        closes = sub["Close"]
                    closes = closes.dropna()
                    
                    if len(closes) >= 2:
                        prev = float(closes.iloc[-2])
                        last = float(closes.iloc[-1])
                    elif len(closes) == 1:
                        prev = last = float(closes.iloc[-1])
                    else:
                        prev = last = None

                    last_close = last
                    if prev and last:
                        change_pct = (last - prev) / prev * 100.0
            except Exception:
                pass

            # 2) Market Cap
            market_cap = None
            try:
                t = tickers_yf.tickers.get(sym)
                if t is not None:
                    mcap = safe_get_fast_info(t, "market_cap")
                    if mcap:
                        market_cap = float(mcap)
            except Exception:
                pass

            # Fallback Market Cap
            if market_cap is None:
                if last_close is not None:
                    market_cap = abs(last_close) * 1e8 # Rough fallback
                else:
                    market_cap = 1e8

            rows.append({
                "symbol": sym,
                "name": name,
                "sector": sector,
                "market_cap": market_cap,
                "change_pct": change_pct,
            })
        
        time.sleep(1)

    out_df = pd.DataFrame(rows)
    out_df.to_csv(outfile, index=False)
    print("  Saved:", outfile, "rows:", len(out_df))

def run_update_snapshots():
    # 1) S&P 500
    sp500_url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    try:
        sp500 = fetch_constituents(sp500_url)
        build_snapshot(sp500, DATA_DIR / "sp500_snapshot.csv")
    except Exception as e:
        print(f"Failed S&P500: {e}")

    # 2) Nasdaq 100
    nasdaq_url = "https://en.wikipedia.org/wiki/Nasdaq-100"
    try:
        nasdaq = fetch_constituents(nasdaq_url)
        build_snapshot(nasdaq, DATA_DIR / "nasdaq100_snapshot.csv")
    except Exception as e:
        print(f"Failed Nasdaq100: {e}")

    # 3) Russell 1000
    russell_url = "https://en.wikipedia.org/wiki/Russell_1000_Index"
    try:
        russell = fetch_constituents(russell_url)
        build_snapshot(russell, DATA_DIR / "russell1000_snapshot.csv")
    except Exception as e:
        print(f"Failed Russell1000: {e}")

if __name__ == "__main__":
    run_update_snapshots()
