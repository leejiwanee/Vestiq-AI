import requests
import json
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings

# Import OAuth helper function
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from accounts.kakao_oauth import get_valid_kakao_token
from updatedata.models import Ticker
from .views import api_chart_data  # Direct function call import

@csrf_exempt
@require_POST  
def send_kakao_vestiq_pick(request):
    """
    Send Vestiq Pick stock data to user's Kakao Talk via template message.
    Template ID: 127273
    Uses user's OAuth access token (requires login).
    """
    try:
        # Check if user is authenticated
        if not request.user.is_authenticated:
            return JsonResponse({
                'success': False, 
                'error': '로그인이 필요합니다.',
                'require_login': True
            }, status=401)
        
        # Get valid access token (auto-refresh if expired)
        access_token = get_valid_kakao_token(request.user)
        
        if not access_token:
            return JsonResponse({
                'success': False, 
                'error': '카카오 로그인이 필요합니다.',
                'require_login': True
            }, status=401)
        
        # Parse request data
        data = json.loads(request.body)
        
        # Extract stock data
        # Extract stock data
        name = data.get('name', '')
        ticker = str(data.get('ticker', '')).upper()
        filters = data.get('filters', '')
        
        print(f"[DEBUG] Kakao Payload Received for {ticker}")
        
        # === USE PAYLOAD DIRECTLY (Frontend Calculated) ===
        rsi_desc = data.get('rsi_desc', "RSI: 중립")
        rsi_desc2 = data.get('rsi_desc2', "")
        
        macd_desc = data.get('macd_desc', "MACD: 횡보")
        macd_desc2 = data.get('macd_desc2', "")
        
        trend_desc = data.get('trend_desc', "추세: 중립")
        trend_desc2 = data.get('trend_desc2', "")
        
        stoch_desc = data.get('stoch_desc', "스토캐스틱: 중립")
        stoch_desc2 = data.get('stoch_desc2', "")
        
        cloud_desc = data.get('cloud_desc', "일목균형표: 보통")
        cloud_desc2 = data.get('cloud_desc2', "")
        cloud_desc3 = data.get('cloud_desc3', "")
        
        print(f"[DEBUG] Extracted Descriptions:")
        print(f" - RSI: {rsi_desc}")
        print(f" - MACD: {macd_desc}")
        # The subsequent cleanup will remove the old API logic
        
        # Placeholder to prevent indentation errors if any
        response = None 
        # API logic cleanup follows...
            
        # [FIX] Restore try block to fix indentation
        try:
            # Check response status code (it's a JsonResponse object)
            if True: # Ignore API response, use frontend payload
                # Parse JSON content from the response object
                # [CRITICAL FIX] attributes are at root level, not under 'data'
                # data = json.loads(response.content) # DATA OVERWRITE PREVENTED
                
                print(f"[DEBUG] API Response keys: {list(data.keys())}")
                
                # === Extract RSI ===
                if 'rsi' in data:
                    rsi_values = data['rsi']
                    if rsi_values and len(rsi_values) > 0:
                        last_rsi = rsi_values[-1]
                        # Handle list [time, value] or dict {time, value} or pure value
                        if isinstance(last_rsi, list):
                            rsi_val = last_rsi[1]
                        elif isinstance(last_rsi, dict):
                            rsi_val = last_rsi.get('value')
                        else:
                            rsi_val = last_rsi
                        
                        if rsi_val is not None:
                            if rsi_val >= 70:
                                rsi_desc = f"RSI ({rsi_val:.1f}): 과매수 (Overbought)"
                                rsi_desc2 = "→ 매수 보류 및 차익 실현"
                            elif rsi_val <= 30:
                                rsi_desc = f"RSI ({rsi_val:.1f}): 과매도 (Oversold)"
                                rsi_desc2 = "→ 저점 매수 기회 포착"
                            else:
                                rsi_desc = f"RSI ({rsi_val:.1f}): 중립"
                                rsi_desc2 = "→ 모멘텀 대기"
                            print(f"[DEBUG] ✅ RSI from API: {rsi_val:.1f} ({rsi_desc})")
                
                # === Extract MACD (Signal/Line) ===
                if 'macd' in data:
                    macd_data = data['macd']
                    if 'macd' in macd_data and 'signal' in macd_data:
                        # Get last values
                        def get_last(arr):
                            if not arr or len(arr) == 0: return None
                            last = arr[-1]
                            if isinstance(last, list): return last[1]
                            if isinstance(last, dict): return last.get('value')
                            return last
                        
                        m_val = get_last(macd_data['macd'])
                        s_val = get_last(macd_data['signal'])
                        
                        if m_val is not None and s_val is not None:
                            if m_val > s_val:
                                macd_desc = "MACD: 골든크로스 (상승 전환)"
                                macd_desc2 = "→ 매수 관점 유효"
                            else:
                                macd_desc = "MACD: 데드크로스 (하락 전환)"
                                macd_desc2 = "→ 매도/리스크 관리 필요"
                            print(f"[DEBUG] ✅ MACD from API: M={m_val:.2f}, S={s_val:.2f} -> {macd_desc}")

                # === Extract MACD Histogram (Trend Strength) ===
                if 'macd' in data and 'diff' in data['macd']:
                    macd_diff = data['macd']['diff']
                    if len(macd_diff) >= 2:
                        # Get last two histogram values
                        last_hist = macd_diff[-1]
                        prev_hist = macd_diff[-2]
                        
                        # Extract values (could be array or dict)
                        if isinstance(last_hist, list):
                            h_val = last_hist[1]
                        elif isinstance(last_hist, dict):
                            h_val = last_hist.get('value', 0)
                        else:
                            h_val = last_hist
                        
                        if isinstance(prev_hist, list):
                            p_val = prev_hist[1]
                        elif isinstance(prev_hist, dict):
                            p_val = prev_hist.get('value', 0)
                        else:
                            p_val = prev_hist
                        
                        # AI Analyst logic (line 5266-5274)
                        if h_val > 0:
                            if h_val > p_val:
                                trend_desc = "양봉 확대 (매수세 강화)"
                            else:
                                trend_desc = "양봉 축소 (상승탄력 둔화)"
                        else:
                            if h_val < p_val:
                                trend_desc = "음봉 확대 (매도세 강화)"
                            else:
                                trend_desc = "음봉 축소 (하락탄력 둔화)"
                        
                        print(f"[DEBUG] ✅ Trend from API: hist={h_val:.4f}, prev={p_val:.4f} → {trend_desc}")
                
                # === Extract Stochastic (Short/Mid/Long) ===
                if 'stoch' in data:
                    stoch_data = data['stoch']
                    
                    def analyze_stoch_api(name, arr):
                        if not arr or not isinstance(arr, list) or len(arr) == 0:
                            return None
                        
                        # Find last valid k value
                        k_val = None
                        d_val = None
                        for item in reversed(arr):
                            if isinstance(item, dict) and 'k' in item:
                                k_val = item['k']
                                d_val = item.get('d')
                                break
                        
                        if k_val is None:
                            return None
                        
                        # Status
                        if k_val > 80:
                            status = "과열"
                        elif k_val < 20:
                            status = "침체"
                        else:
                            status = "중립"
                        
                        # Momentum
                        momentum = ""
                        if d_val is not None:
                            if k_val > d_val:
                                momentum = "상승 모멘텀"
                            else:
                                momentum = "하락 모멘텀"
                        
                        return f"{name}: {status}({k_val:.0f}) {momentum}"
                    
                    # AI Analyst uses s/m/l or fast/mid/slow
                    short_result = analyze_stoch_api("단기", stoch_data.get('s') or stoch_data.get('fast'))
                    mid_result = analyze_stoch_api("중기", stoch_data.get('m') or stoch_data.get('mid'))
                    long_result = analyze_stoch_api("장기", stoch_data.get('l') or stoch_data.get('slow'))
                    
                    # Always show all 3
                    if short_result:
                        stoch_desc = short_result
                    if mid_result and long_result:
                        stoch_desc2 = f"{mid_result.split(':')[1].strip()}, {long_result.split(':')[1].strip()}"
                    
                    print(f"[DEBUG] ✅ Stochastic from API: {short_result}, {mid_result}, {long_result}")
                
                # === Extract Ichimoku Cloud ===
                if 'ichimoku' in data:
                    ich = data['ichimoku']
                    
                    def get_last_val(arr):
                        if not arr or len(arr) == 0:
                            return None
                        last = arr[-1]
                        if isinstance(last, list):
                            return last[1]
                        if isinstance(last, dict):
                            return last.get('value')
                        return last
                    
                    tenkan = get_last_val(ich.get('tenkan'))
                    kijun = get_last_val(ich.get('kijun'))
                    span_a = get_last_val(ich.get('span_a') or ich.get('spanA'))
                    span_b = get_last_val(ich.get('span_b') or ich.get('spanB'))
                    
                    # Get current price
                    if 'ohlcv' in data and len(data['ohlcv']) > 0:
                        last_candle = data['ohlcv'][-1]
                        if isinstance(last_candle, list):
                            current_price = last_candle[4]  # close
                        elif isinstance(last_candle, dict):
                            current_price = last_candle.get('close')
                        else:
                            current_price = 0
                        
                        # Cloud position (AI Analyst line 5348-5358)
                        if span_a and span_b and current_price:
                            cloud_top = max(span_a, span_b)
                            cloud_bottom = min(span_a, span_b)
                            
                            if current_price > cloud_top:
                                cloud_desc = "구름대 상단 돌파 (Breakout)"
                                cloud_desc2 = "장기 강세 국면 진입"
                            elif current_price < cloud_bottom:
                                cloud_desc = "구름대 하단 이탈 (Breakdown)"
                                cloud_desc2 = "약세 국면, 저항 주의"
                            else:
                                cloud_desc = "구름대 내부 (Volatility)"
                                cloud_desc2 = "혼조세, 방향성 탐색 중"
                        
                        # Tenkan vs Kijun (AI Analyst line 5364-5366)
                        if tenkan and kijun:
                            if tenkan > kijun:
                                cloud_desc3 = "호전 (전환선 > 기준선): 매수세 우위"
                            else:
                                cloud_desc3 = "역전 (전환선 < 기준선): 매도세 우위"
                        
                        print(f"[DEBUG] ✅ Ichimoku from API: Price={current_price:.2f}, Cloud=[{cloud_bottom:.2f}, {cloud_top:.2f}], T={tenkan:.2f}, K={kijun:.2f}")
                
                print(f"[DEBUG] 🎯 Using API-fetched data (same as AI Analyst)!")
            else:
                print(f"[WARNING] ⚠️ Chart API returned {response.status_code}")
                
        except Exception as e:
            import traceback
            print(f"[ERROR] ❌ Chart API call failed: {e}")
            print(f"[ERROR] Traceback: {traceback.format_exc()}")
            print(f"[WARNING] Using frontend fallback data")
        
        # Build template args for custom template 127273
        
        # === RSI ===
        rsi_title = "RSI"
        rsi_desc_combined = rsi_desc  # Use raw string from API
        if rsi_desc2:
            rsi_desc_combined += f"\n{rsi_desc2}"
            
        # === MACD ===
        macd_title = "MACD"
        macd_desc_combined = macd_desc
        if macd_desc2:
            macd_desc_combined += f"\n{macd_desc2}"
            
        # === Trend Strength ===
        trend_title = "추세 강도"
        trend_desc_combined = trend_desc
        
        # === Stochastic ===
        stoch_title = "스토캐스틱"
        # Combine desc and desc2 properly
        if stoch_desc2:
            stoch_desc_combined = f"{stoch_desc}\n{stoch_desc2}"
        else:
            stoch_desc_combined = stoch_desc
            
        # === Ichimoku Cloud ===
        cloud_title = "일목균형표"
        cloud_desc_combined = cloud_desc
        if cloud_desc2:
             cloud_desc_combined += f"\n{cloud_desc2}"
        if cloud_desc3:
             cloud_desc_combined += f"\n{cloud_desc3}"
        
        # === VERDICT - Intelligent decision: 매수/관망/매도 ===
        # === VERDICT - Intelligent decision: 매수/관망/매도 ===
        
        # === DETAILED VERDICT (세 번째 사진 형식) ===
        # Format: "✅ 매수 유효 (Buy Zone): 진입가 상회, 상승 모멘텀 지속 중."
        
        # Parse RSI signal
        rsi_is_overbought = "과매수" in rsi_desc or "Overbought" in rsi_desc
        rsi_is_oversold = "과매도" in rsi_desc or "Oversold" in rsi_desc
        
        # Parse MACD signal
        macd_is_golden = "골든크로스" in macd_desc_combined
        macd_is_dead = "데드크로스" in macd_desc_combined
        
        # Parse Cloud signal
        cloud_is_good = "돌파" in cloud_desc_combined or "Breakout" in cloud_desc_combined
        cloud_is_bad = "이탈" in cloud_desc_combined or "Breakdown" in cloud_desc_combined
        
        # AI Analyst logic: RSI overbought + MACD golden cross = Strong Buy
        if rsi_is_overbought and macd_is_golden:
            # Strong bullish momentum - matches "매수 유효 (Buy Zone)"
            verdict = "✅ 매수 유효 (Buy Zone): 진입가 상회, 상승 모멘텀 지속 중."
        elif rsi_is_oversold and macd_is_golden:
            # Oversold with golden cross - good entry
            verdict = "✅ 매수 유효 (Buy Zone): 저점 반등, 상승 전환 포착."
        elif macd_is_dead or cloud_is_bad:
            # Bearish signals
            verdict = "⚠️ 매도 검토 (Sell Zone): 저항선 도달, 리스크 관리 필요."
        elif cloud_is_good and macd_is_golden:
            # Cloud breakout + golden cross
            verdict = "✅ 매수 유효 (Buy Zone): 구름대 돌파, 강세 지속."
        else:
            # Mixed or neutral signals
            verdict = "⏳ 관망 권장 (Hold): 방향성 불명확, 추가 관찰 필요."
        
        print(f"[DEBUG] VERDICT Logic: RSI_OB={rsi_is_overbought}, MACD_GC={macd_is_golden} → {verdict}")
        
        # Get ticker logo
        # Priority: 1. DB Image (Absolute URL) 2. FMP External URL
        ticker_image = ""
        try:
            from updatedata.models import Ticker
            ticker_obj = Ticker.objects.get(symbol=ticker)
            if ticker_obj.image and hasattr(ticker_obj.image, 'url'):
                # Force absolute URL for Kakao
                ticker_image = f"https://vestiq.pro{ticker_obj.image.url}"
        except Exception as e:
            print(f"[DEBUG] DB Image fetch failed: {e}")
            pass
            
        if not ticker_image:
            ticker_image = f"https://financialmodelingprep.com/image-stock/{ticker}.png"
        
        # Build stock profile URL
        stock_url = f"https://vestiq.pro/scanner/profile/{ticker}/"
        
        # Prepare template_args for custom template 127273
        template_args = {
            "NAME": name,
            "TICKER": ticker,
            "FILTERS": filters,
            "RSI_TITLE": rsi_title,
            "RSI_DESC": rsi_desc_combined,
            "MACD_TITLE": macd_title,
            "MACD_DESC": macd_desc_combined,
            "TREND_TITLE": trend_title,
            "TREND_DESC": trend_desc_combined,
            "STOCH_TITLE": stoch_title,
            "STOCH_DESC": stoch_desc_combined,
            "CLOUD_TITLE": cloud_title,
            "CLOUD_DESC": cloud_desc_combined,
            "VERDICT": verdict,
            "TICKER_IMAGE": ticker_image  # Logo from database
        }

        
        # Kakao API request using custom template
        url = "https://kapi.kakao.com/v2/api/talk/memo/send"
        headers = {
            "Authorization": f"Bearer {access_token}"
        }
        
        # Prepare form data for custom template
        payload = {
            "template_id": "127273",
            "template_args": json.dumps(template_args, ensure_ascii=False)
        }
        
        # Debug logging
        print(f"[DEBUG] Kakao API URL: {url}")
        print(f"[DEBUG] Template ID: 127273")
        print(f"[DEBUG] TICKER_IMAGE: {ticker_image}")
        print(f"[DEBUG] Template Args: {json.dumps(template_args, ensure_ascii=False, indent=2)}")
        
        # Send request
        response = requests.post(url, headers=headers, data=payload)


        
        # Debug response
        print(f"[DEBUG] Response Status: {response.status_code}")
        print(f"[DEBUG] Response Body: {response.text}")

        
        if response.status_code == 200:
            return JsonResponse({'success': True, 'message': '카카오톡 전송 성공!'})
        else:
            return JsonResponse({
                'success': False, 
                'error': f'Kakao API Error: {response.status_code}',
                'details': response.text,
                'sent_data': json.dumps(template_object, ensure_ascii=False)
            }, status=response.status_code)

            
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

