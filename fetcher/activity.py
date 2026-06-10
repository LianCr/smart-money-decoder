"""
fetcher/activity.py

职责：查询某钱包在某个市场的最近一次买入时间。
核心结论（来自真实 API 验证）：
  - 服务器端 conditionId 过滤失效，必须拉全量数据本地过滤
  - 只认 side=="BUY" 且 type=="TRADE"，REDEEM / SELL 全部排除
  - 最多翻 3 页（150 条），找不到如实返回 None，不伪造
"""

import requests
from dotenv import load_dotenv

load_dotenv()

DATA_API_BASE  = "https://data-api.polymarket.com"
REQUEST_TIMEOUT = 10
PAGE_SIZE       = 50
MAX_PAGES       = 3


# ── 自定义异常 ────────────────────────────────────────────────────────────────
class ActivityAPIError(Exception):
    """网络请求失败时统一抛这个，携带机器读的 reason 和人读的 message"""
    def __init__(self, reason: str, message: str):
        self.reason  = reason
        self.message = message
        super().__init__(message)


# ── 函数1（内部）：拉取一页活动记录 ───────────────────────────────────────────
def _fetch_activity_page(address: str, offset: int) -> list[dict]:
    """
    拉取该钱包的第 N 页活动记录（offset=0/50/100 对应第1/2/3页）。
    不传 conditionId，因为服务器端过滤已验证失效。
    """
    try:
        resp = requests.get(
            f"{DATA_API_BASE}/activity",
            params={
                "user":   address,
                "limit":  PAGE_SIZE,
                "offset": offset,
            },
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


# ── 函数2（内部）：在一页记录里找最近买入时间戳（纯逻辑，无网络）────────────
def _find_latest_buy(records: list[dict], condition_id: str) -> int | None:
    """
    从一批活动记录里找出目标市场最近一次有效买入的时间戳。

    过滤条件：conditionId 匹配 + side=="BUY" + type=="TRADE"
    用 .get() 而不是 []，字段缺失时静默跳过，不崩溃。
    用 max() 取最大时间戳，不依赖 API 返回顺序的保证。
    """
    matched = []

    for record in records:
        if (
            record.get("conditionId") == condition_id
            and record.get("side")    == "BUY"
            and record.get("type")    == "TRADE"
        ):
            ts = record.get("timestamp")
            if ts is not None:
                matched.append(int(ts))

    return max(matched) if matched else None


# ── 对外唯一入口 ───────────────────────────────────────────────────────────────
def get_entry_time(address: str, condition_id: str) -> int | None:
    """
    查询钱包在某个市场的最近一次买入时间戳（Unix 秒）。

    成功：返回 int（timestamp）
    找不到：返回 None，如实告知，绝不伪造
    网络失败：向上抛 ActivityAPIError，由调用层统一处理
    """
    for page in range(MAX_PAGES):
        offset  = page * PAGE_SIZE
        records = _fetch_activity_page(address, offset)

        result = _find_latest_buy(records, condition_id)
        if result is not None:
            return result

        # 这一页不足 50 条，说明数据已经到底，不再翻下一页避免白发请求
        if len(records) < PAGE_SIZE:
            break

    return None
