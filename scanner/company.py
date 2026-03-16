# scanner/company.py

import functools
import yfinance as yf
import time

# 캐시 크기를 늘려서 반복 호출 시 속도 향상
@functools.lru_cache(maxsize=4096)
def get_company_profile(symbol: str) -> dict:
    """
    yfinance를 통해 기업 정보(이름, 섹터, 산업) 및 핵심 재무 지표(P/E, EPS, 부채비율)를 가져옵니다.
    """
    symbol = (symbol or "").upper().strip()
    if not symbol:
        return {}

    # 기본값 설정
    data = {
        "company": symbol,
        "sector": "",
        "industry": "",
        "market_cap": None,
        "pe_ratio": None,
        "eps": None,
        "debt_equity": None
    }

    try:
        tk = yf.Ticker(symbol)
        
        # 1. Fast Info 시도 (시가총액 등 빠른 데이터)
        try:
            if hasattr(tk, "fast_info"):
                fi = tk.fast_info
                if hasattr(fi, "market_cap"):
                    data["market_cap"] = fi.market_cap
        except:
            pass

        # 2. Full Info 시도 (P/E, EPS, Sector 등은 여기에 있음)
        # yfinance가 차단할 수 있으므로 약간의 딜레이가 필요할 수 있음 (외부 호출 시 제어)
        info = tk.info
        
        if info:
            # 기본 정보
            data["company"] = info.get("shortName") or info.get("longName") or symbol
            data["sector"] = info.get("sector") or ""
            data["industry"] = info.get("industry") or ""
            
            # 재무 지표 (키 값이 없을 수도 있으므로 get 사용)
            # trailingPE: PER (주가수익비율)
            # trailingEps: EPS (주당순이익)
            # debtToEquity: 부채비율 (보통 백분율이 아닌 소수점이나 정수로 옴)
            data["pe_ratio"] = info.get("trailingPE") or info.get("forwardPE")
            data["eps"] = info.get("trailingEps") or info.get("forwardEps")
            data["debt_equity"] = info.get("debtToEquity")
            
            # info에 marketCap이 있다면 fast_info보다 우선 사용 (가끔 더 정확함)
            if info.get("marketCap"):
                data["market_cap"] = info.get("marketCap")

    except Exception as e:
        # 로그를 남겨서 어떤 에러인지 확인하면 좋음 (운영 환경에서는 logger 사용 권장)
        # print(f"[get_company_profile] Error fetching {symbol}: {e}")
        pass

    return data

def get_financials_for_ai(symbol: str) -> dict:
    """
    AI 리포트 생성을 위한 상세 재무 데이터 가져오기
    """
    symbol = (symbol or "").upper().strip()
    if not symbol:
        return {}
    
    data = {}
    try:
        tk = yf.Ticker(symbol)
        info = tk.info
        
        if info:
            # Valuation
            data['trailingPE'] = info.get('trailingPE')
            data['forwardPE'] = info.get('forwardPE')
            data['priceToBook'] = info.get('priceToBook')
            data['bookValue'] = info.get('bookValue')
            
            # Earnings
            data['totalRevenue'] = info.get('totalRevenue')
            data['revenueGrowth'] = info.get('revenueGrowth')
            data['operatingIncome'] = info.get('operatingIncome')
            data['earningsQuarterlyGrowth'] = info.get('earningsQuarterlyGrowth')
            data['mostRecentQuarter'] = info.get('mostRecentQuarter') # Timestamp
            
            # Health
            data['totalCash'] = info.get('totalCash')
            data['totalDebt'] = info.get('totalDebt')
            data['debtToEquity'] = info.get('debtToEquity')
            data['operatingMargins'] = info.get('operatingMargins')
            
            # Wall St
            data['targetMeanPrice'] = info.get('targetMeanPrice')
            data['recommendationKey'] = info.get('recommendationKey')
            
    except Exception as e:
        print(f"Error fetching financials for {symbol}: {e}")
        
    return data