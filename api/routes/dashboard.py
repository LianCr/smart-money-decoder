"""api/routes/dashboard.py — v3 统一看板路由（T2.3 从 main.py 原样搬出）。

构建/单飞/缓存/旧板回退全在 services/dashboard_build（纯数据契约）；
本模块只做 reason→HTTP 状态码映射（_dashboard_status，api 层唯一的 HTTP 知识）。
其余 fetcher 层 reason（API_TIMEOUT / RATE_LIMITED / API_ERROR / KEYWORD_EXTRACT_FAILED /
TAVILY_*）一律视为上游失败 → 502。
"""

import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from api.shared import _rate_limited
from core.config import BRIEFING_AS_OF
from services.dashboard_build import (
    BAD_REQUEST_REASONS, BUILD_IN_PROGRESS, DASHBOARD_CACHE,
    NO_POSITION_REASONS, get_dashboard,
)

router = APIRouter()


def _dashboard_status(reason: str) -> int:
    """service 纯数据错误 → HTTP 状态码（唯一的 HTTP 映射知识，留在 api 层）。"""
    if reason in BAD_REQUEST_REASONS:
        return 400
    if reason in NO_POSITION_REASONS:
        return 404
    if reason == BUILD_IN_PROGRESS:
        return 202                        # 同钱包正在构建，前端轮询
    return 502                            # 其余一律上游失败


@router.get("/dashboard")
def dashboard(wallet: str, request: Request, refresh: int = 0, fresh: int = 0):
    """v3 统一看板：构建/单飞/缓存/旧板回退全在 services/dashboard_build.get_dashboard
    （纯数据契约，recommend.ai_verify 进程内走同一入口）；这里只把错误 dict 映射成 HTTP 状态码。
    refresh=1=强制今天重建（烧 token）；fresh=1=要今天的数据但已有今天缓存不重烧。"""
    denied = _rate_limited(request)
    if denied is not None:
        return denied
    out = get_dashboard(wallet, refresh=refresh, fresh=fresh)
    if isinstance(out, dict) and out.get("error"):
        return JSONResponse(status_code=_dashboard_status(out["error"]), content=out)
    return out


@router.get("/demo-wallets")
def demo_wallets():
    """已缓存看板的钱包清单（入口页"秒开"列表用）：这些钱包点开零 token 秒回。"""
    out, seen = [], set()
    try:
        for p in sorted(DASHBOARD_CACHE.glob(f"*_{BRIEFING_AS_OF}.json")):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            w = d.get("wallet")
            if not w or w.lower() in seen:
                continue
            seen.add(w.lower())
            prof = (d.get("identity") or {}).get("profile") or {}
            out.append({
                "wallet": w,
                "name": prof.get("name") or prof.get("pseudonym"),
                "market_question": ((d.get("position") or {}).get("meta") or {}).get("market"),
            })
    except Exception:
        pass
    return {"as_of": BRIEFING_AS_OF, "wallets": out}
