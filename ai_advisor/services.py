# ai_advisor/services.py

import os
import json
import re
from google import genai
from updatedata.models import Ticker

MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

def _client():
    key = os.getenv("GEMINI2_API_KEY")
    return genai.Client(api_key=key) if key else None

def _get_market_context() -> str:
    try:
        top_stocks = Ticker.objects.filter(is_active=True).order_by('-market_cap')[:5]
        info = [f"{t.symbol}" for t in top_stocks]
        return ", ".join(info)
    except:
        return ""

# 스키마 정의 (asset_class 필수)
SCHEMA = (
    '{'
    '"allocation": {'
        '"US_Stocks": number, '
        '"Intl_Stocks": number, '
        '"Bonds": number, '
        '"Commodities_Gold": number, '
        '"Cash": number'
    '}, '
    '"portfolio": ['
        '{'
            '"ticker": string, '
            '"name": string, '
            '"asset_class": string, ' 
            '"weight": number, '
            '"rationale": string'
        '}'
    '], '
    '"strategy_name": string, '
    '"analysis_report": string'
    '}'
)

def _build_prompt(profile, market_context):
    """
    Builds prompt for portfolio recommendations with language detection
    """
    from django.utils.translation import get_language
    from .prompts import get_portfolio_prompt
    
    lang_code = get_language()
    language = 'en' if lang_code == 'en' else 'ko'
    
    return get_portfolio_prompt(profile, market_context, SCHEMA, language=language)

def _extract_pure_json(text: str) -> dict:
    """
    AI 응답에서 가장 바깥쪽 중괄호 {}를 찾아 JSON만 추출하는 강력한 함수
    """
    try:
        text = text.strip()
        # 1. 가장 처음 나오는 '{' 찾기
        start_idx = text.find('{')
        # 2. 가장 마지막에 나오는 '}' 찾기
        end_idx = text.rfind('}')
        
        if start_idx == -1 or end_idx == -1:
            raise ValueError("No JSON brackets found")
            
        # 3. 그 사이 문자열만 추출
        json_str = text[start_idx : end_idx + 1]
        return json.loads(json_str, strict=False)
    except Exception as e:
        print(f"[JSON Parse Error] {e}")
        return None

def generate_portfolio(profile) -> dict:
    # ▼▼▼ [수정] 템플릿과 키 이름 일치시키기 ('type' -> 'asset_class') ▼▼▼
    fallback_data = {
        "allocation": {"US_Stocks": 50, "Intl_Stocks": 10, "Bonds": 30, "Commodities_Gold": 5, "Cash": 5},
        "portfolio": [
            {"ticker": "VTI", "name": "Vanguard Total Stock", "asset_class": "US Equity", "weight": 50, "rationale": "미국 전체 시장"},
            {"ticker": "VXUS", "name": "Total Intl Stock", "asset_class": "Intl Equity", "weight": 10, "rationale": "해외 다변화"},
            {"ticker": "BND", "name": "Total Bond Market", "asset_class": "Bond ETF", "weight": 30, "rationale": "자산 방어"},
            {"ticker": "GLD", "name": "SPDR Gold Shares", "asset_class": "Gold ETF", "weight": 5, "rationale": "인플레이션 헤지"},
            {"ticker": "USDC", "name": "Cash / T-Bill", "asset_class": "Cash", "weight": 5, "rationale": "유동성"}
        ],
        "strategy_name": "기본 자산 배분 (AI 연결 오류)",
        "analysis_report": "AI 서비스 응답을 해석하는 데 실패했습니다. 대신 가장 표준적인 자산 배분 모델을 제안해 드립니다."
    }
    # ▲▲▲▲▲▲

    client = _client()
    if not client: return fallback_data

    try:
        market_context = _get_market_context()
        prompt = _build_prompt(profile, market_context)
        
        response = client.models.generate_content(model=MODEL, contents=prompt)
        text = getattr(response, "text", "") or ""
        
        # [수정] 강력한 JSON 추출 함수 사용
        data = _extract_pure_json(text)
        
        if data:
            return data
        else:
            print(f"[AI Raw Text] {text}") # 디버깅용 로그
            return fallback_data

    except Exception as e:
        print(f"[AI Error] {e}")
        return fallback_data

def get_chat_response(portfolio_report, user_question):
    """
    RAG 방식: 포트폴리오 데이터를 프롬프트에 포함해서 Gemini에게 질문
    """
    client = _client()
    if not client:
        return "죄송합니다. AI 서비스 연결에 실패했습니다."

    # 1. 포트폴리오 데이터를 AI가 읽기 편한 텍스트로 변환
    # (DB에 저장된 JSON 데이터를 문자열로 풀어서 설명)
    portfolio_context = json.dumps(portfolio_report.tickers_json, ensure_ascii=False, indent=2)
    allocation_context = json.dumps(portfolio_report.allocation_json, ensure_ascii=False, indent=2)
    user_profile = f"""
    - 투자금: ${portfolio_report.profile.total_amount:,}
    - 목표: {portfolio_report.profile.get_investment_goal_display()}
    - 성향: {portfolio_report.profile.get_risk_tolerance_display()}
    """

    # 2. 시스템 프롬프트 (페르소나 부여)
    system_prompt = f"""
    당신은 이 사용자의 전담 AI 프라이빗 뱅커(PB)입니다.
    사용자의 현재 포트폴리오와 투자 성향을 완벽하게 파악하고 있습니다.

    [사용자 정보]
    {user_profile}

    [현재 제안된 포트폴리오]
    {portfolio_context}

    [자산 배분]
    {allocation_context}

    [지시사항]
    - 위 데이터를 기반으로 사용자의 질문에 친절하고 전문적으로 답변하세요.
    - 포트폴리오에 없는 종목을 물어보면, 현재 포트폴리오와 비교해서 조언해주세요.
    - 답변은 한국어로, 핵심만 간결하게(3~5문장 내외) 작성하세요.
    - 너무 어려운 금융 용어는 쉽게 풀어서 설명하세요.
    """

    try:
        # 3. 대화 생성
        chat = client.models.start_chat(
            model=MODEL,
            history=[
                {"role": "user", "parts": system_prompt},
                {"role": "model", "parts": "네, 알겠습니다. 고객님의 포트폴리오를 숙지했습니다. 무엇을 도와드릴까요?"}
            ]
        )
        
        response = chat.send_message(user_question)
        return response.text

    except Exception as e:
        print(f"[Chat Error] {e}")
        return "죄송합니다. 일시적인 오류로 답변할 수 없습니다."