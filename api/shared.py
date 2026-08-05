"""
api/shared.py — 跨路由共享件（T2.3 拆分时从 main.py 原样搬出，零逻辑改动）。

🔴 `_RATE_LIMITER` 是**内存态单例**：滑动窗口和每日全局计数都在实例里——
全仓只许这一份，任何路由 import 使用、绝不自行构造第二个（两份=限流额度翻倍）。
"""

from fastapi import Request
from fastapi.responses import JSONResponse

from core.config import RATE_LIMIT_DAILY_GLOBAL, RATE_LIMIT_PER_IP, RATE_LIMIT_WINDOW_SECONDS
from core.log import get_logger
from core.ratelimit import RateLimiter

LOG = get_logger("api")


def _err(status: int, reason: str, message: str) -> JSONResponse:
    """统一错误出口，body 形如 {"error": reason, "message": ...}。"""
    LOG.warning(f"   ✗ [{status}] {reason} — {message}")
    return JSONResponse(status_code=status, content={"error": reason, "message": message})


# ── 入站限流（P1-15）：只闸真烧 token 的 /dashboard；阈值在 core/config.py。
# 🔴 闸防"额度被刷空"，不是关门——「完全开放」的产品决策不变。进程内 ai_verify 不经
# 路由、天然不受闸（扫榜是用户主动批准的批量烧）。
_RATE_LIMITER = RateLimiter(RATE_LIMIT_PER_IP, RATE_LIMIT_WINDOW_SECONDS, RATE_LIMIT_DAILY_GLOBAL)


def _client_ip(request: Request) -> str:
    """Render 代理层设 X-Forwarded-For（首项=真实客户端）；本地直连退回 socket 对端。
    直连时该头可伪造——所以每日全局硬闸不认 IP，是刷不开的兜底。"""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _rate_limited(request: Request) -> JSONResponse | None:
    """过闸：放行返回 None；超限返回 429（人话 message + retry_after 已在闸里备好）。"""
    denied = _RATE_LIMITER.check(_client_ip(request))
    if denied is None:
        return None
    LOG.warning(f"   ✗ [429] {denied['error']} ip={_client_ip(request)[:24]}")
    return JSONResponse(status_code=429, content=denied)
