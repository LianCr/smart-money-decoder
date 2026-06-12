"""
backtest/resolution.py

职责（回测第二步）：conditionId → 真实结算结果（获胜方 + 实际结算时间戳）。

2026-06-12 实探确认的读法（Gamma /markets）：
  - 查询**必须带 `closed=true`**：Gamma 默认过滤掉已结算市场，不带则返回 0
    ——这正是此前「按 conditionId 反查失效」的真因（不是 conditionId 不能用）。
  - `closed: true`            → 已结算标识
  - `outcomes` / `outcomePrices` 是 **JSON 字符串**（`'["Yes","No"]'` / `'["0","1"]'`），
    需 json.loads。获胜方 = 定格价 argmax 对应的 outcome（`["0","1"]`→No 赢，
    `["1","0"]`→Yes 赢）。
  - `closedTime`（实际结算，非标准格式 `2026-06-11 06:13:57+00`）= T 锚；
    `endDate`（ISO，预定结算日）留作参考。两者可能差几小时到几天（事件提前结算）。

网络错误沿用 ActivityAPIError（与 backtest/full_activity.py 一致，回测模块统一一个
异常类型，reason 字段区分来源）。
"""

import json
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

from fetcher.activity import ActivityAPIError  # 回测模块统一复用的 API 异常类型

load_dotenv()

GAMMA_BASE      = "https://gamma-api.polymarket.com"
REQUEST_TIMEOUT = 12

# 定格价高于此阈值才认定为「干净结算」的获胜方（防 0.5/0.5 等未结算或异常态）
WIN_PRICE_MIN = 0.99


# ── 函数1（内部，纯逻辑）：解析 gamma 的 JSON 字符串字段 ───────────────────────
def _parse_json_field(v):
    """outcomes / outcomePrices 是 JSON 字符串；已是 list 则原样返回；失败返回 None。"""
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return None
    return None


# ── 函数2（内部，纯逻辑）：定格价 → 获胜方 ────────────────────────────────────
def _winner_from_prices(outcomes, prices) -> str | None:
    """
    获胜方 = 定格价 argmax 对应的 outcome。

    无明显定格在 ~1 的一侧（如 0.5/0.5，未干净结算）→ 返回 None。
    outcomes / prices 可为 list 或 JSON 字符串。
    """
    outs = _parse_json_field(outcomes)
    prs  = _parse_json_field(prices)
    if not outs or not prs or len(outs) != len(prs):
        return None
    try:
        fp = [float(p) for p in prs]
    except (TypeError, ValueError):
        return None
    mx = max(fp)
    if mx < WIN_PRICE_MIN:
        return None
    return outs[fp.index(mx)]


# ── 函数3（内部，纯逻辑）：容错解析时间戳 → unix 秒 ───────────────────────────
def _parse_ts(s) -> int | None:
    """
    closedTime（`2026-06-11 06:13:57+00`）/ endDate（`2026-06-11T03:59:00Z`）→ unix 秒。
    容忍：空格分隔、`Z`、两位时区偏移 `+00`、无时区（按 UTC）。失败返回 None。
    """
    if not s:
        return None
    s = str(s).strip().replace("Z", "+00:00")
    if s.endswith("+00"):
        s = s + ":00"
    if " " in s and "T" not in s:
        s = s.replace(" ", "T", 1)
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except ValueError:
        return None


# ── 对外入口 ───────────────────────────────────────────────────────────────────
def get_market_resolution(condition_id: str) -> dict | None:
    """
    查 conditionId 的真实结算结果。

    成功（已干净结算）：返回 dict：
      {
        "condition_id":   str,
        "winning_outcome": str,   # "Yes"/"No"（定格价 argmax 对应的 outcome）
        "resolved_time":  int,    # 实际结算 unix 秒（closedTime 优先，回退 endDate）= T 锚
        "scheduled_end":  int|None, # endDate（预定结算日），参考用
        "question":       str,
        "slug":           str,
      }
    未结算 / 查不到 / 未干净结算 → 返回 None（合法，回测跳过该市场）。
    网络/HTTP 失败 → 抛 ActivityAPIError（reason 以 GAMMA_ 开头）。

    关键：必须带 closed=true，否则 gamma 不返回已结算市场。
    """
    try:
        resp = requests.get(
            f"{GAMMA_BASE}/markets",
            params={"condition_ids": condition_id, "closed": "true"},
            timeout=REQUEST_TIMEOUT,
        )
    except requests.exceptions.Timeout:
        raise ActivityAPIError("GAMMA_TIMEOUT", "Gamma 结算查询超时，请稍后重试")
    except requests.exceptions.ConnectionError:
        raise ActivityAPIError("GAMMA_UNREACHABLE", "无法连接 Gamma，请检查网络")

    if resp.status_code != 200:
        raise ActivityAPIError("GAMMA_HTTP_ERROR", f"Gamma 返回状态码 {resp.status_code}")

    data = resp.json()
    if not isinstance(data, list) or not data:
        return None  # 没有已结算市场命中该 conditionId

    m = data[0]
    # 服务器端过滤可能不严，本地再核一遍 conditionId + closed
    if m.get("conditionId") != condition_id or not m.get("closed"):
        return None

    winner = _winner_from_prices(m.get("outcomes"), m.get("outcomePrices"))
    if winner is None:
        return None  # 未干净结算（无明确获胜方）

    resolved_time = _parse_ts(m.get("closedTime")) or _parse_ts(m.get("endDate"))
    return {
        "condition_id":    condition_id,
        "winning_outcome": winner,
        "resolved_time":   resolved_time,
        "scheduled_end":   _parse_ts(m.get("endDate")),
        "question":        m.get("question"),
        "slug":            m.get("slug"),
    }
