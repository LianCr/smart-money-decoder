"""
fetcher/trades.py

职责（v2 建仓时间）：按「市场维度」查某钱包在某个市场的**第一次买入**时间。

与老 fetcher/activity.py 的关键区别（两处都要看清，别混用）：
  1. 数据源不同：
     - activity.py 翻该钱包的「全活动流」（/activity），最多 150 条，超出即降级 None。
       whale 持有的老仓位，其建仓动作常落在 150 条窗口之外，于是查不到。
     - trades.py 用 /trades?market=<conditionId>&user=<wallet>，**服务器端按市场精确过滤
       有效**（实测伊朗 98 条全部命中、Newsom 6 条全部命中——后者正是 activity 翻 2000
       条都找不到的老仓位）。按市场维度查，天然不受全活动流条数上限拖累。
  2. 取哪一笔不同：
     - activity.py 取「最近一次」BUY（max 时间戳）。
     - trades.py 取「**最早一次**」BUY（min 时间戳）。建仓时间 = 第一次买入，
       这才是真正的入场点；后续加仓不改变「何时建立这个 thesis」。

/trades 接口本身只返回成交（BUY/SELL），没有 REDEEM/REWARD，所以无需像 activity.py
那样再过滤 type=="TRADE"，只认 side=="BUY" 即可。

错误处理沿用 ActivityAPIError（直接复用同一异常类，让调用层一个 except 兜住 v2 与
fallback 两条路）。
"""

import requests
from dotenv import load_dotenv

# 复用 activity 层的异常类型，调用方 except ActivityAPIError 即可同时兜住两条路
from fetcher.activity import ActivityAPIError

load_dotenv()

DATA_API_BASE   = "https://data-api.polymarket.com"
REQUEST_TIMEOUT = 10
PAGE_SIZE       = 100
# 单市场 + 单用户的成交数有限（重仓 whale 实测也就近百条），10 页 = 1000 条足够兜底
MAX_PAGES       = 10


# ── 函数1（内部）：拉取一页该市场的成交记录 ───────────────────────────────────
def _fetch_trades_page(address: str, condition_id: str, offset: int) -> list[dict]:
    """
    GET /trades，按 market(conditionId) + user 服务器端过滤（实测有效）。
    返回降序（最新在前）的成交列表。
    """
    try:
        resp = requests.get(
            f"{DATA_API_BASE}/trades",
            params={
                "user":   address,
                "market": condition_id,
                "limit":  PAGE_SIZE,
                "offset": offset,
            },
            timeout=REQUEST_TIMEOUT,
        )
    except requests.exceptions.Timeout:
        raise ActivityAPIError("API_TIMEOUT", "Trades API 请求超时，请稍后重试")
    except requests.exceptions.ConnectionError:
        raise ActivityAPIError("API_ERROR", "无法连接 Trades API，请检查网络")

    if resp.status_code == 429:
        raise ActivityAPIError("RATE_LIMITED", "请求频率超限，请等待几秒后重试")
    if resp.status_code != 200:
        raise ActivityAPIError("API_ERROR", f"Trades API 返回异常状态码：{resp.status_code}")

    return resp.json()


# ── 函数2（内部）：从一批成交里取最早的 BUY 时间戳（纯逻辑，无网络）───────────
def _earliest_buy(records: list[dict], condition_id: str) -> int | None:
    """
    过滤 conditionId 匹配 + side=="BUY"，取**最小**（最早）时间戳。

    - 服务器端已按 market 过滤，这里再本地核一遍 conditionId 纯属防御性兜底。
    - 用 .get() 而非 []，字段缺失静默跳过，不崩。
    - 用 min() 而非依赖 API 排序，逻辑自洽。
    """
    matched = []
    for record in records:
        if (
            record.get("conditionId") == condition_id
            and record.get("side")    == "BUY"
        ):
            ts = record.get("timestamp")
            if ts is not None:
                matched.append(int(ts))
    return min(matched) if matched else None


# ── 对外唯一入口 ───────────────────────────────────────────────────────────────
def get_entry_time_v2(address: str, condition_id: str) -> int | None:
    """
    查询钱包在某市场的**第一次买入**时间戳（Unix 秒）。

    成功：返回 int（最早一笔 BUY 的 timestamp）
    找不到：返回 None（该市场无买入记录，如实降级，不伪造）
    网络失败：向上抛 ActivityAPIError，由调用层统一处理

    实现要点：/trades 降序返回（最新在前），最早的 BUY 落在末页，
    因此必须翻完所有页、跨页取全局 min，不能只看第一页。
    """
    earliest: int | None = None

    for page in range(MAX_PAGES):
        offset  = page * PAGE_SIZE
        records = _fetch_trades_page(address, condition_id, offset)

        page_earliest = _earliest_buy(records, condition_id)
        if page_earliest is not None:
            earliest = page_earliest if earliest is None else min(earliest, page_earliest)

        # 不足一页说明已到底，停止翻页
        if len(records) < PAGE_SIZE:
            break

    return earliest
