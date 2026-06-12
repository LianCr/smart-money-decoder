"""
backtest/snapshot.py

职责（回测第三块砖之一）：取某 outcome token 在历史某时刻的市场价格。

数据源（2026-06-12 实探确认）：CLOB prices-history
  GET clob.polymarket.com/prices-history?market=<tokenId>&startTs=&endTs=&fidelity=
  → {"history": [{"t": unix, "p": 0..1}, ...]}

token 是某个 outcome 的 CLOB token id（在活动/持仓记录里是 `asset` 字段）。
取离目标时刻最近的成交点；超出容差（默认 ±6h）视为无数据 → None
（短命市场在 T-7 时还没创建/没成交，会自然返回 None，上层据此跳过）。
"""

import requests

CLOB_BASE       = "https://clob.polymarket.com"
REQUEST_TIMEOUT = 12
DEFAULT_TOLERANCE = 6 * 3600  # 最近点离目标超过 6 小时就当没有


def get_price_at(token_id: str, ts: int, tolerance: int = DEFAULT_TOLERANCE) -> float | None:
    """
    token_id 在 unix 时刻 ts 的价格（0..1）。无数据 / 超容差 / 失败 → None。

    纯展示/回测用，**吞掉网络异常返回 None**：单个时点拿不到价不该让整条回测崩。
    """
    if not token_id:
        return None
    try:
        r = requests.get(
            f"{CLOB_BASE}/prices-history",
            params={"market": token_id, "startTs": ts - tolerance, "endTs": ts + tolerance, "fidelity": 60},
            timeout=REQUEST_TIMEOUT,
        )
    except requests.exceptions.RequestException:
        return None
    if r.status_code != 200:
        return None
    try:
        history = r.json().get("history", [])
    except Exception:
        return None
    if not history:
        return None
    near = min(history, key=lambda x: abs(x.get("t", 0) - ts))
    if abs(near.get("t", 0) - ts) > tolerance:
        return None
    try:
        return float(near["p"])
    except (KeyError, TypeError, ValueError):
        return None
