"""
fetcher/polymarket.py — Gamma API 的 event 详情 + 政治类判定（回测在用）。

（2026-08-03 瘦身：v2 /analyze 解读卡链路下架，本文件的持仓拉取/最大政治仓选择
（validate_wallet_address / fetch_user_positions / filter_top_political_position /
get_top_political_position）随之删除，见 git 历史。正向流程的"最大政治仓"唯一实现
= fetcher/positions.py 的 Heisenberg 版。这里保留的是 backtest/pipeline.py 及诊断
脚本仍依赖的两块：批量 event 详情 + tags 政治判定。）
"""

import requests

# ── 配置项 ────────────────────────────────────────────────────────────────────
# 想扩展类别时只改这里，例如加入 "ipos" / "geopolitics"
ALLOWED_TAG_SLUGS = ["politics"]

GAMMA_API_BASE = "https://gamma-api.polymarket.com"
REQUEST_TIMEOUT = 10  # 秒，超过则认定超时


# ── 自定义异常 ────────────────────────────────────────────────────────────────
class PolymarketAPIError(Exception):
    """
    网络请求失败时统一抛这个异常，携带 reason（机器读）和 message（人读）。
    这样上层调用者可以按 reason 做分支处理，而不是解析字符串。
    """
    def __init__(self, reason: str, message: str):
        self.reason  = reason
        self.message = message
        super().__init__(message)


# ── 批量拉取 event 详情 ───────────────────────────────────────────────────────
def fetch_events_by_ids(event_ids: list[str]) -> dict[str, dict]:
    """
    批量查询 Gamma API 获取 event 详情（含 tags）。
    返回 {event_id: event_detail} 字典，方便后续按 id 查找。

    为什么批量而不是逐条请求？
    一个钱包可能有 20-50 个仓位，逐条请求会发 20-50 次 HTTP，
    批量则只需 1 次，大幅降低耗时和触发限流的概率。
    """
    if not event_ids:
        return {}

    # Gamma API 用 HTTP 多值参数传多个 id（?id=1&id=2），不支持逗号分隔
    params = [("id", eid) for eid in event_ids]
    params.append(("limit", 500))

    try:
        resp = requests.get(
            f"{GAMMA_API_BASE}/events",
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.exceptions.Timeout:
        raise PolymarketAPIError("API_TIMEOUT", "Gamma API 请求超时，请稍后重试")
    except requests.exceptions.ConnectionError:
        raise PolymarketAPIError("API_ERROR", "无法连接 Gamma API，请检查网络")

    if resp.status_code == 429:
        raise PolymarketAPIError("RATE_LIMITED", "Gamma API 请求过于频繁，请等待几秒后重试")

    if resp.status_code != 200:
        raise PolymarketAPIError("API_ERROR", f"Gamma API 返回异常状态码：{resp.status_code}")

    # 转成字典：{str(event_id): event_dict}
    return {str(event["id"]): event for event in resp.json()}


# ── 判断是否政治类 ────────────────────────────────────────────────────────────
def _is_political_event(event: dict) -> bool:
    """
    检查 event 的 tags 列表，是否包含 ALLOWED_TAG_SLUGS 中的任意 slug。
    用 slug 而不是 label，因为 slug 是小写稳定字符串，label 可能随版本改大小写。
    """
    tags = event.get("tags") or []
    for tag in tags:
        if isinstance(tag, dict) and tag.get("slug") in ALLOWED_TAG_SLUGS:
            return True
    return False
