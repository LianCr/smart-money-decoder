"""api/routes/meta.py — 探活 + 静态回测存档（零业务只读；T2.3 从 main.py 原样搬出）。"""

import json
import time
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from core.health import health_report
from core.log import get_logger

router = APIRouter()
LOG = get_logger("api.meta")


def _log(msg: str) -> None:
    LOG.info(msg)


BACKTEST_RESULT = Path("backtest/lift_result.json")   # 整体 lift 汇总（git 跟踪、手填自 lift_v1.md，不重跑）
CASES_PATH      = Path("backtest/cases.json")          # 6 个案例故事卡（git 跟踪、手填自 final_samples.md）


# ── P2-28 数据层真探针：一发最便宜的 574，按 reason 分类；TTL 缓存防 Render 高频
# 探活把额度打穿/打出 429（探活本身不能成为新的额度杀手）。探针只在 key 在场时被
# health_report 调用；分类逻辑在 core/health（纯函数可测），这里只供弹药。
_PROBE_TTL_SECONDS = 600
_probe_state = {"t": 0.0, "reason": None, "primed": False}


def _data_probe():
    now = time.time()
    if _probe_state["primed"] and now - _probe_state["t"] < _PROBE_TTL_SECONDS:
        return _probe_state["reason"]
    try:
        from fetcher.heisenberg import call as hz_call
        hz_call(574, {"condition_id": "0x0"}, limit=1)   # 任何 200（含空结果）= 数据层通
        reason = None
    except Exception as e:
        reason = getattr(e, "reason", None) or f"PROBE_ERROR:{type(e).__name__}"
    _probe_state.update(t=now, reason=reason, primed=True)
    return reason


@router.get("/healthz")
def healthz():
    """真探活：必填 key 齐不齐 + 缓存目录写不写得动 + 数据层真探针（P2-28：能区分
    "key 缺失"与"key 在但额度尽"——后者 2026-08-05 真实发生过，被缓存掩盖毫无提示）。
    判定口径见 core/health.py。

    不健康返回 **503**，让部署/负载均衡当场知道 —— 这正是 P0-2 那次事故缺的东西：
    实例起来了、首页能开、一点陌生钱包就 502，而没有任何地方会告诉你。
    本端点只做转发，逻辑全在 core/health（纯函数、可单测，与 api 装配解耦）。"""
    r = health_report(data_probe=_data_probe)
    return JSONResponse(status_code=200 if r["ok"] else 503, content=r)


@router.get("/backtest")
def backtest():
    """
    Track Record：6 个案例故事卡（主体）+ 整体 lift 汇总（进阶）。

    两者都是 git 跟踪的静态文件、零 token、不重跑：
      - cases  ← backtest/cases.json（手填自 final_samples.md，含 T-7/T-1 演变）
      - lift   ← backtest/lift_result.json（N=94 汇总，给想深究的人）
    """
    out = {"cases": [], "summary": {}, "lift": None}
    try:
        cj = json.loads(CASES_PATH.read_text(encoding="utf-8"))
        out["cases"] = cj.get("cases", [])
        out["summary"] = cj.get("summary", {})
    except Exception as e:
        _log(f"\n=== /backtest cases 读取失败：{e} ===")
    try:
        out["lift"] = json.loads(BACKTEST_RESULT.read_text(encoding="utf-8"))
    except Exception as e:
        _log(f"\n=== /backtest lift 读取失败：{e} ===")
    _log(f"\n=== /backtest （{len(out['cases'])} 案例 + lift 汇总）===")
    return out
