# home/views.py

import json
import pytz
import requests
import urllib3
import pandas as pd
import yfinance as yf
import feedparser
import re
import re
from .services import get_market_weather, get_gemini_market_weather, get_tiingo_last_price # New import

from functools import lru_cache
from datetime import datetime, time as dtime
import fear_and_greed
from django.shortcuts import render
from django.utils import timezone
from django.http import HttpResponse

def gemini_market_summary(request):
    # Fetch Data for Prompt (Replicated from index view logic or moved to service?)
    # Ideally should be in service to avoid duplication, but for now we can call services directly.
    # To keep it fast, we might need to cache the 'stats' too or just re-fetch (Tiingo/YF are fast enough or cached).
    # Re-fetching stats might slow down the async call slightly but it's background.
    
    # Actually, get_gemini_market_weather handles the data preparation internally if we pass the stats.
    # But wait, get_gemini_market_weather prompt generation logic relies on 'stats' passed to it.
    
    # Let's check get_gemini_market_weather signature: 
    # def get_gemini_market_weather(stats, theme_stats=None, sector_stats=None):
    
    # We need to fetch stats again here.
    # Duplicate logic from index view? Or Refactor?
    # For now, duplicate the fetch logic for simplicity and speed.
    
    # 1. Fetch Key Market Stats (Same as Index)
    # 1. Collect all Tickers
    all_tickers = []
    
    # Macro Assets
    for item in MACRO_ASSETS:
        all_tickers.append(item['tk'])
        
    # Sectors
    for s in SECTOR_ETFS:
        all_tickers.append(s['tk'])
        
    # Themes
    for t in THEMES:
        all_tickers.extend(t['tickers'])
        
    # 2. Batch Fetch
    batch_data = _fetch_batch_data(all_tickers)
    
    # 3. Build 'stats' for Macro Assets
    stats = {}
    for item in MACRO_ASSETS:
        tk = item['tk']
        df = batch_data.get(tk, pd.DataFrame())
        if not df.empty:
            latest = df['close'].iloc[-1]
            prev = df['close'].iloc[-2] if len(df) > 1 else latest
            pct = (latest - prev) / prev * 100 if prev != 0 else 0
        else:
            latest = 0
            pct = 0
        stats[tk] = {'price': latest, 'pct': pct}
        
    # 4. Build 'sector_stats' list
    sector_stats_list = []
    # Language Selection Logic (Early Check)
    user_lang = request.LANGUAGE_CODE if hasattr(request, 'LANGUAGE_CODE') else 'ko'

    for s in SECTOR_ETFS:
        tk = s['tk']
        df = batch_data.get(tk, pd.DataFrame())
        
        # Determine Display Name based on Language
        display_name = s['title']
        if user_lang == 'ko':
            display_name = s.get('title_ko', s['title'])

        if not df.empty:
            latest = df['close'].iloc[-1]
            prev = df['close'].iloc[-2] if len(df) > 1 else latest
            pct = (latest - prev) / prev * 100 if prev != 0 else 0
            
            sector_stats_list.append({
                'name': display_name,
                'change': f"{pct:+.2f}%"
            })
            
    # 5. Build 'theme_stats' list
    theme_stats_list = []
    for t in THEMES:
        tickers = t['tickers']
        total_pct = 0
        count = 0
        
        # Determine Display Name based on Language
        display_name = t['title']
        if user_lang == 'ko':
            display_name = t.get('title_ko', t['title'])

        for tk in tickers:
            df = batch_data.get(tk, pd.DataFrame())
            if not df.empty:
                latest = df['close'].iloc[-1]
                prev = df['close'].iloc[-2] if len(df) > 1 else latest
                pct = (latest - prev) / prev * 100 if prev != 0 else 0
                total_pct += pct
                count += 1
        
        if count > 0:
            avg_pct = total_pct / count
            theme_stats_list.append({
                'name': display_name, # CHANGED from 'id' to 'name' to match template
                'change': f"{avg_pct:+.2f}%"
            })
    
    gemini_summary_data = get_gemini_market_weather(stats, theme_stats_list, sector_stats_list)
    
    # Language Selection Logic
    user_lang = request.LANGUAGE_CODE if hasattr(request, 'LANGUAGE_CODE') else 'ko'
    # Default to Korean if English not forced, or stick to detected. 
    # Usually request.LANGUAGE_CODE is 'ko' or 'en'.
    
    gemini_summary = {}
    if gemini_summary_data:
        # Get the specific language dict (default to English if missing)
        summary_content = gemini_summary_data.get(user_lang, gemini_summary_data.get('en', {}))
        
        # If explicitly checking for 'en' fallback if 'ko' is empty
        if not summary_content and user_lang == 'ko':
            summary_content = gemini_summary_data.get('en', {})
            
        if summary_content:
            gemini_summary = summary_content.copy()
            # Restore metadata if needed (e.g. last_updated)
            gemini_summary['last_updated'] = gemini_summary_data.get('last_updated')
            
            # OVERRIDE LLM Data with Actual Data for Precision
            # The User requested actual red/green numbers, and LLM sometimes hallucinates or formats poorly.
            # We already calculated accurate stats above.
            
            # Sort Sectors by Performance (Best to Worst)
            sorted_sectors = sorted(sector_stats_list, key=lambda x: float(x['change'].strip('%').replace('+','')), reverse=True)
            gemini_summary['sectors'] = sorted_sectors
            
            # Sort Themes by Performance
            sorted_themes = sorted(theme_stats_list, key=lambda x: float(x['change'].strip('%').replace('+','')), reverse=True)
            gemini_summary['themes'] = sorted_themes

    context = {
        'gemini_summary': gemini_summary,
        'now': timezone.now()
    }
    return render(request, 'home/partials/gemini_summary.html', context)

import requests
import math
import logging
logger = logging.getLogger(__name__)


# -----------------------------------------
# TIMEZONES
# -----------------------------------------
US_TZ = pytz.timezone("America/New_York")


# -----------------------------------------
# INDEX / ASSET LIST  (아이콘 + 색 + 그룹)
# -----------------------------------------
INDEXES = [
    {"tk": "^GSPC",      "title": "S&P 500", "title_ko": "S&P 500", "color": "#2563eb", "icon": "bi bi-activity", "asset": "equity"},
    {"tk": "^IXIC",      "title": "Nasdaq",  "title_ko": "나스닥", "color": "#7c3aed", "icon": "bi bi-laptop", "asset": "equity"},
    {"tk": "^DJI",       "title": "Dow Jones", "title_ko": "다우존스", "color": "#f97316", "icon": "bi bi-building", "asset": "equity"},
    {"tk": "^RUT",       "title": "Russell 2000", "title_ko": "러셀 2000", "color": "#0891b2", "icon": "bi bi-diagram-3", "asset": "equity"},

    {"tk": "BTC-USD",    "title": "Bitcoin", "title_ko": "비트코인", "color": "#f97316", "icon": "bi bi-currency-bitcoin", "asset": "crypto"},
    {"tk": "^KS11",      "title": "KOSPI",   "title_ko": "코스피", "color": "#10b981", "icon": "bi bi-globe-asia-australia", "asset": "equity"},
    {"tk": "USDKRW=X",   "title": "USD/KRW", "title_ko": "원/달러 환율", "color": "#f59e0b", "icon": "bi bi-cash-coin", "asset": "fx"},
    {"tk": "GC=F",       "title": "Gold",    "title_ko": "금", "color": "#eab308", "icon": "bi bi-stop-circle", "asset": "commodity"},

    {"tk": "^TNX",       "title": "10Y Yield", "title_ko": "미 10년물 국채", "color": "#0ea5e9", "icon": "bi bi-bank", "asset": "rate"},
    {"tk": "CL=F",       "title": "WTI Crude", "title_ko": "WTI 원유", "color": "#fb923c", "icon": "bi bi-droplet-fill", "asset": "commodity"},
    
    {"tk": "^VIX",       "title": "VIX",     "title_ko": "VIX 변동성", "color": "#475569", "icon": "bi bi-exclamation-triangle", "asset": "equity"},
    {"tk": "DX-Y.NYB",   "title": "US Dollar", "title_ko": "달러 인덱스", "color": "#84cc16", "icon": "bi bi-currency-dollar", "asset": "fx"},
]

# New Comprehensive Macro List matching user request
MACRO_ASSETS = [
    # US Indices (Preferred display order)
    {"tk": "^GSPC", "title": "S&P 500", "category": "US Indices", "icon": "bi bi-activity", "color": "#2563eb"},
    {"tk": "^IXIC", "title": "Nasdaq", "category": "US Indices", "icon": "bi bi-laptop", "color": "#7c3aed"},
    {"tk": "^DJI", "title": "Dow Jones", "category": "US Indices", "icon": "bi bi-building", "color": "#f97316"},
    {"tk": "^RUT", "title": "Russell 2000", "category": "US Indices", "icon": "bi bi-diagram-3", "color": "#0891b2"},
    {"tk": "^VIX", "title": "VIX", "category": "US Indices", "icon": "bi bi-activity", "color": "#ef4444"},

    # Global Indices (Flag Emojis)
    {"tk": "^N225", "title": "Nikkei 225", "category": "Global", "icon": "🇯🇵", "color": "#ef4444"},
    {"tk": "^HSI", "title": "Hang Seng", "category": "Global", "icon": "🇭🇰", "color": "#f97316"},
    {"tk": "^STOXX50E", "title": "Euro Stoxx 50", "category": "Global", "icon": "🇪🇺", "color": "#3b82f6"},
    {"tk": "000001.SS", "title": "Shanghai Comp", "category": "Global", "icon": "🇨🇳", "color": "#ef4444"},
    {"tk": "^KS11", "title": "KOSPI", "category": "Global", "icon": "🇰🇷", "color": "#10b981"},

    # Key Rates & Bonds (Unified Icon)
    {"tk": "^TNX", "title": "10Y T-Note", "category": "Rates", "icon": "bi bi-cash-stack", "color": "#0ea5e9"},
    {"tk": "^TYX", "title": "30Y T-Bond", "category": "Rates", "icon": "bi bi-cash-stack", "color": "#0284c7"},
    {"tk": "^FVX", "title": "5Y T-Note", "category": "Rates", "icon": "bi bi-cash-stack", "color": "#38bdf8"},
    {"tk": "^IRX", "title": "13W T-Bill", "category": "Rates", "icon": "bi bi-cash-stack", "color": "#0284c7"},

    # Currencies
    {"tk": "DX-Y.NYB", "title": "Dollar Index", "category": "Currencies", "icon": "bi bi-currency-dollar", "color": "#84cc16"},
    {"tk": "EURUSD=X", "title": "Euro/USD", "category": "Currencies", "icon": "bi bi-currency-euro", "color": "#3b82f6"},
    {"tk": "JPY=X", "title": "USD/JPY", "category": "Currencies", "icon": "bi bi-currency-yen", "color": "#ef4444"},
    {"tk": "CNY=X", "title": "USD/CNY", "category": "Currencies", "icon": "bi bi-currency-exchange", "color": "#f97316"},

    # Commodities (Top 4)
    {"tk": "GC=F", "title": "Gold", "category": "Commodities", "icon": "bi bi-stop-circle", "color": "#eab308"},
    {"tk": "SI=F", "title": "Silver", "category": "Commodities", "icon": "bi bi-stop-circle", "color": "#94a3b8"},
    {"tk": "HG=F", "title": "Copper", "category": "Commodities", "icon": "bi bi-circle", "color": "#f97316"},
    {"tk": "CL=F", "title": "WTI Crude", "category": "Commodities", "icon": "bi bi-droplet-fill", "color": "#f97316"},
    # {"tk": "NG=F", "title": "Natural Gas", "category": "Commodities", "icon": "bi bi-droplet", "color": "#3b82f6"},

    # Crypto -- Restored
    {"tk": "BTC-USD", "title": "Bitcoin", "category": "Crypto", "icon": "bi bi-currency-bitcoin", "color": "#f97316"},
    {"tk": "ETH-USD", "title": "Ethereum", "category": "Crypto", "icon": "bi bi-currency-exchange", "color": "#6366f1"},

]

# -----------------------------------------
# MARKET THEMES (6개)
# -----------------------------------------
# -----------------------------------------
# MARKET THEMES (AI, 반도체, 에너지, 퀀텀, 크립토, 메가테크)
# -----------------------------------------
THEMES = [
    {
        "id": "theme_ai",
        "title": "AI Leaders",
        "title_ko": "AI 주도주",
        "subtitle": "NVDA · AMD · GOOG · AMZN · MSFT · PLTR",
        "tickers": ["NVDA", "AMD", "GOOG", "AMZN", "MSFT", "PLTR"],
        "base_colors": ["#a855f7", "#c084fc", "#d946ef", "#8b5cf6", "#6366f1", "#4f46e5"],
    },
    {
        "id": "theme_semi",
        "title": "Semiconductors",
        "title_ko": "반도체",
        "subtitle": "NVDA · AMD · TSM · AVGO · INTC",
        "tickers": ["NVDA", "AMD", "TSM", "AVGO", "INTC"],
        "base_colors": ["#22c55e", "#4ade80", "#16a34a", "#15803d", "#166534"],
    },
    {
        "id": "theme_energy",
        "title": "Energy",
        "title_ko": "에너지",
        "subtitle": "XLE · CL=F · SMR · OKLO·  CCJ·  CEG",
        "tickers": ["XLE", "CL=F", "SMR","OKLO","CCJ","CEG"],
        "base_colors": ["#fb923c", "#f97316"],
    },
    {
        "id": "theme_quantum",
        "title": "Quantum",
        "title_ko": "양자컴퓨팅",
        "subtitle": "IONQ · RGTI · QUBT · QBTS · IBM · GOOG",
        "tickers": ["IONQ", "RGTI", "QUBT", "QBTS", "IBM", "GOOG"],
        "base_colors": ["#0ea5e9", "#22d3ee", "#38bdf8", "#0284c7", "#0369a1", "#0f766e"],
    },
    {
        "id": "theme_crypto",
        "title": "Crypto Related",
        "title_ko": "가상화폐 관련주",
        "subtitle": "COIN · BTC-USD · MSTR",
        "tickers": ["COIN", "BTC-USD", "MSTR"],
        "base_colors": ["#facc15", "#eab308", "#f59e0b"],
    },
    {
        "id": "theme_megatech",
        "title": "Mega Tech",
        "title_ko": "메가테크",
        "subtitle": "AAPL · MSFT · AMZN · TSLA · META · GOOG",
        "tickers": ["AAPL", "MSFT", "AMZN", "TSLA", "META", "GOOG"],
        "base_colors": ["#3b82f6", "#2563eb", "#1d4ed8", "#38bdf8", "#0ea5e9", "#4f46e5"],
    },
]
COLOR_PALETTE = [
    "#ef4444",  # red
    "#22c55e",  # green
    "#3b82f6",  # blue
    "#eab308",  # yellow
    "#a855f7",  # purple
    "#14b8a6",  # teal
    "#f97316",  # orange
    "#ec4899",  # pink
    "#6366f1",  # indigo
    "#84cc16",  # lime
    "#06b6d4",  # cyan
    "#f59e0b",  # amber
]

# -----------------------------------------
# SECTOR ETFS
# -----------------------------------------
SECTOR_ETFS = [
    {"tk": "XLK", "title": "Technology", "title_ko": "기술주"},
    {"tk": "XLI", "title": "Industrials", "title_ko": "산업재"},
    {"tk": "XLC", "title": "Comm. Services", "title_ko": "통신서비스"},
    {"tk": "XLF", "title": "Financials", "title_ko": "금융"},
    {"tk": "XLY", "title": "Cons. Discretionary", "title_ko": "임의소비재"},
    {"tk": "XLRE", "title": "Real Estate", "title_ko": "부동산"},
    {"tk": "XLV", "title": "Health Care", "title_ko": "헬스케어"},
    {"tk": "XLP", "title": "Cons. Staples", "title_ko": "필수소비재"},
    {"tk": "XLU", "title": "Utilities", "title_ko": "유틸리티"},
    {"tk": "XLB", "title": "Materials", "title_ko": "소재"},
    {"tk": "XLE", "title": "Energy", "title_ko": "에너지"},
]

def _color_for_ticker(ticker: str) -> str:
    """
    티커 문자열로부터 항상 동일한 색을 결정.
    (hash 느낌으로 팔레트 인덱스 선택)
    """
    s = sum(ord(c) for c in ticker)
    idx = s % len(COLOR_PALETTE)
    return COLOR_PALETTE[idx]

# -----------------------------------------
# DATA LOADER
# -----------------------------------------
@lru_cache(maxsize=64)
def _ytd_series(ticker: str) -> pd.DataFrame:
    """YTD prices for charts."""
    df = yf.download(
        ticker,
        period="ytd",
        interval="1d",
        auto_adjust=True,
        progress=False,
        threads=False,
    )

    if df.empty:
        return pd.DataFrame({"close": []})

    # MultiIndex → 단일 Close
    if isinstance(df.columns, pd.MultiIndex):
        if "Close" in df.columns.get_level_values(0):
            df = df["Close"]
            if isinstance(df, pd.DataFrame):
                df = df.iloc[:, 0]
    else:
        df = df["Close"] if "Close" in df else df.iloc[:, 0]

    return pd.DataFrame({"close": df.dropna()})


# -----------------------------------------
# Fear & Greed Index
# -----------------------------------------
def get_fear_greed():
    try:
        fear_greed_data = fear_and_greed.get()

    # Access the data
        value = int(fear_greed_data.value)
        label = fear_greed_data.description
        last_updated = fear_greed_data.last_update
        if label == "extreme greed":
            label = "Extreme Greed 😃"
        elif label == "greed":
            label = "Greed 🙂"
        elif label == "neutral":
            label = "Neutral 😐"
        elif label == "fear":
            label = "Fear 😨"
        else:
            label = "Extreme Fear 😱"


        # Convert to EST
        if isinstance(last_updated, datetime):
            est_tz = pytz.timezone('US/Eastern')
            if last_updated.tzinfo is None:
                last_updated = pytz.utc.localize(last_updated) # Assume UTC if naive
            last_updated = last_updated.astimezone(est_tz).strftime("%Y-%m-%d %I:%M %p EST")
        
        return {"value": value, "label": label, "last_updated":last_updated}

    except Exception as e:
        logger.warning("Fear & Greed fetch failed: %s", e)
        # 0 말고 None으로 두고, 템플릿에서 '데이터 오류'로 표시
        return {"value": None, "label": "데이터 오류"}















# -----------------------------------------
# 글로벌 뉴스 10개
# -----------------------------------------







# -----------------------------------------
# Market Summary (language-aware)
# -----------------------------------------
def generate_market_summary(stats, lang='ko'):
    """
    Generate market summary in Korean or English based on lang parameter.
    lang: 'ko' for Korean (default), 'en' for English
    """
    spx   = stats["^GSPC"]["pct"]
    ndx   = stats["^IXIC"]["pct"]
    vix   = stats["^VIX"]["pct"]
    tnx   = stats["^TNX"]["pct"]
    wti   = stats["CL=F"]["pct"]
    gold  = stats["GC=F"]["pct"]
    kospi = stats["^KS11"]["pct"]
    btc   = stats["BTC-USD"]["pct"]

    lines = []

    if lang == 'en':
        # English version
        if spx > 0.5 and ndx > 0.5:
            lines.append("US equities are showing a clear risk-on trend with both S&P 500 and Nasdaq rising together.")
        elif spx < -0.5 and ndx < -0.5:
            lines.append("S&P 500 and Nasdaq are both declining, indicating a risk-off sentiment across the market.")
        else:
            lines.append("US markets are mixed with diverging performance across indices and sectors.")

        if vix > 5:
            lines.append("VIX is rising, signaling heightened volatility and increased caution.")
        elif vix < -5:
            lines.append("VIX is declining, suggesting a stable volatility environment in the near term.")

        if tnx > 0.1:
            lines.append("The 10-year Treasury yield is rising, which could pressure growth stocks and high-valuation names.")
        elif tnx < -0.1:
            lines.append("The 10-year yield is falling, creating a supportive backdrop for tech and long-duration growth stocks.")

        if wti > 1.0:
            lines.append("WTI crude oil is rising, potentially benefiting the energy sector.")
        elif wti < -1.0:
            lines.append("Oil prices are declining, which could weigh on energy stocks but benefit consumer and airline sectors.")

        if gold > 0.7:
            lines.append("Gold is rising as safe-haven demand picks up.")
        elif gold < -0.7:
            lines.append("Gold is weakening, suggesting renewed appetite for risk assets.")

        if kospi < -1.0:
            lines.append("KOSPI is underperforming significantly, reflecting weak sentiment toward Asian risk assets.")
        elif kospi > 1.0:
            lines.append("KOSPI is holding up well, indicating solid momentum in Asian risk assets.")

        if btc > 2.0:
            lines.append("Bitcoin is surging, reflecting strong appetite for high-risk assets.")
        elif btc < -2.0:
            lines.append("Bitcoin is pulling back, as caution toward speculative assets increases.")

        if not lines:
            lines.append("Markets are showing limited volatility with no clear directional bias across indices, rates, and commodities.")
    else:
        # Korean version (original)
        if spx > 0.5 and ndx > 0.5:
            lines.append("미국 주식시장은 S&P500과 나스닥이 동반 상승하며 뚜렷한 리스크 온 흐름을 보이고 있습니다.")
        elif spx < -0.5 and ndx < -0.5:
            lines.append("S&P500과 나스닥이 모두 하락하며 전반적인 리스크 오프 분위기가 형성되어 있습니다.")
        else:
            lines.append("미국 주식시장은 지수 간 온도 차가 있는 혼조세입니다. 업종·테마별로 성과가 갈리는 장입니다.")

        if vix > 5:
            lines.append("VIX가 상승하면서 변동성 확대에 대한 경계심이 높아지고 있습니다.")
        elif vix < -5:
            lines.append("VIX가 하락세를 이어가며 단기적으로는 안정적인 변동성 환경이 이어지고 있습니다.")

        if tnx > 0.1:
            lines.append("미 10년물 국채 금리가 상승하며 성장주와 고밸류에이션 종목에는 부담 요인이 되고 있습니다.")
        elif tnx < -0.1:
            lines.append("10년물 금리가 하락하면서 기술주와 장기 성장주에는 우호적인 환경입니다.")

        if wti > 1.0:
            lines.append("WTI 유가가 상승하면서 에너지 섹터가 상대적인 강세를 보일 가능성이 있습니다.")
        elif wti < -1.0:
            lines.append("유가 하락으로 에너지 섹터에는 부담이, 소비·항공 등에는 안도 요인이 될 수 있습니다.")

        if gold > 0.7:
            lines.append("금 가격이 오르며 안전자산 수요가 다소 유입되는 모습입니다.")
        elif gold < -0.7:
            lines.append("금 가격이 약세를 보이며 위험자산 선호가 다시 강화되는 흐름입니다.")

        if kospi < -1.0:
            lines.append("KOSPI가 상대적으로 크게 밀리며 아시아 위험자산에 대한 투자심리는 약한 편입니다.")
        elif kospi > 1.0:
            lines.append("KOSPI가 견조한 흐름을 보이며 아시아 위험자산도 무난한 분위기입니다.")

        if btc > 2.0:
            lines.append("비트코인이 강하게 오르며 고위험 자산 선호가 강화되는 모습입니다.")
        elif btc < -2.0:
            lines.append("비트코인이 조정을 받으며 투기적 자산에 대한 경계심이 나타나고 있습니다.")

        if not lines:
            lines.append("지수·금리·원자재 모두 큰 방향성 없이 제한적인 변동성을 보이는 하루입니다.")

    return " ".join(lines)




# -----------------------------------------
# MAIN VIEW
# -----------------------------------------
# -----------------------------------------
# BATCH DATA LOADER (Optimized)
# -----------------------------------------
def _fetch_batch_data(tickers: list) -> dict:
    """
    Fetch YTD data for ALL tickers in a single request.
    Returns a dict: { 'AAPL': pd.DataFrame(columns=['close']), ... }
    """
    if not tickers:
        return {}
        
    unique_tickers = list(set(tickers))
    
    try:
        # Download all at once
        data = yf.download(
            unique_tickers,
            period="ytd",
            interval="1d",
            auto_adjust=True,
            progress=False,
            threads=True,
            group_by='ticker'
        )
        
        result = {}
        
        # If only one ticker, yfinance might return flat OR MultiIndex depending on version/args
        if len(unique_tickers) == 1:
            tk = unique_tickers[0]
            
            # Check if data has the ticker as a column level (MultiIndex)
            if isinstance(data.columns, pd.MultiIndex) and tk in data.columns:
                df = data[tk]
            elif isinstance(data.columns, pd.MultiIndex) and tk in data.columns.levels[0]:
                 df = data[tk]
            else:
                # Assume flat
                df = data
                
            if "Close" in df.columns:
                # Handle if Close is a DataFrame (rare but possible with duplicates) or Series
                close_data = df["Close"]
                if isinstance(close_data, pd.DataFrame):
                    close_data = close_data.iloc[:, 0]
                    
                clean_df = pd.DataFrame({"close": close_data})
                result[tk] = clean_df.dropna()
            return result

        # MultiIndex handling
        for tk in unique_tickers:
            try:
                # Access ticker data from MultiIndex
                if tk in data.columns.levels[0]:
                    df = data[tk]
                    if "Close" in df.columns:
                        clean_df = pd.DataFrame({"close": df["Close"]})
                        result[tk] = clean_df.dropna()
                    else:
                        result[tk] = pd.DataFrame()
                else:
                    result[tk] = pd.DataFrame()
            except Exception:
                result[tk] = pd.DataFrame()
                
        return result
        
    except Exception as e:
        logger.error(f"Batch download failed: {e}")
        return {}

# -----------------------------------------
# MAIN VIEW
# -----------------------------------------
def index(request):
    asset_cards = []
    chart_data = []
    stats = {}

    # 1. Collect ALL tickers
    all_tickers = []
    
    # Indices
    for m in INDEXES:
        all_tickers.append(m["tk"])
        
    # Sectors
    for s in SECTOR_ETFS:
        all_tickers.append(s["tk"])
        
    # Themes
    for theme in THEMES:
        all_tickers.extend(theme["tickers"])
        
    # 2. Batch Fetch
    batch_data = _fetch_batch_data(all_tickers)

    # 3. Process Indices (Top Cards & Charts)
    for m in INDEXES:
        tk = m["tk"]
        df = batch_data.get(tk, pd.DataFrame())

        if df.empty:
            latest = 0
            pct = 0
        else:
            latest = df["close"].iloc[-1]
            prev = df["close"].iloc[-2] if len(df) > 1 else latest
            pct = (latest - prev) / prev * 100 if prev != 0 else 0

        stats[tk] = {"price": latest, "pct": pct}

        # Card Data
        asset_cards.append({
            "title": m["title"],
            "icon": m["icon"],
            "color": m["color"],
            "price": latest,
            "pct": pct,
        })

        # Chart Data
        labels = [i.strftime("%Y-%m-%d") for i in df.index] if not df.empty else []
        values = df["close"].tolist() if not df.empty else []

        chart_data.append({
            "id": f"chart_{tk.replace('^','').replace('=','').replace('-','')}",
            "title": m["title_ko"] if request.LANGUAGE_CODE == 'ko' and "title_ko" in m else m["title"],
            "color": m["color"],
            "labels": labels,
            "data": values,
        })

    # 4. Process Sectors
    sector_stats = {}
    for s in SECTOR_ETFS:
        tk = s["tk"]
        df = batch_data.get(tk, pd.DataFrame())
        
        if not df.empty:
            latest = df["close"].iloc[-1]
            prev = df["close"].iloc[-2] if len(df) > 1 else latest
            pct = (latest - prev) / prev * 100 if prev != 0 else 0
            sector_stats[s["title"]] = pct

    # Top Performing Sector
    top_sector = None
    if sector_stats:
        best_sector = max(sector_stats, key=sector_stats.get)
        top_sector = {
            "title": best_sector,
            "pct": sector_stats[best_sector],
            "color": "#10b981" if sector_stats[best_sector] >= 0 else "#ef4444"
        }

    # 5. Process Themes
    theme_stats = {}
    theme_charts = []
    
    for theme in THEMES:
        tickers = theme["tickers"]
        
        # Stats
        total_pct = 0
        count = 0
        for tk in tickers:
            if tk in stats: # If in stats (indices)
                total_pct += stats[tk]["pct"]
                count += 1
            else: # Calculate from batch data
                df = batch_data.get(tk, pd.DataFrame())
                if not df.empty:
                    latest = df["close"].iloc[-1]
                    prev = df["close"].iloc[-2] if len(df) > 1 else latest
                    pct = (latest - prev) / prev * 100 if prev != 0 else 0
                    total_pct += pct
                    count += 1
                    
        if count > 0:
            theme_stats[theme["title"]] = total_pct / count
            
        # Charts
        series_list = []
        all_index = None
        
        for tk in tickers:
            df = batch_data.get(tk, pd.DataFrame())
            if df.empty: continue
            
            s = df["close"].copy()
            if s.iloc[0] == 0: continue
            
            norm = (s / s.iloc[0]) * 100.0
            norm.name = tk
            series_list.append(norm)
            all_index = norm.index if all_index is None else all_index.union(norm.index)
            
        if series_list and all_index is not None:
             # Align
            aligned = [s.reindex(all_index).ffill() for s in series_list]
            df_all = pd.concat(aligned, axis=1)
            
            labels = [d.strftime("%Y-%m-%d") for d in all_index]
            datasets = []
            
            for col in df_all.columns:
                data = [round(float(v), 1) if pd.notna(v) else None for v in df_all[col].tolist()]
                color = _color_for_ticker(col)
                datasets.append({
                    "label": col,
                    "data": data,
                    "color": color,
                })
                
            theme_charts.append({
                "id": theme["id"],
                "title": theme["title"],
                "subtitle": theme.get("subtitle", ""),
                "labels": labels,
                "datasets": datasets,
            })

    # 6. Macro Assets Data
    macro_stats = {}
    for item in MACRO_ASSETS:
        tk = item['tk']
        # Replace spaces in category with underscores for template compatibility
        cat = item['category'].replace(" ", "_")
        if cat not in macro_stats: macro_stats[cat] = []
        
        price = 0.0
        pct = 0.0
        
        # Check if already fetched in stats (Global Dashboard)
        if tk in stats:
            # Reuse YFinance data
            price = stats[tk].get('price', 0.0)
            pct = stats[tk].get('pct', 0.0)
        else:
            # 1. Try Tiingo API first (as requested)
            t_price, t_pct = get_tiingo_last_price(tk)
            
            if t_price is not None and t_price > 0:
                price = t_price
                pct = t_pct
            else:
                # 2. Fallback to YFinance on the fly if Tiingo fails
                try:
                    ticker = yf.Ticker(tk)
                    # Try fast_info first
                    if hasattr(ticker, 'fast_info') and 'last_price' in ticker.fast_info:
                        price = ticker.fast_info['last_price'] or 0.0
                        prev = ticker.fast_info['previous_close'] or price
                        if prev > 0:
                             pct = ((price - prev) / prev) * 100
                    
                    # If fast_info failed or 0, try history
                    if price == 0:
                        hist = ticker.history(period="5d")
                        if not hist.empty:
                            price = hist["Close"].iloc[-1]
                            prev = hist["Close"].iloc[-2] if len(hist) > 1 else price
                            if prev > 0:
                                pct = ((price - prev) / prev) * 100
                except Exception as e:
                    logger.error(f"Macro fallback failed for {tk}: {e}")

        macro_stats[cat].append({
            "title": item['title'],
            "price": price,
            "pct": pct,
            "tk": tk,
            "icon": item.get("icon", "bi bi-activity"), 
            "color": item.get("color", "#64748b") 
        })

    # 7. Other Data
    fg = get_fear_greed()
    
    # Market Summary
    user_lang = request.LANGUAGE_CODE if hasattr(request, 'LANGUAGE_CODE') else 'ko'
    market_summary = generate_market_summary(stats, lang=user_lang)
    
    # 3. Market Weather
    weather = get_market_weather(stats) # This was already called above, ensuring it's available.
    
    # 4. Fear & Greed Index
    fg_index = get_fear_greed()

    context = {
        "asset_cards": asset_cards,
        "charts": chart_data,
        "charts_json": json.dumps(chart_data),
        "stats": stats,
        "macro_stats": macro_stats,
        "top_sector": top_sector,
        "fg": fg,
        "market_summary": market_summary,
        "weather": weather,
        # "gemini_summary": gemini_summary, # Removed: Loaded Async
        "theme_charts": theme_charts,
        "theme_charts_json": json.dumps(theme_charts),
        "now": timezone.now(),
    }

    return render(request, "home/index.html", context)

# -----------------------------------------
# THEME CHART BUILDER
# -----------------------------------------

def _build_theme_charts() -> list[dict]:
    """THEMES 정의를 기반으로 100 기준 상대지수 차트 payload 생성."""
    theme_charts: list[dict] = []

    for theme in THEMES:
        tickers = theme["tickers"]
        series_list = []
        all_index = None

        # 1) 각 티커별 YTD 시계열 다운 + 100 기준으로 normalize
        for tk in tickers:
            df = _ytd_series(tk)
            if df.empty:
                continue

            s = df["close"].copy()
            if s.iloc[0] == 0:
                continue

            norm = (s / s.iloc[0]) * 100.0
            norm.name = tk

            series_list.append(norm)
            all_index = norm.index if all_index is None else all_index.union(norm.index)

        if not series_list or all_index is None:
            continue

        # 2) 인덱스 align + forward-fill
        aligned = []
        for s in series_list:
            aligned.append(s.reindex(all_index).ffill())
        df_all = pd.concat(aligned, axis=1)

        labels = [d.strftime("%Y-%m-%d") for d in all_index]

        # 3) Chart.js datasets 구조 만들기
        datasets = []
        for col in df_all.columns:
            data = [
                round(float(v), 1) if pd.notna(v) else None
                for v in df_all[col].tolist()
            ]

            # ✅ 테마 base_colors 무시하고, 티커 기준으로 색 결정
            color = _color_for_ticker(col)

            datasets.append(
                {
                    "label": col,
                    "data": data,
                    "color": color,
                }
            )

        theme_charts.append(
            {
                "id": theme["id"],
                "title": theme["title"],
                "subtitle": theme.get("subtitle", ""),
                "labels": labels,
                "datasets": datasets,
            }
        )

    return theme_charts

