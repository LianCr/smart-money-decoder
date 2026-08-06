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


_SETTLE_CONFLICTS = []       # 本次 settle 扫描发现的 574/575 结算矛盾（如实随响应下发，不猜）


def _resolve_574(cid):
    """cid → 结算结果 "Yes"/"No"/None（574 winning_outcome 为主 + 575 winning_side 交叉，T1）。
    574 `winning_outcome` 是**未文档化字段**（坑表 2026-08-07）——575 有文档化的 `winning_side`
    可交叉：两者都在且矛盾 → 记 conflicts、返回 None（保持 pending，不猜）；575 缺/挂 →
    574 单裁（交叉是加固不是新硬依赖，实测 winning_side 常为 null）。记分牌与回验共用注入。"""
    m = (hz_results(hz_call(HZ_AGENTS["markets"][0], {"condition_id": cid})) or
         hz_results(hz_call(HZ_AGENTS["markets"][0], {"condition_id": cid, "closed": "True"})))
    if not m:
        return None
    w = str(m[0].get("winning_outcome") or "").strip()
    if w not in ("Yes", "No"):
        return None
    try:
        m575 = hz_results(hz_call(575, {"condition_id": cid}))
        side = str(((m575[0] if m575 else {}) or {}).get("winning_side") or "").strip()
    except Exception:
        side = ""
    if side in ("Yes", "No") and side != w:
        _SETTLE_CONFLICTS.append({"cid": cid, "winning_outcome_574": w, "winning_side_575": side})
        _log(f"   ⚠ 结算矛盾 {cid[:14]}…：574={w} vs 575={side} —— 保持 pending 不猜")
        return None
    return w


@router.get("/scorecard")
def scorecard_endpoint():
    """诚实记分牌：增量抓结算(574,免费) → 纯代码冷数字 + 行表（不调 AI、不算收益率）。"""
    _SETTLE_CONFLICTS.clear()
    try:
        filled = scorecard.fetch_settlements(_resolve_574)
        if filled:
            _log(f"   📒 记分牌新结算 {filled} 条")
    except Exception as e:
        _log(f"   ⚠ 记分牌抓结算失败: {e}")
    out = scorecard.compute_scorecard()
    out["settle_conflicts"] = list(_SETTLE_CONFLICTS)   # 574/575 矛盾盘如实下发（保持 pending）
    return out


@router.get("/confidence-replay")
def confidence_replay_endpoint(settle: int = 0):
    """信心回验（P1-6/T2.5）：high/med/low 分档命中率 + guard_flags 交叉，纯代码零 AI。
    裸 GET = 纯读（喂前端，不打外网不落盘）；`?settle=1` 先跑增量结算再返回
    （574 免费幂等，手动触发即 curl "$HOST/confidence-replay?settle=1"）。"""
    if settle:
        _SETTLE_CONFLICTS.clear()
        try:
            n = confidence_replay.settle(_resolve_574)
            if n:
                _log(f"   🔁 回验新结算 {n} 条")
        except Exception as e:
            _log(f"   ⚠ 回验抓结算失败: {e}")
        out = confidence_replay.compute()
        out["settle_conflicts"] = list(_SETTLE_CONFLICTS)
        return out
    return confidence_replay.compute()
