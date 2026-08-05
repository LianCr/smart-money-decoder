"""api/routes/scorecard.py — 诚实对账路由：记分牌 + 信心回验（T2.5）。"""

from fastapi import APIRouter

from core.log import get_logger
from fetcher.heisenberg import call as hz_call, results as hz_results, AGENTS as HZ_AGENTS
import confidence_replay
import scorecard

router = APIRouter()
LOG = get_logger("api.scorecard")


def _log(msg: str) -> None:
    LOG.info(msg)


def _resolve_574(cid):
    """cid → 结算结果 "Yes"/"No"/None（574 markets agent，免费零 token）。
    记分牌与回验共用；两处 settle 都由调用方注入它，模块本身不依赖 heisenberg。"""
    m = (hz_results(hz_call(HZ_AGENTS["markets"][0], {"condition_id": cid})) or
         hz_results(hz_call(HZ_AGENTS["markets"][0], {"condition_id": cid, "closed": "True"})))
    if not m:
        return None
    w = str(m[0].get("winning_outcome") or "").strip()
    return w if w in ("Yes", "No") else None


@router.get("/scorecard")
def scorecard_endpoint():
    """诚实记分牌：增量抓结算(574,免费) → 纯代码冷数字 + 行表（不调 AI、不算收益率）。"""
    try:
        filled = scorecard.fetch_settlements(_resolve_574)
        if filled:
            _log(f"   📒 记分牌新结算 {filled} 条")
    except Exception as e:
        _log(f"   ⚠ 记分牌抓结算失败: {e}")
    return scorecard.compute_scorecard()


@router.get("/confidence-replay")
def confidence_replay_endpoint(settle: int = 0):
    """信心回验（P1-6/T2.5）：high/med/low 分档命中率 + guard_flags 交叉，纯代码零 AI。
    裸 GET = 纯读（喂前端，不打外网不落盘）；`?settle=1` 先跑增量结算再返回
    （574 免费幂等，手动触发即 curl "$HOST/confidence-replay?settle=1"）。"""
    if settle:
        try:
            n = confidence_replay.settle(_resolve_574)
            if n:
                _log(f"   🔁 回验新结算 {n} 条")
        except Exception as e:
            _log(f"   ⚠ 回验抓结算失败: {e}")
    return confidence_replay.compute()
