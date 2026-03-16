# insight/documents.py

import datetime
from mongoengine import (
    Document,
    EmbeddedDocument,
    StringField,
    IntField,
    FloatField,
    ListField,
    EmbeddedDocumentField,
    DateTimeField,
)


class Holding(EmbeddedDocument):
    """
    13F 개별 보유 종목
    """
    cusip = StringField() 
    ticker = StringField()   # 표시용 티커 (회사명 앞 12글자 등)
    name = StringField()     # 회사명 전체
    shares = IntField()      # 보유 주식 수
    value = FloatField()     # 보유 가치 (USD)
    percent = FloatField()   # 포트폴리오 내 비중 (%)


class GuruPortfolioDoc(Document):
    """
    Super Investor 13F 포트폴리오 스냅샷
    """
    # 예: "buffett", "dalio"
    guru_key = StringField(required=True, unique=True)

    # 기본 정보
    name = StringField()         # 예: "Warren Buffett (Berkshire)"
    report_date = StringField()  # 13F reportDate (YYYY-MM-DD 문자열)

    # 핵심: 보유 종목 리스트
    holdings = ListField(EmbeddedDocumentField(Holding))

    

    # 메타 데이터
    total_value = FloatField()   # 총 포트폴리오 가치
    count = IntField()           # 종목 개수

    # 마지막 업데이트 시간
    updated_at = DateTimeField(default=datetime.datetime.now)

    meta = {
        "collection": "guru_portfolios",
    }
