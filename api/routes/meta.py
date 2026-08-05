"""api/routes/meta.py — 探活 + 静态回测存档（零业务只读；T2.3 从 main.py 原样搬出）。"""

import json
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


@router.get("/healthz")
def healthz():
    """真探活：必填 key 齐不齐 + 缓存目录写不写得动。判定口径见 core/health.py。

    不健康返回 **503**，让部署/负载均衡当场知道 —— 这正是 P0-2 那次事故缺的东西：
    实例起来了、首页能开、一点陌生钱包就 502，而没有任何地方会告诉你。
    本端点只做转发，逻辑全在 core/health（纯函数、可单测，与 api 装配解耦）。"""
    r = health_report()
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
