"""
fetcher/polymarket.py

职责：只管"从 Polymarket 拿数据"，不做任何 AI 分析或展示。
数据流（共 2 次网络请求）：
  请求1 → data-api.polymarket.com/positions  → 用户所有持仓
  请求2 → gamma-api.polymarket.com/events    → 批量拿 tags，判断是否政治类
  本地  → 过滤 + 排序，找出最大政治仓位
"""

import re
import requests

# ── 配置项 ────────────────────────────────────────────────────────────────────
# 想扩展类别时只改这里，例如加入 "ipos" / "geopolitics"
ALLOWED_TAG_SLUGS = ["politics"]

# 过滤掉价值低于此阈值的"噪音仓位"，单位 USDC
MIN_POSITION_VALUE_USD = 5000

DATA_API_BASE  = "https://data-api.polymarket.com"
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


# ── 函数1：地址验证 ────────────────────────────────────────────────────────────
def validate_wallet_address(address: str) -> str:
    """
    验证以太坊钱包地址格式，通过则返回统一小写地址，否则抛 ValueError。
    以太坊地址规则：0x 开头 + 40 位十六进制字符 = 共 42 位。
    """
    if not isinstance(address, str):
        raise ValueError("地址必须是字符串类型")

    address = address.strip()

    if len(address) != 42:
        raise ValueError(f"地址长度错误：应为 42 位，实际 {len(address)} 位")

    # re.match 只检查开头，这里用 fullmatch 的等价写法确保全串匹配
    if not re.match(r'^0x[0-9a-fA-F]{40}$', address):
        raise ValueError("地址格式错误：须以 0x 开头，后接 40 位十六进制字符（0-9, a-f）")

    return address.lower()


# ── 函数2：拉取用户持仓 ────────────────────────────────────────────────────────
def fetch_user_positions(address: str) -> list[dict]:
    """
    从 data-api 拉取该钱包的所有持仓，原始数据不过滤。
    sizeThreshold=0.01 只过滤接近零的"灰尘仓位"，减少无效数据量。
    """
    params = {
        "user":           address,
        "sizeThreshold":  0.01,
        "limit":          500,       # API 最大值，确保不遗漏
        "sortBy":         "CURRENT", # 按当前价值降序，让大仓位在前
        "sortDirection":  "DESC",
    }

    try:
        resp = requests.get(
            f"{DATA_API_BASE}/positions",
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.exceptions.Timeout:
        raise PolymarketAPIError("API_TIMEOUT", "Polymarket 请求超时，请稍后重试")
    except requests.exceptions.ConnectionError:
        raise PolymarketAPIError("API_ERROR", "无法连接 Polymarket，请检查网络")

    if resp.status_code == 429:
        raise PolymarketAPIError("RATE_LIMITED", "请求过于频繁，请等待几秒后重试")

    if resp.status_code != 200:
        raise PolymarketAPIError("API_ERROR", f"Polymarket 返回异常状态码：{resp.status_code}")

    return resp.json()


# ── 函数3：批量拉取 event 详情 ─────────────────────────────────────────────────
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


# ── 内部辅助：判断是否政治类 ──────────────────────────────────────────────────
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


# ── 函数4：过滤 + 选出最大政治仓位（纯逻辑，无网络）────────────────────────────
def filter_top_political_position(
    positions: list[dict],
    events_map: dict[str, dict],
) -> dict | None:
    """
    从所有持仓里找出满足条件的最大政治仓位。
    此函数无任何网络请求，可以直接用 mock 数据测试。

    过滤条件（三个缺一不可）：
      1. event 属于政治类（tag slug 在 ALLOWED_TAG_SLUGS 里）
      2. redeemable == False（市场尚未结算）
      3. currentValue >= MIN_POSITION_VALUE_USD（仓位价值足够大）
    """
    qualified = []

    for pos in positions:
        event_id = str(pos.get("eventId", ""))
        event    = events_map.get(event_id)

        # event 信息缺失时跳过（防御性处理，正常不会发生）
        if not event:
            continue

        if not _is_political_event(event):
            continue

        # redeemable=True 代表市场已结算，curPrice 归零，不展示给用户
        if pos.get("redeemable", False):
            continue

        if float(pos.get("currentValue", 0)) < MIN_POSITION_VALUE_USD:
            continue

        qualified.append(pos)

    if not qualified:
        return None

    # 取价值最大的那一个
    return max(qualified, key=lambda p: float(p.get("currentValue", 0)))


# ── 内部辅助：原始字段 → 干净数据结构 ─────────────────────────────────────────
def _format_position(raw: dict) -> dict:
    """
    把 API 原始字段名映射成项目内统一字段名。
    这样 AI 解码层和渲染层不需要知道 API 的原始字段，
    将来 API 字段名变了只改这一处。
    """
    return {
        "market_id":       raw.get("conditionId"),
        "market_question": raw.get("title"),
        "outcome":         raw.get("outcome"),        # "Yes" 或 "No"
        "size":            float(raw.get("size", 0)),
        "entry_price":     raw.get("avgPrice"),        # 注意：可能为 None
        "current_price":   float(raw.get("curPrice", 0)),
        "position_value":  float(raw.get("currentValue", 0)),
        "cash_pnl":        float(raw.get("cashPnl", 0)),
        "pnl_pct":         float(raw.get("percentPnl", 0)),
        "event_id":        str(raw.get("eventId", "")),
        "event_slug":      raw.get("eventSlug"),
    }


# ── 对外唯一入口 ───────────────────────────────────────────────────────────────
def get_top_political_position(address: str) -> dict:
    """
    输入钱包地址，返回该钱包最大政治仓位的解析结果。

    成功：返回干净的仓位字典（见 _format_position）
    失败：返回 {"error": True, "reason": "...", "message": "..."}
          reason 枚举值：INVALID_ADDRESS / NO_POSITIONS / NO_POLITICAL_POSITIONS
                         ALL_BELOW_MIN_VALUE / API_TIMEOUT / RATE_LIMITED / API_ERROR
    """
    # 第一步：验证地址格式
    try:
        address = validate_wallet_address(address)
    except ValueError as e:
        return {"error": True, "reason": "INVALID_ADDRESS", "message": str(e)}

    # 第二步：拉取所有持仓
    try:
        positions = fetch_user_positions(address)
    except PolymarketAPIError as e:
        return {"error": True, "reason": e.reason, "message": e.message}

    if not positions:
        return {
            "error":   True,
            "reason":  "NO_POSITIONS",
            "message": "该钱包在 Polymarket 没有任何持仓记录",
        }

    # 第三步：收集所有 eventId，批量拉取 event 详情
    event_ids = list({
        str(p["eventId"])
        for p in positions
        if p.get("eventId")
    })

    try:
        events_map = fetch_events_by_ids(event_ids)
    except PolymarketAPIError as e:
        return {"error": True, "reason": e.reason, "message": e.message}

    # 第四步：过滤 + 选出最大政治仓位
    top_raw = filter_top_political_position(positions, events_map)

    if top_raw is None:
        # 区分"完全没政治盘"和"有但金额不够"，给用户更准确的提示
        has_any_political = any(
            _is_political_event(events_map.get(str(p.get("eventId", "")), {}))
            for p in positions
            if not p.get("redeemable", False)
        )
        if has_any_political:
            return {
                "error":   True,
                "reason":  "ALL_BELOW_MIN_VALUE",
                "message": f"该钱包有政治盘持仓，但全部低于 ${MIN_POSITION_VALUE_USD:,} 阈值",
            }
        return {
            "error":   True,
            "reason":  "NO_POLITICAL_POSITIONS",
            "message": "该钱包没有政治类预测盘的持仓",
        }

    formatted = _format_position(top_raw)
    event = events_map.get(str(top_raw.get("eventId", "")), {})
    formatted["resolution_criteria"] = event.get("description")
    formatted["resolution_date"] = event.get("endDate")
    return formatted
