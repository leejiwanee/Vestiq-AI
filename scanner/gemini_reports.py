# scanner/gemini_reports.py
import os
import json
import re
from typing import Optional, Tuple, Any, Dict

from google import genai
from django.utils import timezone
from datetime import datetime, time, timedelta
from .models import AiReport

MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


def _client():
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY missing")
    return genai.Client(api_key=key)


# Scanner용 구조화 리포트 스키마 (JSON)
SCHEMA = (
    '{'
    '"overview": string, '
    '"positives":[string], '
    '"negatives":[string], '
    '"checklist":[string], '
    '"technical":[string], '
    '"reasons":[{"title":string,"url":string,"explanation":string}], '
    '"financial_analysis": {'
    '"valuation": {"pe_ratio":string,"pb_ratio":string,"assessment":string},'
    '"earnings": {"revenue":string,"operating_income":string,"eps":string,"growth_summary":string,"recent_earnings_summary":string},'
    '"health": {"cash":string,"debt_to_equity":string,"assessment":string},'
    '"risks": [string],'
    '"wall_street": {"consensus":string,"target_price":string},'
    '"verdict": {"title":string,"content":string}'
    '},'
    '"fair_value_price": number | string, '
    '"fair_value_rationale": string, '
    '"conclusion": string'
    '}'
)


def _build_filter_block_ko(stats: Dict[str, Any]) -> str:
    """
    stats 안에 포함된 필터 플래그를 바탕으로
    이 종목이 왜 스캐너에 포착되었는지 한국어로 설명 블록 생성.
    기대 키:
      - f_volume, f_volatility, f_trend, f_pattern, f_momentum (bool)
    """
    parts = []

    if stats.get("f_volume"):
        parts.append(
            "🔥 거래량 기반 필터: 오늘 거래량이 최근 평균 대비 크게 증가했고, "
            "전일 대비 거래량 변화율도 의미 있게 확대되어 단기적으로 큰 자금 유입 가능성이 있습니다."
        )

    if stats.get("f_volatility"):
        parts.append(
            "⚡ 변동성 필터 (Volatility Breakout): 일중 고가–저가 범위와 ATR 기준으로 "
            "최근보다 변동성이 커져 단타 매매가 가능한 수준의 가격 움직임이 포착되었습니다."
        )

    if stats.get("f_trend"):
        parts.append(
            "📈 추세 전환 시그널 필터 (Trend Reversal): RSI, MACD, 이동평균선 조합을 기준으로 "
            "하락 혹은 조정 국면에서 상승 전환을 시도하는 신호가 나타난 종목입니다."
        )

    if stats.get("f_pattern"):
        parts.append(
            "📊 차트 패턴 필터 (Breakout/Breakdown): 최근 캔들 형태가 박스권·삼각 수렴·플래그 패턴 등 "
            "돌파 직전 구간에 해당하는 차트 구조를 보여주는 종목입니다."
        )

    if stats.get("f_momentum"):
        parts.append(
            "💎 모멘텀 필터 (Momentum Strength): 단기 수익률과 이동평균선, VWAP 기준으로 "
            "상승 모멘텀이 유지되는 종목으로, 강한 추세가 이어질 가능성이 있는 종목입니다."
        )

    if not parts:
        return (
            "이 종목은 현재 정의된 5개 필터에 뚜렷하게 걸리지는 않았지만, "
            "참고용으로 단기 기술적 관점에서 리포트를 생성합니다."
        )

    return "\n".join(parts)


def _build_prompt(symbol: str, stats: dict, company: dict, financials: dict = None, language='ko') -> str:
    """
    stats: {
      "close": float,
      "price_change_pct": float,
      "vol_change_pct": float,
      "volume": float,
      "prev_volume": float,
      "f_volume": bool,
      "f_volatility": bool,
      "f_trend": bool,
      "f_pattern": bool,
      "f_momentum": bool,
      ...
    }
    """
    close = float(stats.get("close") or 0.0)
    price_pct = float(stats.get("price_change_pct") or 0.0)
    vol_pct = float(stats.get("vol_change_pct") or 0.0)
    volume = float(stats.get("volume") or 0.0)
    prev_volume = float(stats.get("prev_volume") or 0.0)

    name = company.get("name", "") or ""
    sector = company.get("sector", "") or ""
    industry = company.get("industry", "") or ""

    filter_block = _build_filter_block_ko(stats)

    from ai_advisor.prompts import get_scanner_report_prompt
    return get_scanner_report_prompt(
        symbol, name, sector, industry, close, price_pct, vol_pct, volume, prev_volume, 
        filter_block, financials or {}, SCHEMA, language=language
    )



def _extract_json(text: str) -> Optional[dict]:
    text = (text or "").strip()
    s, e = text.find("{"), text.rfind("}")
    if s == -1 or e == -1 or e <= s:
        return None
    try:
        return json.loads(text[s:e + 1])
    except Exception:
        cleaned = re.sub(
            r"^```(?:json)?|```$",
            "",
            text,
            flags=re.MULTILINE
        ).strip()
        s, e = cleaned.find("{"), cleaned.rfind("}")
        if s != -1 and e != -1 and e > s:
            return json.loads(cleaned[s:e + 1])
        return None


def _parse_float_maybe(x) -> Optional[float]:
    """문자열/숫자에서 처음 나오는 실수 하나만 뽑아내기."""
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x)
    m = re.search(r"-?\d+(\.\d+)?", s.replace(",", ""))
    if not m:
        return None
    try:
        return float(m.group(0))
    except Exception:
        return None


# scanner/gemini_reports.py
import re

def _normalize_conclusion(conclusion: str) -> str:

    text = (conclusion or "").strip()
    if not text:
        return ""

    # 줄 → 문장 단위 분해
    raw_lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    sentences = []
    for ln in raw_lines:
        parts = re.split(r'(?<=[\.!?])\s+', ln)
        for p in parts:
            p = p.strip()
            if p:
                sentences.append(p)

    if not sentences:
        return text

    # stance 판별
    stance = None
    for s in sentences:
        if "매도" in s:
            stance = "매도"
            break
        if "관망" in s and stance is None:
            stance = "관망"
        if "매수" in s and stance is None:
            stance = "매수"

    # Gemini 판단 헤더 문구 먼저 만들어 두기
    if stance == "매수":
        first_line = "🟢 Gemini 판단: 매수"
    elif stance == "매도":
        first_line = "🔴 Gemini 판단: 매도"
    elif stance == "관망":
        first_line = "⚪ Gemini 판단: 관망"
    else:
        # stance 못 찾으면 그냥 원문 돌려보내기
        return text

    # 'Gemini 판단' 문장은 제거
    cleaned = []
    for s in sentences:
        if "Gemini 판단" in s or "Gemini의 판단" in s:
            continue
        cleaned.append(s)

    # 본문 첫 문장이 '관망.', '매수.', '매도.' 같은 경우 삭제
    if cleaned:
        # 한글/영문/숫자만 남기고 비교 (마침표, 공백 제거)
        first_raw = cleaned[0]
        first_norm = re.sub(r"[^0-9A-Za-z가-힣]", "", first_raw)
        if stance and first_norm == stance:
            cleaned = cleaned[1:]

    rest_text = " ".join(cleaned).strip()
    if rest_text:
        return first_line + "\n" + rest_text
    else:
        return first_line



def generate_ai_report_structured(
    symbol: str,
    stats: dict,
    company: dict,
    financials: dict = None,
    language='ko'
) -> Tuple[Optional[dict], Optional[str]]:
    """
    Scanner용 구조화 리포트 생성
    language: 'ko' or 'en'
    
    Returns:
        (report_dict, error_msg)
    """
    # 1. 캐시 체크 (오늘 16:15 이후에 만들어진 리포트가 있는지)
    from django.utils import timezone
    from datetime import datetime, time, timedelta
    
    now = timezone.now()
    cutoff_time = time(16, 15)  # 4:15 PM
    
    # 해당 날짜(target_date) 이후에 생성된 리포트가 있는지 확인
    # [Fix] USE_TZ=False 환경에서는 naive datetime을 사용해야 함.
    if now.time() < cutoff_time:
        base_date = now.date() - timedelta(days=1)
    else:
        base_date = now.date()

    window_start = datetime.combine(base_date, cutoff_time)
        
    # Cache key includes language to separate Korean and English reports
    cache_key = f"{symbol}_{language}"
    cached = AiReport.objects.filter(
        symbol=cache_key,  # Use language-aware key
        created_at__gte=window_start
    ).order_by('-created_at').first()
    
    if cached:
        return cached.payload, None

    # 2. API 호출
    try:
        client = _client()
        prompt = _build_prompt(symbol, stats, company, financials, language=language)
        # Try primary model first, fallback to lite/alternative models if experiencing 503/errors
        r = None
        try:
            r = client.models.generate_content(model=MODEL, contents=prompt)
        except Exception as e:
            for fallback_model in ["gemini-2.5-flash-lite", "gemini-2.0-flash"]:
                if fallback_model == MODEL:
                    continue
                try:
                    r = client.models.generate_content(model=fallback_model, contents=prompt)
                    if r:
                        break
                except Exception:
                    pass
            if not r:
                raise e

        # genai 라이브러리 응답 구조에 따라 조정 필요할 수 있음
        text = getattr(r, "text", "") or ""
        obj = _extract_json(text)
        if not obj:
            return None, "AI 응답이 비었습니다."

        # 기본 필드 보정
        obj.setdefault("overview", "")
        obj.setdefault("positives", [])
        obj.setdefault("negatives", [])
        obj.setdefault("checklist", [])
        obj.setdefault("technical", [])
        obj.setdefault("reasons", [])
        obj.setdefault("fair_value_price", None)
        obj.setdefault("fair_value_rationale", "")
        obj.setdefault("conclusion", "")

        # 길이 제한
        obj["positives"] = [p[:140] for p in obj["positives"]][:3]
        obj["negatives"] = [n[:140] for n in obj["negatives"]][:4]
        obj["checklist"] = [c[:120] for c in obj["checklist"]][:4]
        obj["technical"] = [str(x)[:120] for x in obj["technical"]][:5]

        cleaned_reasons = []
        for ritem in obj["reasons"]:
            if not isinstance(ritem, dict):
                continue
            t = (ritem.get("title") or "").strip()
            u = (ritem.get("url") or "").strip()
            e = (ritem.get("explanation") or "").strip()
            if t:
                cleaned_reasons.append(
                    {"title": t[:120], "url": u, "explanation": e[:200]}
                )
        obj["reasons"] = cleaned_reasons[:5]
        obj["conclusion"] = _normalize_conclusion(obj.get("conclusion", ""))

        # 적정주가 블록 계산
        fv_raw = obj.get("fair_value_price")
        fv = _parse_float_maybe(fv_raw)
        close = float(stats.get("close") or 0.0)

        fair_value_block = None
        if fv and close > 0:
            diff = fv - close
            diff_pct = diff / close * 100.0

            if diff_pct >= 5:
                label = "저렴"
                tone = "cheap"
            elif diff_pct <= -5:
                label = "비쌈"
                tone = "expensive"
            else:
                label = "적정"
                tone = "fair"

            fair_value_block = {
                "price": round(fv, 2),
                "diff_pct": round(diff_pct, 1),
                "label": label,
                "tone": tone,
                "rationale": (obj.get("fair_value_rationale") or "")[:220],
            }

        obj["fair_value"] = fair_value_block
        
        obj.setdefault("fair_value_rationale", "")
        obj.setdefault("conclusion", "")

        # 3. 캐시 저장
        cache_key = f"{symbol}_{language}"  # Use language-aware key
        AiReport.objects.create(symbol=cache_key, payload=obj)

        return obj, None
    except Exception as e:
        return None, f"Gemini API 오류: {str(e)}"
