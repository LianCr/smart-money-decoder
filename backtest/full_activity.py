"""
backtest/full_activity.py

职责（回测专用）：按时间段翻某钱包的**全部**活动记录，作为历史持仓反推的原料。

与 fetcher/activity.py 的本质区别（见 CLAUDE.md「回测设计备忘」，必须独立，别合并）：
  - fetcher/activity.py：**正向流程**，最多 3 页（150 条），超出即如实降级 None。
    「超出 150 条即降级」是正向契约的一部分，不能动。
  - 本模块：**回测反推历史**，按时间段不设硬上限地翻页（可能几千条），独立翻页逻辑、
    独立边界处理。`fetcher/activity.py` 一行不改。

/activity 返回 newest-first（timestamp 降序），所以一旦翻到早于 start_time 的记录，
说明已越过时间窗的「老」边界，后面只会更旧，可提前停止翻页（省请求）。

网络错误沿用 ActivityAPIError（与 trades.py 一致，调用层一个 except 兜住）。
"""

import requests
from dotenv import load_dotenv

# 仅复用异常类型（网络错误），不复用任何翻页逻辑——翻页语义两边完全独立
from fetcher.activity import ActivityAPIError

load_dotenv()

DATA_API_BASE   = "https://data-api.polymarket.com"
REQUEST_TIMEOUT = 12
PAGE_SIZE       = 100
# 安全上限，防失控（20000 条远超任何真实钱包的活动量）；回测仍是「按时间段翻到底」
MAX_PAGES       = 200


# ── 函数1（内部）：拉一页活动记录 ─────────────────────────────────────────────
def _fetch_page(wallet: str, offset: int) -> list[dict]:
    """GET /activity 一页（newest-first）。不传 conditionId（服务器端过滤已知失效）。"""
    try:
        resp = requests.get(
            f"{DATA_API_BASE}/activity",
            params={"user": wallet, "limit": PAGE_SIZE, "offset": offset},
            timeout=REQUEST_TIMEOUT,
        )
    except requests.exceptions.Timeout:
        raise ActivityAPIError("API_TIMEOUT", "Activity API 请求超时，请稍后重试")
    except requests.exceptions.ConnectionError:
        raise ActivityAPIError("API_ERROR", "无法连接 Activity API，请检查网络")

    if resp.status_code == 429:
        raise ActivityAPIError("RATE_LIMITED", "请求频率超限，请等待几秒后重试")
    if resp.status_code != 200:
        raise ActivityAPIError("API_ERROR", f"Activity API 返回异常状态码：{resp.status_code}")

    return resp.json()


# ── 函数2（内部）：按时间窗筛一页 + 判断是否到老边界（纯逻辑，无网络）──────────
def _filter_page(
    records: list[dict],
    start_time: int | None,
    end_time: int | None,
) -> tuple[list[dict], bool]:
    """
    从一页（newest-first）记录里选出落在 [start_time, end_time]（闭区间）的记录。

    返回 (kept, reached_old_edge)：
      - kept：窗内记录（保持原 newest-first 顺序）
      - reached_old_edge：本页出现了早于 start_time 的记录 → 已越过老边界，可停翻页

    边界：start_time / end_time 为 None 表示该端不设界。缺 timestamp 的记录静默跳过。
    """
    kept: list[dict] = []
    reached_old_edge = False
    for r in records:
        ts = r.get("timestamp")
        if ts is None:
            continue
        ts = int(ts)
        if start_time is not None and ts < start_time:
            reached_old_edge = True
            continue
        if end_time is not None and ts > end_time:
            continue
        kept.append(r)
    return kept, reached_old_edge


# ── 对外入口 ───────────────────────────────────────────────────────────────────
def fetch_full_activity(
    wallet: str,
    start_time: int | None = None,
    end_time: int | None = None,
    max_pages: int = MAX_PAGES,
) -> list[dict]:
    """
    翻钱包的全活动流，返回落在 [start_time, end_time] 内的所有记录（newest-first）。

    成功：返回 list[dict]（可能为空）
    网络失败：向上抛 ActivityAPIError

    停翻页条件（任一满足）：
      1. 某页出现早于 start_time 的记录（已到老边界，后面只会更旧）
      2. 某页不足一页（活动流到底）
      3. 翻满 max_pages（安全上限）
    """
    out: list[dict] = []
    for page in range(max_pages):
        try:
            records = _fetch_page(wallet, page * PAGE_SIZE)
        except ActivityAPIError:
            # 翻页途中失败（多见于深 offset 触发 data-api 的 400 分页越界）→ 当作到底。
            # 仅首页失败才是真错误（坏地址 / 网络 / 限流），照常上抛。
            if page == 0:
                raise
            break
        if not records:
            break

        kept, reached_old_edge = _filter_page(records, start_time, end_time)
        out.extend(kept)

        if reached_old_edge:
            break
        if len(records) < PAGE_SIZE:
            break

    return out
