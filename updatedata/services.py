# updatetop200/services.py
import os
import io
import re
import requests
import pandas as pd
import xml.etree.ElementTree as ET
from io import StringIO
from urllib.parse import unquote

# ======================================
# CONFIGURATION
# ======================================
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

SLICKCHARTS_SNP500    = "https://www.slickcharts.com/sp500"
SLICKCHARTS_NASDAQ100 = "https://www.slickcharts.com/nasdaq100"
#NASDAQ_LISTED_URL     = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt"

# iShares Russell 2000 ETF (IWM) CSV live feed (User Provided)
IWM_CSV_URL_LIVE = (
    "https://www.ishares.com/us/products/239710/ishares-russell-2000-etf/1467271812596.ajax?fileType=csv"
)

# Optional env overrides
IWM_CSV_URL = os.getenv("IWM_CSV_URL", "").strip()
ONEQ_CSV_URL = os.getenv("ONEQ_CSV_URL", "").strip()

# Local fallbacks
LOCAL_DIR  = os.path.join(os.path.dirname(__file__), "data")
LOCAL_IWM  = os.path.join(LOCAL_DIR, "iwm.csv")
LOCAL_ONEQ = os.path.join(LOCAL_DIR, "oneq.csv")

# Seed fallback lists (last resort)
SEED_ONEQ = [
    "AAPL","MSFT","AMZN","NVDA","GOOGL","GOOG","META","AVGO","COST","TSLA","PEP","AMD","ADBE",
    "CSCO","NFLX","TMUS","INTC","AMAT","QCOM","TXN","INTU","BKNG","ISRG","REGN","VRTX","PANW"
]

SEED_IWB = [ 
    "MSFT", "AAPL", "NVDA", "AMZN", "META", "GOOGL", "GOOG", "BRK.B", "LLY", "AVGO",
    "JPM", "XOM", "TSLA", "UNH", "V", "PG", "MA", "COST", "JNJ", "HD"
]

_MAP = {"BRK.B": "BRK-B", "BF.B": "BF-B"}
_WS  = re.compile(r"\s+")

# ======================================
# HELPERS
# ======================================
def _sanitize(url: str) -> str:
    if not url:
        return ""
    u = unquote(url).strip()
    bad = ("<", ">", "%3c", "%3e", "direct-oneq-holdings", "direct-iwm-holdings")
    return "" if any(b in u.lower() for b in bad) else u

IWM_CSV_URL = _sanitize(IWM_CSV_URL)
ONEQ_CSV_URL  = _sanitize(ONEQ_CSV_URL)

def _norm(sym: str) -> str:
    s = (sym or "").upper().strip()
    s = _WS.sub("", s)
    return _MAP.get(s, s)

def _read_html(url: str) -> pd.DataFrame | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        tables = pd.read_html(StringIO(r.text))
        return tables[0] if tables else None
    except Exception as e:
        print(f"[_read_html] Failed: {e}")
        return None


        
import xml.etree.ElementTree as ET

def _read_xml_spreadsheet(content: bytes, sheet_name="Holdings") -> pd.DataFrame | None:
    """
    Parses 'Microsoft Excel 2003 XML' format (iShares 'xls' is often this).
    Uses ElementTree to manually extract the 'Holdings' sheet.
    """
    try:
        # Decode and strip BOM(s). The file has double BOM (\ufeff\ufeff).
        text = content.decode("utf-8", errors="ignore").lstrip('\ufeff')
        
        # [Fix] iShares XML often has unescaped '&' in URLs (e.g. &style=All).
        # We must escape them to &amp; unless they are already valid entities.
        # This regex matches '&' not followed by (entity_name; or #number;)
        text = re.sub(r'&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)', '&amp;', text)
        
        root = ET.fromstring(text)
        # Namespace for formatting
        ns = "{urn:schemas-microsoft-com:office:spreadsheet}"
        
        target_sheet = None
        # Find worksheet by name
        for sheet in root.findall(f".//{ns}Worksheet"):
            if sheet.attrib.get(f"{ns}Name") == sheet_name:
                target_sheet = sheet
                break
        
        if target_sheet is None:
            # Fallback: Try first sheet if Holdings not found
            print(f"[_read_xml_spreadsheet] Sheet '{sheet_name}' not found. Using first sheet.")
            target_sheet = root.find(f".//{ns}Worksheet")
            
        if target_sheet is None:
            return None
            
        # Parse Rows
        rows = target_sheet.findall(f".//{ns}Row")
        data_rows = []
        for row in rows:
            cells = row.findall(f"{ns}Cell")
            row_data = []
            for cell in cells:
                data_tag = cell.find(f"{ns}Data")
                if data_tag is not None:
                    row_data.append(data_tag.text)
                else:
                    row_data.append(None)
            data_rows.append(row_data)
            
        if not data_rows:
            return None
            
        # Find Header (first row with "Ticker" or "Symbol")
        header_idx = -1
        for i, r in enumerate(data_rows[:30]):
            str_r = [str(x).lower() for x in r if x]
            if "ticker" in str_r or "symbol" in str_r:
                header_idx = i
                break
        
        if header_idx == -1:
            header_idx = 0 # Default to 0 if not found
            
        cols = data_rows[header_idx]
        # Ensure cols are strings and not None
        cols = [str(c) if c else f"col_{j}" for j, c in enumerate(cols)]
        
        data = data_rows[header_idx+1:]
        
        # Normalize row lengths (some rows might have fewer cells)
        max_len = len(cols)
        clean_data = []
        for r in data:
            if len(r) < max_len:
                r.extend([None] * (max_len - len(r)))
            clean_data.append(r[:max_len])
            
        df = pd.DataFrame(clean_data, columns=cols)
        return df

    except Exception as e:
        print(f"[_read_xml_spreadsheet] Failed: {e}")
        return None

def _read_excel_url(url: str, sheet_name="Holdings") -> pd.DataFrame | None:
    """
    Reads an Excel file from a URL.
    Supports .xlsx (openpyxl), .xls (xlrd), and XML Spreadsheet 2003 (ElementTree).
    """
    try:
        r = requests.get(url, headers=HEADERS, timeout=60) # Increased timeout for large excel
        r.raise_for_status()
        
        # Note: Using io.BytesIO for binary content
        with io.BytesIO(r.content) as f:
            df = None
            last_err = None
            
            # 1. Try Standard Excel Engines (openpyxl, xlrd)
            for eng in ['openpyxl', 'xlrd']:
                try:
                    f.seek(0)
                    # First, read a small chunk to find the header
                    temp_df = pd.read_excel(f, sheet_name=sheet_name, header=None, nrows=50, engine=eng)
                    
                    header_idx = None
                    for i, row in temp_df.iterrows():
                        # Check if row contains "Ticker" or "Symbol"
                        row_vals = [str(x).lower() for x in row.values]
                        if "ticker" in row_vals or "symbol" in row_vals:
                            header_idx = i
                            break
                    
                    if header_idx is not None:
                        f.seek(0)
                        df = pd.read_excel(f, sheet_name=sheet_name, header=header_idx, engine=eng)
                    else:
                         # print(f"[_read_excel_url] Could not find header in first 50 rows (engine={eng}).")
                         f.seek(0)
                         df = pd.read_excel(f, sheet_name=sheet_name, header=0, engine=eng)
                    
                    if df is not None:
                        # Success
                        return df
                        
                except Exception as e:
                    last_err = e
                    continue
            
            # 2. Try Custom XML Spreadsheet 2003 Parser (The "Nuclear Option")
            if df is None:
                # print(f"[_read_excel_url] Excel engines failed. Trying XML Spreadsheet 2003 parser...")
                df = _read_xml_spreadsheet(r.content, sheet_name=sheet_name)
                
                if df is not None:
                    return df

            print(f"[_read_excel_url] All parsing attempts failed for {url}")
            return None
                 
    except Exception as e:
        print(f"[_read_excel_url] Failed to read Excel from {url}: {e}")
        return None
                 
        return df
    except Exception as e:
        print(f"[_read_excel_url] Failed to read Excel from {url}: {e}")
        return None

def _parse_float(val):
    """'1,234.56' 이나 '7.23%' 같은 문자열도 안전하게 float로 변환."""
    import pandas as pd

    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, str):
        val = val.replace(",", "").replace("%", "").strip()
        if val == "":
            return None
    try:
        return float(val)
    except Exception:
        return None


def _read_slickcharts_table(url: str) -> pd.DataFrame | None:
    """
    Slickcharts 테이블 전체를 DataFrame으로 가져오고,
    column 이름을 소문자로 정규화한다.
    (company, symbol, weight, price, chg, % chg → company, symbol, weight, price, chg, pct_chg)
    """
    df = _read_html(url)
    if df is None or df.empty:
        return None

    # 컬럼 소문자로 통일
    new_cols = {}
    for c in df.columns:
        lc = str(c).strip().lower()
        if lc == "% chg":
            lc = "pct_chg"
        new_cols[c] = lc
    df = df.rename(columns=new_cols)

    # 혹시라도 퍼센트 변화 컬럼이 다른 이름이면 한 번 더 맞추기
    if "pct_chg" not in df.columns:
        for c in df.columns:
            if "chg" in c and "%" in c and c != "chg":
                df = df.rename(columns={c: "pct_chg"})
                break

    return df

# ... (CSV helpers removed/reduced as we focus on Excel for IWB) ...

# ======================================
# PUBLIC: "Refresh Russell CSV" helper
# ======================================
def download_latest_iwm_csv(dest_path: str = LOCAL_IWM, top_n: int = 2000, progress_callback=None) -> tuple[bool, str]:
    # iShares 웹사이트에서 IWM (Russell 2000) CSV를 다운로드하고,
    # Market Cap 기준 상위 N개만 필터링하여 저장.
    try:
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        
        # Download CSV from iShares
        print("[Refresh Russell] Downloading from iShares...")
        if progress_callback: progress_callback(10, "Downloading from iShares...")
        r = requests.get(IWM_CSV_URL_LIVE, headers=HEADERS, timeout=60)
        r.raise_for_status()
        
        # Parse CSV (skip first 9 metadata rows)
        if progress_callback: progress_callback(40, "Parsing CSV...")
        from io import StringIO
        df = pd.read_csv(StringIO(r.text), skiprows=9)
        
        if df.empty:
            return False, "Downloaded CSV is empty"
        
        # Normalize column names
        if progress_callback: progress_callback(60, "Processing Tickers...")
        df.columns = [str(c).strip().lower() for c in df.columns]
        
        # Filter out invalid tickers
        if 'ticker' in df.columns:
            df = df[df['ticker'].notna()]
            df = df[~df['ticker'].astype(str).str.strip().isin(['-', '--', '', 'nan'])]
        
        # Sort by market value (descending) and take top N
        market_val_col = next((c for c in df.columns if 'market value' in c or 'market_value' in c), None)
        
        if market_val_col:
            # Convert market value to numeric (remove commas)
            df[market_val_col] = df[market_val_col].replace({',': '', '"': ''}, regex=True)
            df[market_val_col] = pd.to_numeric(df[market_val_col], errors='coerce')
            
            # Sort by market value descending
            df = df.sort_values(market_val_col, ascending=False)
            print(f"[Refresh Russell] Sorted by {market_val_col}")
        else:
            print("[Refresh Russell] Warning: Market value column not found, using original order")
        
        # Take top N
        if progress_callback: progress_callback(80, "Optimizing List...")
        original_count = len(df)
        df = df.head(top_n)
        
        # Rename ticker to symbol for consistency
        if 'ticker' in df.columns:
            df = df.rename(columns={'ticker': 'symbol'})
        
        # Save filtered CSV
        if progress_callback: progress_callback(90, "Saving to Disk...")
        df.to_csv(dest_path, index=False)
        
        return True, f"Saved top {len(df)} of {original_count} (by Market Cap) to {dest_path}"
        
    except Exception as e:
        return False, f"Download failed: {e}"

# ======================================
# FETCHERS
# ======================================

def fetch_sp500_df() -> pd.DataFrame | None:
    """S&P500 전체 (Slickcharts)"""
    return _read_slickcharts_table(SLICKCHARTS_SNP500)


def fetch_nasdaq100_df() -> pd.DataFrame | None:
    """Nasdaq100 전체 (Slickcharts)"""
    return _read_slickcharts_table(SLICKCHARTS_NASDAQ100)

def fetch_russell2000_df() -> pd.DataFrame | None:
    """
    로컬 CSV 파일에서 Russell 상위 1000개 종목 DataFrame 반환.
    CSV는 "Refresh Russell 2000" 버튼으로 미리 다운로드되어 있어야 함.
    (이미 Market Cap 기준 상위 1000개로 필터링, 컬럼명 정규화됨)
    """
    try:
        if not os.path.exists(LOCAL_IWM):
            print(f"[fetch_russell2000_df] CSV not found: {LOCAL_IWM}")
            print("[fetch_russell2000_df] Please click 'Refresh Russell 2000' button first.")
            return None
        
        # Read file first to determine format (Raw vs Pre-processed)
        with open(LOCAL_IWM, 'r') as f:
            first_line = f.readline()
            
        if 'iShares' in first_line or 'Fund Holdings' in first_line:
            # Raw format likely
            df = pd.read_csv(LOCAL_IWM, skiprows=9)
        else:
            # Clean/Pre-processed format
            df = pd.read_csv(LOCAL_IWM)
        
        if df.empty:
            print("[fetch_russell2000_df] CSV is empty")
            return None
        
        # Ensure column names are lowercase
        df.columns = [str(c).strip().lower() for c in df.columns]

        # Rename 'Ticker' to 'symbol' if present (Raw format has 'Ticker')
        if 'ticker' in df.columns:
            df = df.rename(columns={'ticker': 'symbol'})
        
        print(f"[fetch_russell2000_df] Loaded {len(df)} holdings from CSV")
        return df
        
    except Exception as e:
        print(f"[fetch_russell2000_df] Failed: {e}")
        return None








# ======================================
# SCHA (Schwab Small-Cap ETF)
# ======================================
SCHA_BASE_URL = "https://www.schwabassetmanagement.com/sites/g/files/eyrktu361/files/product_files/SCHA/SCHA_FundHoldings_{date}.CSV"
LOCAL_SCHA = os.path.join(LOCAL_DIR, "scha.csv")

def download_latest_scha_csv(dest_path: str = LOCAL_SCHA) -> tuple[bool, str]:
    # Downloads SCHA holdings CSV from Schwab.
    # URL includes current date.
    # Fallback: If file is missing (e.g. weekend), tries previous dates.
    import datetime
    import subprocess
    
    try:
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        
        # Headers mimicking a browser
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Referer": "https://www.schwabassetmanagement.com/products/scha",
            "Accept-Language": "en-US,en;q=0.9"
        }

        def _fetch_url_content(target_url):
            # Tries Requests first, then Curl.
            # 1. Requests
            try:
                r = requests.get(target_url, headers=headers, timeout=20)
                if r.status_code == 200:
                    return r.text
            except Exception:
                pass
            
            # 2. Curl Fallback
            try:
                cmd = [
                    "curl", "-L", "-A", headers["User-Agent"], 
                    "-H", f"Referer: {headers['Referer']}",
                    target_url
                ]
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode == 0 and result.stdout:
                    return result.stdout
            except Exception:
                pass
            return None

        # Logic: Try Yesterday first (User preference/higher success rate), then Today
        today = datetime.date.today()
        dates_to_try = [today - datetime.timedelta(days=1), today]
        
        text_content = None
        used_url = ""
        
        for d in dates_to_try:
            d_str = d.strftime('%Y-%m-%d')
            url = SCHA_BASE_URL.format(date=d_str)
            print(f"[Refresh SCHA] Trying {url}...")
            
            content = _fetch_url_content(url)
            
            # Validate Content (Must be CSV, not HTML error page)
            if content and "<html" not in content[:200].lower():
                text_content = content
                used_url = url
                break
            elif content:
                print(f"[Refresh SCHA] {d_str} returned HTML (Access Denied/404).")
            else:
                print(f"[Refresh SCHA] {d_str} connection failed.")

        if not text_content:
            return False, "Download failed for Today and Yesterday (Access Denied or Not Found)."

        # Parse CSV
        from io import StringIO
        text_content = text_content.lstrip('\ufeff')
        df = pd.read_csv(StringIO(text_content))
        
        if df.empty:
            return False, "Downloaded CSV is empty"
            
        # Normalize columns
        df.columns = [str(c).strip().lower() for c in df.columns]
        
        # Filter valid tickers
        if 'symbol' in df.columns:
            df = df[df['symbol'].notna()]
            df = df[~df['symbol'].astype(str).str.strip().isin(['nan', ''])]
            
        # Save
        df.to_csv(dest_path, index=False)
        return True, f"Saved {len(df)} SCHA holdings via {used_url}"

    except Exception as e:
        return False, f"Download failed: {e}"

def fetch_scha_df() -> pd.DataFrame | None:
    # Reads local SCHA CSV.
    if not os.path.exists(LOCAL_SCHA):
        return None
    try:
        df = pd.read_csv(LOCAL_SCHA)
        df.columns = [str(c).strip().lower() for c in df.columns]
        return df
    except:
        return None

# ======================================
# COMBINED UNIVERSE BUILDER
# ======================================
def build_combined_universe():
    # Universe: S&P500 + Nasdaq100 + Russell2000 + SCHA (Small Cap)
    # Unique Union.
    dbg = {}

    _sp_df = fetch_sp500_df()
    sp_df = _sp_df if _sp_df is not None else pd.DataFrame()

    _ndx_df = fetch_nasdaq100_df()
    ndx_df = _ndx_df if _ndx_df is not None else pd.DataFrame()

    _rus_df = fetch_russell2000_df()
    rus_df = _rus_df if _rus_df is not None else pd.DataFrame()
    
    _scha_df = fetch_scha_df()
    scha_df = _scha_df if _scha_df is not None else pd.DataFrame()

    symbols: list[str] = []
    seen: set[str] = set()
    market: dict[str, str] = {}
    meta: dict[str, dict] = {}
    
    EXCLUDE_SYMBOLS = {"GOOG", "FOX", "NWS", "XTSLA"}

    def add_label(sym: str, label: str):
        cur = market.get(sym, "")
        if not cur:
            market[sym] = label
        else:
            parts = [p.strip() for p in cur.split(",") if p.strip()]
            if label not in parts:
                parts.append(label)
                market[sym] = ",".join(parts)

    def add_meta(sym: str, *, name=None, weight=None, last_price=None, change_amount=None, change_percent=None, sector=None, industry=None):
        info = meta.get(sym, {})
        # Prioritize non-empty values
        if name and not info.get("name"): info["name"] = name
        if weight is not None and info.get("weight") is None: info["weight"] = weight
        if sector and not info.get("sector"): info["sector"] = sector
        meta[sym] = info

    def add_symbol(sym: str, label: str, **meta_kwargs):
        sym = _norm(sym)
        if sym in EXCLUDE_SYMBOLS: return
        if not sym: return
        
        if sym not in seen:
            symbols.append(sym)
            seen.add(sym)
        
        add_label(sym, label)
        add_meta(sym, **meta_kwargs)

    # 1. S&P 500
    if not sp_df.empty:
        for _, row in sp_df.iterrows():
            sym = row.get("symbol")
            name = str(row.get("company") or "").strip()
            add_symbol(sym, "sp500", name=name)
    
    # 2. Nasdaq 100
    if not ndx_df.empty:
        for _, row in ndx_df.iterrows():
            sym = row.get("symbol")
            name = str(row.get("company") or "").strip()
            add_symbol(sym, "nasdaq100", name=name)
            
    # 3. Russell 2000
    if not rus_df.empty:
        sym_col = 'symbol' if 'symbol' in rus_df.columns else 'ticker'
        for _, row in rus_df.iterrows():
            sym = row.get(sym_col)
            sector = str(row.get('sector') or "").strip()
            add_symbol(sym, "russell2000", sector=sector)

    # 4. SCHA (Schwab Small Cap)
    if not scha_df.empty:
        import re
        # Columns: symbol, name, sector, ...
        for _, row in scha_df.iterrows():
            sym = row.get("symbol")
            if not sym or pd.isna(sym):
                continue
            sym = str(sym).strip().upper()
            
            # Filter unwanted: "2200964D" (digits), headers/footers (too long or spaces)
            if re.search(r'\d', sym):
                continue
            if len(sym) > 10:
                continue
                
            name = str(row.get("name") or "").strip()
            sector = str(row.get("sector") or "").strip()
            add_symbol(sym, "scha_smallcap", name=name, sector=sector)

    dbg["total"] = len(symbols)
    return symbols, market, meta, dbg



# ======================================
# FMP API (Financial Modeling Prep)
# ======================================
def fetch_fmp_prices(symbol: str, days: int = 365*5) -> list[dict] | None:
    # Fetches historical price data from FMP API.
    # Endpoint: /historical-price-full/{symbol}
    from django.conf import settings
    import datetime
    
    api_key = settings.FMP_API_KEY
    if not api_key:
        print("[FMP] Error: FMP_API_KEY not set.")
        return None
        
    # FMP Symbol Handling (BRK.B -> BRK-B)
    req_sym = symbol.replace('.', '-')
    
    # Calculate start date
    start_date = datetime.date.today() - datetime.timedelta(days=days)
    from_str = start_date.strftime('%Y-%m-%d')
    
    url = f"https://financialmodelingprep.com/api/v3/historical-price-full/{req_sym}?from={from_str}&apikey={api_key}"
    
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        data = r.json()
        
        # FMP returns {'symbol': 'AAPL', 'historical': [...]}
        if 'historical' in data:
            return data['historical']
        elif 'Error Message' in data:
            print(f"[FMP] API Error for {symbol} ({req_sym}): {data['Error Message']}")
            return None
        else:
            return []
            
    except Exception as e:
        print(f"[FMP] Request failed for {symbol}: {e}")
        return None
