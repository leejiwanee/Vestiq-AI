<div align="center">
  <img src="static/img/vestiq_signature.png" alt="Vestiq AI Logo" width="300"/>
  
  # Vestiq AI: Intelligent Quant & Market Insight Platform
  
  [![Python](https://img.shields.io/badge/Python-3.12-blue.svg?style=flat-square&logo=python)](https://www.python.org/)
  [![Django](https://img.shields.io/badge/Django-5.0-092E20.svg?style=flat-square&logo=django)](https://www.djangoproject.com/)
  [![MongoDB](https://img.shields.io/badge/MongoDB-Atlas-47A248.svg?style=flat-square&logo=mongodb)](https://www.mongodb.com/)
  [![Gemini API](https://img.shields.io/badge/AI-Google_Gemini-FFCA28.svg?style=flat-square&logo=google)](https://deepmind.google/technologies/gemini/)
  [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](https://opensource.org/licenses/MIT)

  *Vestiq AI is an automated quantitative analysis and AI-driven market insight platform designed to help investors make data-driven decisions based on SEC filings, macro data, and LLM-powered recommendations.*
  
  [**🇺🇸 English**](#english) | [**🇰🇷 한국어**](#korean)
</div>

<br />

---

<h2 id="english">🇺🇸 English</h2>

### 📌 Overview
**Vestiq AI** integrates multiple external data sources (SEC EDGAR, yfinance, FMP) with Google's Gemini LLM to provide deep, institutional-grade market intelligence. By automating the parsing of highly complex 13F SEC XML filings and utilizing generative AI for earnings report summarization, Vestiq bridges the gap between raw financial data and actionable trading insights.

### 📸 Screenshots
*(Please replace the placeholders below with your actual screenshots)*

| Scanner | Vestiq Pick |
| :---: | :---: |
| <img src="docs/images/scanner.png" width="400" alt="Scanner Screenshot" /> | <img src="docs/images/vestiq_pick.png" width="400" alt="Vestiq Pick Screenshot" /> |
| **AI Report Summary** | **AI Pick** |
| <img src="docs/images/ai_report.png" width="400" alt="AI Report Screenshot" /> | <img src="docs/images/ai_pick.png" width="400" alt="AI Pick Screenshot" /> |
| **Stock Search** | **AI Portfolio** |
| <img src="docs/images/stock_search.png" width="400" alt="Stock Search Screenshot" /> | <img src="docs/images/ai_portfolio.png" width="400" alt="AI Portfolio Screenshot" /> |
| **Galaxy Market Lab (Insight)** | **13F Guru Holdings** |
| <img src="docs/images/galaxy_insight.png" width="400" alt="Galaxy Insight Screenshot" /> | <img src="docs/images/13f_holdings.png" width="400" alt="13F Screenshot" /> |

### ✨ Key Features
- **🤖 AI-Powered Trading Recommendations**: Utilizes Google Gemini API to analyze market weather, technical indicators, and news, generating concrete Buy/Hold/Avoid recommendations with dynamic stop-loss/take-profit targets. Built-in fallback mechanisms handle API rate limits gracefully.
- **🏦 SEC 13F XML Automation**: Directly pulls and parses quarterly 13F-HR filings from the SEC EDGAR API, calculating institutional portfolio adjustments (new, increased, decreased, exited) of major gurus (e.g., Warren Buffett) in real-time.
- **🌌 Galaxy Market Lab (Data Visualization)**: Visualizes the market universe using Chart.js/ECharts. Features include Constellation Maps (clustering by sector), Risk Radars, and Flow Orbits based on market cap and daily returns.
- **📈 Advanced Quant Scanner**: Custom algorithmic screeners capable of filtering 500+ US stocks based on multi-timeframe technical setups (Day, Swing, Long).

### 🛠 Tech Stack
- **Backend**: Python 3, Django, APScheduler (Cron Jobs), BeautifulSoup4
- **Frontend**: HTML5/CSS3, Vanilla JS, Bootstrap 5, ECharts, Chart.js, Tailwind-inspired Dark Theme
- **Database**: SQLite (Local) / MongoDB Atlas (Document Store for 13F)
- **APIs**: Google Gemini 2.0 Flash, SEC EDGAR, yfinance, Financial Modeling Prep (FMP)

### 🏗 Architecture
```mermaid
graph LR
    A[External APIs] -->|Market Data| B(Django Backend)
    A2[SEC EDGAR] -->|13F XML/8-K| B
    A3[Gemini API] -->|AI Summary & Recs| B
    B -->|Persist JSON/Docs| C[(MongoDB Atlas)]
    B -->|Render UI| D[Frontend View]
    D -->|ECharts / Chart.js| E((User Browser))
```

### 🚀 Getting Started
1. **Clone the repository**
   ```bash
   git clone https://github.com/leejiwanee/Vestiq-AI.git
   cd Vestiq-AI
   ```
2. **Set up the virtual environment**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
3. **Environment Variables**
   Create a `.env` file in the root directory:
   ```env
   DJANGO_SECRET_KEY=your_secret_key
   GEMINI_API_KEY=your_gemini_key
   GEMINI2_API_KEY=your_gemini2_key
   MONGODB_URI=your_mongo_cluster_uri
   FMP_API_KEY=your_fmp_api_key
   ```
4. **Run Server**
   ```bash
   python manage.py makemigrations
   python manage.py migrate
   python manage.py runserver
   ```

---

<h2 id="korean">🇰🇷 한국어</h2>

### 📌 프로젝트 소개
**Vestiq AI**는 방대한 금융 데이터(SEC 공시, 주가, 거시경제 지표)를 수집하여 Google Gemini 생성형 AI와 결합, 개인 투자자에게 기관급 퀀트 분석 및 투자 인사이트를 제공하는 웹 플랫폼입니다. 복잡한 미국 증권거래위원회(SEC)의 13F 보고서를 자동 파싱하고, 실시간 시장 데이터를 기반으로 AI 매매 추천을 생성하는 것이 핵심입니다.

### 📸 스크린샷
*(docs/images 폴더에 직접 캡처한 이미지를 넣어주세요)*

| 스캐너 (Scanner) | Vestiq Pick |
| :---: | :---: |
| <img src="docs/images/scanner.png" width="400" alt="스캐너" /> | <img src="docs/images/vestiq_pick.png" width="400" alt="Vestiq Pick" /> |
| **AI 리포트 요약** | **AI Pick** |
| <img src="docs/images/ai_report.png" width="400" alt="AI 리포트 요약" /> | <img src="docs/images/ai_pick.png" width="400" alt="AI Pick" /> |
| **종목 검색** | **AI 포트폴리오** |
| <img src="docs/images/stock_search.png" width="400" alt="종목 검색" /> | <img src="docs/images/ai_portfolio.png" width="400" alt="AI 포트폴리오" /> |
| **Galaxy Market Lab (시각화)** | **13F 구루 포트폴리오 (SEC 연동)** |
| <img src="docs/images/galaxy_insight.png" width="400" alt="마켓 랩" /> | <img src="docs/images/13f_holdings.png" width="400" alt="13F 분석" /> |

### ✨ 주요 기능
- **🤖 AI 기반 투자 전략 및 요약 (Generative AI)**: Gemini API를 활용해 그날의 시장(Market Weather)을 요약하고, 기술적/기본적 지표를 종합하여 종목별 매수/보유/관망(Buy/Hold/Avoid) 의견 및 목표가를 자동 산출합니다. (503 Rate Limit 대비 다중 모델 Fallback 적용)
- **🏦 SEC 13F 공시 자동화 파이프라인**: 워런 버핏 등 유명 투자 대가(Guru)들의 SEC EDGAR 13F-HR 공시 원본(XML)을 파싱 및 집계합니다. 전 분기 대비 포트폴리오의 신규 매수, 비중 확대/축소, 전량 매도 내역을 정확히 계산하여 MongoDB에 캐싱합니다.
- **🌌 인터랙티브 데이터 시각화 (Galaxy Lab)**: Chart.js 및 ECharts를 활용하여 시가총액 기반의 Flow Orbit, 섹터별 리스크 레이더(Risk Radar) 등 다차원적인 시장 데이터를 직관적인 다크 테마 UI로 제공합니다.
- **📈 자체 퀀트 스캐너**: 데이트레이딩, 스윙, 장기 투자 등 다중 타임프레임 기준에 맞춘 자체 알고리즘 필터링 시스템을 통해 조건에 부합하는 종목을 실시간 스크리닝합니다.

### 🛠 기술 스택
- **Backend**: Python 3, Django, APScheduler (백그라운드 크론잡), BeautifulSoup4
- **Frontend**: HTML5/CSS3, Vanilla JS, Bootstrap 5, ECharts, Chart.js, 자체 설계 Gilded Obsidian 다크 테마
- **Database**: SQLite (RDBMS) / MongoDB Atlas (비정형 13F 공시 데이터)
- **APIs**: Google Gemini 2.0 Flash, SEC EDGAR, yfinance, Financial Modeling Prep (FMP)

### 🏗 시스템 아키텍처
```mermaid
graph LR
    A[외부 데이터 API] -->|주가 및 재무 데이터| B(Django 백엔드)
    A2[SEC EDGAR] -->|13F XML / 8-K 공시| B
    A3[Google Gemini API] -->|시황 요약 및 AI 분석| B
    B -->|데이터 캐싱 및 스냅샷| C[(MongoDB Atlas)]
    B -->|화면 렌더링| D[프론트엔드 UI]
    D -->|ECharts / Chart.js| E((사용자 웹 브라우저))
```

### 🚀 설치 및 실행 방법
1. **레포지토리 클론**
   ```bash
   git clone https://github.com/leejiwanee/Vestiq-AI.git
   cd Vestiq-AI
   ```
2. **가상환경 설정 및 패키지 설치**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
3. **환경 변수 설정**
   루트 디렉토리에 `.env` 파일을 생성하고 아래 키를 입력하세요:
   ```env
   DJANGO_SECRET_KEY=발급받은_시크릿키
   GEMINI_API_KEY=제미나이_API키
   GEMINI2_API_KEY=제미나이_API키_2
   MONGODB_URI=몽고DB_연결_URI
   FMP_API_KEY=FMP_API키
   ```
4. **서버 실행**
   ```bash
   python manage.py makemigrations
   python manage.py migrate
   python manage.py runserver
   ```

---
<div align="center">
  <i>Developed with ❤️ by Jiwan Lee</i>
</div>
