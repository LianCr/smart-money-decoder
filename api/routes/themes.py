"""api/routes/themes.py — 首页主题卡（2026-10-30）：中期选举横幅 + Tech & Immigration。

纯转发：逻辑与诚实声明全在 fetcher/theme_markets.py（TTL 缓存、上游失败返空 markets）。
两个端点永远 200——主题卡是锦上添花，不许把首页拖成错误页。
"""

from fastapi import APIRouter

from fetcher import theme_markets

router = APIRouter()


@router.get("/election-pulse")
def election_pulse():
    return theme_markets.election_pulse()


@router.get("/tech-immigration")
def tech_immigration():
    return theme_markets.tech_immigration()
