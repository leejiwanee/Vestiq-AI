import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import pandas as pd
from django.conf import settings
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class TiingoClient:
    def __init__(self):
        self.api_key = settings.TIINGO_API_KEY
        self.headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Token {self.api_key}'
        }
        self.base_url = "https://api.tiingo.com/tiingo"
        self.iex_url = "https://api.tiingo.com/iex"
        
        # Configure Retry Strategy
        self.session = requests.Session()
        retries = Retry(
            total=3,
            backoff_factor=1, # Sleep 1s, 2s, 4s
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"]
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retries))

    def get_historical_data(self, symbol, start_date, end_date=None, interval='daily'):
        """
        Fetch historical data (OHLCV).
        interval: 'daily' (EOD) or '1min', '5min', '15min', '1hour' (IEX Intraday)
        """
        if not self.api_key:
            logger.error("TIINGO_API_KEY is missing.")
            return pd.DataFrame()

        # Format dates
        if isinstance(start_date, datetime):
            start_date = start_date.strftime('%Y-%m-%d')
        if isinstance(end_date, datetime):
            end_date = end_date.strftime('%Y-%m-%d')

        try:
            if interval == 'daily':
                url = f"{self.base_url}/daily/{symbol}/prices"
                params = {
                    'startDate': start_date,
                    'columns': 'date,open,high,low,close,volume,adjOpen,adjHigh,adjLow,adjClose,adjVolume,divCash,splitFactor',
                    'resampleFreq': 'daily' 
                }
            else:
                # IEX Intraday
                url = f"{self.iex_url}/{symbol}/prices"
                params = {
                    'startDate': start_date,
                    'resampleFreq': interval,
                    'columns': 'date,open,high,low,close,volume'
                }
            
            if end_date:
                params['endDate'] = end_date

            response = self.session.get(url, headers=self.headers, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if not data:
                return pd.DataFrame()

            df = pd.DataFrame(data)
            
            # Standardize columns to match yfinance style (Title Case) for compatibility
            # Tiingo returns: date, open, high, low, close, volume, adjClose, etc.
            # We map them to: Date, Open, High, Low, Close, Volume
            
            rename_map = {
                'date': 'Date',
                'open': 'Open',
                'high': 'High',
                'low': 'Low',
                'close': 'Close',
                'volume': 'Volume',
                'adjOpen': 'Adj Open',
                'adjHigh': 'Adj High',
                'adjLow': 'Adj Low',
                'adjClose': 'Adj Close',
                'adjVolume': 'Adj Volume',
                'divCash': 'Div Cash',
                'splitFactor': 'Split Factor'
            }
            df = df.rename(columns=rename_map)
            
            # Parse Date
            df['Date'] = pd.to_datetime(df['Date'])
            df = df.set_index('Date')
            
            # If daily, use adjClose as Close for analysis consistency? 
            # yfinance 'Close' is usually adjusted if auto_adjust=True.
            # Let's keep Close as raw close and Adj Close as adjusted.
            
            return df

        except Exception as e:
            logger.error(f"[Tiingo] Error fetching history for {symbol}: {e}")
            return pd.DataFrame()

    def get_batch_snapshots(self, tickers):
        """
        Fetch full IEX snapshot (OHLCV) for tickers.
        Returns list of dicts: [{'ticker': 'AAPL', 'open': ..., 'high': ..., ...}, ...]
        """
        if not tickers: return []
        
        chunk_size = 50
        all_data = []
        
        for i in range(0, len(tickers), chunk_size):
            chunk = tickers[i:i+chunk_size]
            tickers_str = ",".join(chunk)
            url = f"{self.iex_url}/"
            params = {'tickers': tickers_str, 'token': self.api_key}
            
            try:
                response = self.session.get(url, params=params, timeout=5)
                response.raise_for_status()
                data = response.json() # List of dicts
                all_data.extend(data)
            except Exception as e:
                logger.error(f"[Tiingo] Batch snapshot error: {e}")
                
        return all_data

    def get_latest_price_snapshot(self, tickers):
        """
        Fetch latest IEX price for a list of tickers (REST fallback).
        """
        if not tickers: return {}
        
        # Tiingo IEX endpoint supports comma-separated tickers
        # URL: https://api.tiingo.com/iex/?tickers=aapl,spy
        
        # Chunking to be safe (URL length)
        chunk_size = 50
        results = {}
        
        for i in range(0, len(tickers), chunk_size):
            chunk = tickers[i:i+chunk_size]
            tickers_str = ",".join(chunk)
            url = f"{self.iex_url}/"
            params = {'tickers': tickers_str}
            
            try:
                response = self.session.get(url, headers=self.headers, params=params, timeout=5)
                response.raise_for_status()
                data = response.json() # List of dicts
                
                for item in data:
                    # item: {'ticker': 'AAPL', 'tngoLast': 150.0, 'last': 150.0, ...}
                    sym = item.get('ticker')
                    price = item.get('tngoLast') or item.get('last')
                    if sym and price:
                        results[sym] = float(price)
                        
            except Exception as e:
                logger.error(f"[Tiingo] Snapshot error: {e}")
                
        return results

    def get_news(self, tickers=None, limit=20):
        """
        Fetch news articles.
        """
        url = f"{self.base_url}/news"
        params = {'limit': limit}
        if tickers:
            if isinstance(tickers, list):
                params['tickers'] = ",".join(tickers)
            else:
                params['tickers'] = tickers
                
        try:
            response = self.session.get(url, headers=self.headers, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"[Tiingo] News fetch error: {e}")
            return []

    def get_ticker_meta(self, symbol):
        """
        Fetch ticker metadata (name, exchange, description).
        """
        url = f"{self.base_url}/daily/{symbol}"
        try:
            response = self.session.get(url, headers=self.headers, timeout=5)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"[Tiingo] Meta fetch error for {symbol}: {e}")

    def get_fundamentals_daily(self, ticker: str, start_date=None, end_date=None):
        """
        Fetch daily fundamentals (PE, Market Cap, etc.)
        https://api.tiingo.com/tiingo/fundamentals/<ticker>/daily
        """
        url = f"{self.base_url}/fundamentals/{ticker}/daily"
        params = {}
        if start_date:
            params['startDate'] = start_date.strftime('%Y-%m-%d') if hasattr(start_date, 'strftime') else start_date
        if end_date:
            params['endDate'] = end_date.strftime('%Y-%m-%d') if hasattr(end_date, 'strftime') else end_date
            
        try:
            # Use self.headers for Authorization
            response = self.session.get(url, headers=self.headers, params=params, timeout=10)
            
            if response.status_code in [400, 404]:
                # Common for tickers without fundamental data coverage
                # logger.warning(f"[Tiingo] No fundamentals for {ticker} ({response.status_code})")
                return []
                
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"[Tiingo] Failed to fetch fundamentals for {ticker}: {e}")
            return []

    def get_historical_prices(self, ticker: str, start_date, end_date):
        """
        Fetch OHLCV data.
        """
        return self.get_historical_data(ticker, start_date, end_date)

    def get_fundamentals_meta(self):
        """
        Fetch Bulk Fundamentals Metadata (Sector, Industry).
        https://api.tiingo.com/tiingo/fundamentals/meta
        Returns: Dict { 'AAPL': {'sector': 'Technology', ...}, ... }
        """
        url = f"{self.base_url}/fundamentals/meta"
        try:
            response = self.session.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            data = response.json() # List of dicts
            
            # Convert to optimized dict for lookup
            meta_map = {}
            for item in data:
                tkr = item.get('ticker')
                if tkr:
                    meta_map[tkr] = {
                        'sector': item.get('sector'),
                        'industry': item.get('industry'),
                        'isActive': item.get('isActive')
                    }
            return meta_map
        except Exception as e:
            logger.error(f"[Tiingo] Meta fetch error: {e}")
            return {}
