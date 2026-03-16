# scanner/watchlist.py
from typing import List
from updatedata.models import Ticker

# 야후 티커 리맵용
_REMAP = {"BRK.B": "BRK-B", "BF.B": "BF-B"}

def get_watchlist(limit: int = 200) -> List[str]:
    """
    스캔/차트 등에 쓸 심볼 리스트.
    - Universe(Ticker) 기준
    - is_active 없이 전체 Ticker에서 가져옴
    """
    qs = Ticker.objects.all().order_by("symbol")
    if limit:
        qs = qs[:limit]

    syms: list[str] = []
    for s in qs.values_list("symbol", flat=True):
        s = (s or "").strip().upper()
        if not s:
            continue
        syms.append(_REMAP.get(s, s))
    return syms
