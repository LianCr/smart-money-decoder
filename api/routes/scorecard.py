"""api/routes/scorecard.py — 诚实记分牌路由（T2.3 从 main.py 原样搬出）。"""

from fastapi import APIRouter

from core.log import get_logger
from fetcher.heisenberg import call as hz_call, results as hz_results, AGENTS as HZ_AGENTS
import scorecard

router = APIRouter()
LOG = get_logger("api.scorecard")


def _log(msg: str) -> None:
    LOG.info(msg)


@router.get("/scorecard")
def scorecard_endpoint():
    """诚实记分牌：增量抓结算(574,免费) → 纯代码冷数字 + 行表（不调 AI、不算收益率）。"""
    def _resolve_574(cid):
        m = (hz_results(hz_call(HZ_AGENTS["markets"][0], {"condition_id": cid})) or
             hz_results(hz_call(HZ_AGENTS["markets"][0], {"condition_id": cid, "closed": "True"})))
        if not m:
            return None
        w = str(m[0].get("winning_outcome") or "").strip()
        return w if w in ("Yes", "No") else None
    try:
        filled = scorecard.fetch_settlements(_resolve_574)
        if filled:
            _log(f"   📒 记分牌新结算 {filled} 条")
    except Exception as e:
        _log(f"   ⚠ 记分牌抓结算失败: {e}")
    return scorecard.compute_scorecard()
