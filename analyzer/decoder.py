"""
analyzer/decoder.py

职责：拿 fetcher 层组装好的 assembled dict，跑置信度矩阵，
调课堂网关生成解读卡片，并做严格的代码层校验。

设计原则：
  - 置信度由代码先算（computed_confidence），模型只解释不改判
  - warnings 由代码生成，不经过模型（防止幻觉伪造降级原因）
  - 模型违反硬约束（改置信度 / 编催化剂 / 乱填 follow_call）一律抛异常
"""

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from core.llm import call_gateway, GatewayError
from core.jsonstore import atomic_write_json
from analyzer import guards
from analyzer.guards import FOLLOW_CALL_ENUM  # noqa: F401  正本已收口 guards.py，re-export 兼容旧引用

# ── 配置项 ────────────────────────────────────────────────────────────────────
MAX_TOKENS        = 2000
REQUEST_TIMEOUT   = 30
USE_CACHE         = os.environ.get("USE_DECODER_CACHE", "false").lower() == "true"
CACHE_DIR         = Path(".cache/decoder")

# 模型必须从这两个枚举里选
# FOLLOW_CALL_ENUM 现从 analyzer/guards.py 导入（顶部），此处不再定义第二份
CONFIDENCE_ENUM  = {"high", "medium", "low"}

# 只把契约里定义的字段送进模型，杜绝 market_id / event_id 这类内部 ID 干扰
CONTRACT_KEYS = (
    "market_question", "outcome", "entry_price", "current_price",
    "position_value", "pnl_pct", "cash_pnl",
    "resolution_criteria", "resolution_date",
    "entry_time",
    "articles", "time_anchored", "search_query",
)

# ── system prompt 从独立文件读取，杜绝被代码改动悄悄覆盖 ───────────────────────
# 所有 prompt 修改只许动 analyzer/system_prompt.txt，配合 git commit 留痕
SYSTEM_PROMPT_PATH = Path(__file__).parent / "system_prompt.txt"
SYSTEM_PROMPT = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


# ── 自定义异常 ────────────────────────────────────────────────────────────────
class DecoderError(Exception):
    """解码失败时统一抛这个，携带 reason（机器读）和 message（人读）。"""
    def __init__(self, reason: str, message: str):
        self.reason  = reason
        self.message = message
        super().__init__(message)


# ── 函数1（内部）：置信度矩阵 ─────────────────────────────────────────────────
def _compute_confidence(assembled: dict) -> str:
    """
    按 CLAUDE.md 定稿置信度矩阵，优先级从高到低判定 high/medium/low。

    重要：pnl_pct 是百分比数值（0.5813 表示 0.5813%），阈值直接用 30 / 60。
    """
    articles      = assembled.get("articles") or []
    time_anchored = bool(assembled.get("time_anchored", False))
    pnl_pct       = assembled.get("pnl_pct")

    # 规则1：articles 为空 → 低（强制，最高优先级）
    if not articles:
        return "low"

    # 规则2：pnl_pct > 60% → 低（涨幅已被吃透）
    if pnl_pct is not None and pnl_pct > 60:
        return "low"

    # 规则3：浮亏 + 时间未锚定 → 低（articles 为空已被规则1截走）
    if pnl_pct is not None and pnl_pct < 0 and not time_anchored:
        return "low"

    # 规则4：浮亏（封顶在中）
    if pnl_pct is not None and pnl_pct < 0:
        return "medium"

    # 规则5：time_anchored=False（封顶在中）
    if not time_anchored:
        return "medium"

    # 此处已满足：articles 非空 + time_anchored=True + pnl_pct ≥ 0 或 None

    # pnl_pct 缺失时不给"高"，保守降到"中"
    if pnl_pct is None:
        return "medium"

    # 规则6：0 ≤ pnl_pct < 30 → 高
    if pnl_pct < 30:
        return "high"

    # 规则7：30 ≤ pnl_pct < 60 → 中
    if pnl_pct < 60:
        return "medium"

    # > 60 已被规则2截走，理论不可达
    return "low"


# ── 函数2（内部）：代码生成 warnings ───────────────────────────────────────────
def _build_warnings(assembled: dict) -> list[str]:
    """
    降级原因列表，由代码生成，不经过模型。
    三种情况分别对应数据契约里独立的可空字段。
    """
    warnings = []
    if not bool(assembled.get("time_anchored", False)):
        warnings.append(
            "Entry time unknown or beyond lookback window; articles are recent "
            "context, not entry catalysts."
        )
    if assembled.get("entry_price") is None:
        warnings.append("Entry price missing; the wallet's cost basis cannot be compared.")
    if not (assembled.get("articles") or []):
        warnings.append("No relevant news found in the search window; the trade's catalyst is unknown.")
    return warnings


# ── 函数2.5（内部）：预算价差，让模型不必做减法 ───────────────────────────────
def _compute_price_delta(assembled: dict) -> float | None:
    """
    current_price - entry_price，保留 4 位小数（价格本身最多 4 位）。
    entry_price 为 None 时返回 None。
    """
    entry = assembled.get("entry_price")
    curr  = assembled.get("current_price")
    if entry is None or curr is None:
        return None
    return round(curr - entry, 4)


# ── 函数2.52（内部）：跟单者的剩余上行 / 最大损失 ─────────────────────────────
def _compute_follower_max_upside_and_loss(assembled: dict) -> tuple[float | None, float | None]:
    """
    跟单者今天按 current_price 买入时的「剩余上行」与「最大损失」。

    前提（用真实数据验证过，详见 verify_price_side.py）：
      positions API 返回的 current_price 已经是 outcome 那一侧自己的报价
      ——例如持 No 仓位时 curPrice=0.895 就是 No 侧的市场价，
      不是 Yes 侧的 0.105。方向性已经消化在数据里，无需再按 Yes/No 分支。

    所以对任意一侧统一：
      上行 = 1 - current_price   （赢时拿 1 USDC 减去成本）
      损失 = current_price       （输时血本无归）

    current_price 缺失时返回 (None, None)。
    """
    curr = assembled.get("current_price")
    if curr is None:
        return None, None
    return round(1.0 - curr, 4), round(curr, 4)


# ── 函数2.55（内部）：当前日期，给模型作为"现在"的唯一参考点 ─────────────────
def _today_str() -> str:
    """
    模型没有可靠的"现在"概念，由代码注入 today (本地时区, YYYY-MM-DD)。

    用本地时区不是 UTC：用户看到的"今天"是本地日历日，UTC 在傍晚到次日清晨
    之间会与本地日期错位（例如 PDT 18:00 = UTC 次日 01:00，给模型 UTC 日期
    会让卡片显示"明天"），扰乱阅读。
    """
    return datetime.now().strftime("%Y-%m-%d")


# ── 函数2.6（内部）：把 ISO 时间转成人类可读日期，让模型不必推算 ─────────────
def _format_resolution_date_human(iso_str: str | None) -> str | None:
    """
    "2026-12-31T00:00:00Z" → "December 31, 2026"
    解析失败则原样返回（防御性兜底，宁可显示丑也别崩）。
    """
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%B %d, %Y")
    except Exception:
        return iso_str


# ── 函数3（内部）：去掉 markdown 围栏 ─────────────────────────────────────────
def _strip_markdown_fence(text: str) -> str:
    """
    模型偶尔会忽略 system prompt 包一层 ```json ... ```，剥掉它再 json.loads。
    """
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*\n", "", text)
        text = re.sub(r"\n```\s*$", "", text)
    return text.strip()


# ── 函数4（内部）：调课堂网关 ─────────────────────────────────────────────────
def _call_classroom_gateway(system_prompt: str, user_payload: dict) -> str:
    """
    课堂网关只接受单一 input 字段，把 system 和 user data 在 input 里串起来。
    返回 response['output'] 原文。
    """
    combined_input = (
        f"{system_prompt}\n\n"
        f"=== INPUT DATA (the JSON object you must analyze) ===\n\n"
        f"{json.dumps(user_payload, ensure_ascii=False, indent=2)}"
    )

    try:
        output = call_gateway(combined_input, max_tokens=MAX_TOKENS, timeout=REQUEST_TIMEOUT).strip()
    except GatewayError as e:
        reason = {"TIMEOUT": "GATEWAY_TIMEOUT", "UNREACHABLE": "GATEWAY_UNREACHABLE",
                  "RATE_LIMITED": "GATEWAY_RATE_LIMITED"}.get(e.reason, "GATEWAY_HTTP_ERROR")
        raise DecoderError(reason, e.message)
    if not output:
        raise DecoderError("GATEWAY_EMPTY", "解码网关返回空 output")
    return output


# ── 函数5（内部）：缓存 key ───────────────────────────────────────────────────
def _cache_key(user_payload: dict, computed_confidence: str) -> str:
    blob = json.dumps(
        {"payload": user_payload, "conf": computed_confidence},
        sort_keys=True, ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.md5(blob).hexdigest()


# ── 对外唯一入口 ───────────────────────────────────────────────────────────────
def decode_position(assembled: dict, as_of: str | None = None) -> dict:
    """
    输入 assembled dict（CLAUDE.md 数据契约结构），返回解读卡片。

    as_of（可选，"YYYY-MM-DD"）：覆盖注入给模型的「今天」。
      - 正向流程不传 → 用真实当下（_today_str()），行为不变。
      - **回测历史重放必须传快照日（T-7/T-1）**：否则模型拿到真实当下、却看到一个已过去的
        结算日，会算出诡异时长撞 DURATION_COMPUTED 守卫。这是回测重放唯一需要的时间旅行入口。

    成功：{ what_bet, catalyst, edge_analysis, follow_call,
            confidence, reasoning, warnings }
    失败：抛 DecoderError，reason 枚举：
          GATEWAY_TIMEOUT / GATEWAY_UNREACHABLE / GATEWAY_RATE_LIMITED /
          GATEWAY_HTTP_ERROR / GATEWAY_EMPTY / INVALID_JSON /
          INVALID_FOLLOW_CALL / CONFIDENCE_TAMPERED / FABRICATED_CATALYST
    """
    # 第一步：代码先跑置信度矩阵
    computed_confidence = _compute_confidence(assembled)

    # 第二步：只取契约字段，加上代码预算的派生字段一起送进模型
    user_payload = {k: assembled.get(k) for k in CONTRACT_KEYS}
    user_payload["computed_confidence"]   = computed_confidence
    user_payload["price_delta"]           = _compute_price_delta(assembled)
    upside, loss                          = _compute_follower_max_upside_and_loss(assembled)
    user_payload["follower_max_upside"]   = upside
    user_payload["follower_max_loss"]     = loss
    user_payload["resolution_date_human"] = _format_resolution_date_human(
        assembled.get("resolution_date")
    )
    user_payload["today"]                 = as_of or _today_str()

    # 第三步：缓存命中检查（默认关）
    cache_path = None
    if USE_CACHE:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_path = CACHE_DIR / f"{_cache_key(user_payload, computed_confidence)}.json"
        if cache_path.exists():
            try:
                return json.loads(cache_path.read_text(encoding="utf-8"))
            except Exception:
                pass  # 缓存损坏则忽略

    # 第四步：调网关
    raw_output = _call_classroom_gateway(SYSTEM_PROMPT, user_payload)

    # 第五步：剥 markdown 围栏后 json.loads，失败直接抛
    cleaned = _strip_markdown_fence(raw_output)
    try:
        card = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise DecoderError(
            "INVALID_JSON",
            f"模型返回的不是合法 JSON：{e}。原文前 400 字：{raw_output[:400]}",
        )

    # 第六步：代码层守卫（🔴 实现正本在 analyzer/guards.py，decoder 保持 raise 语义：
    # 首个 violation 原样转 DecoderError——reason/message 与抽取前逐字一致）
    duration_fields = []
    for k in ("what_bet", "edge_analysis", "reasoning"):
        if isinstance(card.get(k), str):
            duration_fields.append((k, card[k]))
    for idx, item in enumerate(card.get("catalyst") or []):
        if isinstance(item, dict) and isinstance(item.get("why_relevant"), str):
            duration_fields.append((f"catalyst[{idx}].why_relevant", item["why_relevant"]))

    violations = (
        guards.check_follow_call(card.get("follow_call"))                                   # 6.1
        + guards.check_confidence_tampered(card.get("confidence"), computed_confidence)     # 6.2
        + guards.check_fabricated_catalyst(assembled.get("articles"), card.get("catalyst")) # 6.3
        + guards.check_irrelevant_catalyst(card.get("catalyst"))                            # 6.3b
        + guards.check_duration(duration_fields)                                            # 6.3c
        + guards.check_entry_price_denied(assembled.get("entry_price"),                     # 6.4
                                          card.get("edge_analysis"))
    )
    if violations:
        raise DecoderError(violations[0]["code"], violations[0]["message"])

    # 第七步：代码生成 warnings 拼进最终卡片
    card["warnings"] = _build_warnings(assembled)

    # 第八步：写缓存（开启时）
    if USE_CACHE and cache_path is not None:
        try:
            atomic_write_json(cache_path, card)
        except Exception:
            pass

    return card
