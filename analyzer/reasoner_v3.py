"""
analyzer/reasoner_v3.py — ⑥ Edge / Reasoning（v3 统一看板最后一段，本轮唯一新逻辑）

两部分：
  A. compute_confidence_v3 —— 代码算置信度（v2 底座删 rule5 + R1→R4 只降不升），附「降级原因」列表。
  B. run_reasoner_v3       —— 读 reasoner_v3_prompt.txt + 代码算好的字段，网关出
                              follow_call / confidence(echo) / reasoning（说人话、守三铁律）。

守卫：CONFIDENCE_TAMPERED · INVALID_FOLLOW_CALL · 三铁律扫词(LAW1 评判对错 / LAW3 替用户决定)
      · DURATION_COMPUTED · FABRICATED。

🔴 红线：不改任何封板模块（dual_catalyst / price_reaction / 六道守卫 / decoder v2 矩阵 / fetcher 数据层），
   只读它们的输出。decoder._compute_confidence（v2，/analyze 在用）原封不动，这里是独立 v3 矩阵。
"""
import json
import os
import re
from pathlib import Path

import requests

CONF_ORDER = {"low": 0, "medium": 1, "high": 2}
FOLLOW_ENUM = ["ROOM LEFT", "CHASED", "NO BASIS"]
PROMPT_PATH = Path(__file__).parent / "reasoner_v3_prompt.txt"
GATEWAY_URL = "https://4dm65e698a.execute-api.us-west-2.amazonaws.com/prod/invoke"

# 三铁律扫词（命中即守卫拦截）。"错"单字太宽（不错/没错误伤），用具体短语。
LAW1_VERDICT = ["看走眼", "失误", "错判", "判断对", "判断错", "高明", "明智", "愚蠢", "英明", "正确",
                "wrong", "mistaken", "foolish", "sharp call", "correct call", "smart move"]
LAW3_DIRECTIVE = ["建议跟", "别跟", "不要跟", "值得买", "值得跟", "快上车", "该跟", "该买", "该卖",
                  "推荐跟", "赶紧", "应该跟", "should follow", "don't follow", "do not follow",
                  "worth it", "get in now", "stay out"]
DURATION_RE = re.compile(r"\d+\s*(天|周|个?月|年|days?|weeks?|months?|years?)", re.IGNORECASE)


class ReasonerError(Exception):
    def __init__(self, reason: str, message: str):
        self.reason = reason
        self.message = message
        super().__init__(f"{reason}: {message}")


def _min_conf(a: str, b: str) -> str:
    return a if CONF_ORDER[a] <= CONF_ORDER[b] else b


# ── A. 置信度矩阵 ────────────────────────────────────────────────────────────
def _base_confidence_v3(articles_nonempty: bool, pnl_pct, time_anchored: bool) -> str:
    """v2 矩阵 **删掉 rule5**(time_anchored=False→medium)，其余 7 条不动。pnl_pct 是百分比数值。"""
    if not articles_nonempty:
        return "low"                                            # rule1: 证据为空→低
    if pnl_pct is not None and pnl_pct > 60:
        return "low"                                            # rule2: 涨幅吃透→低
    if pnl_pct is not None and pnl_pct < 0 and not time_anchored:
        return "low"                                            # rule3: 浮亏+未锚→低
    if pnl_pct is not None and pnl_pct < 0:
        return "medium"                                         # rule4: 浮亏→封中
    # rule5(未锚→封中) 已在 v3 删除：实时场景不再因新闻没锚建仓而降级
    if pnl_pct is None:
        return "medium"                                         # 缺失保守→中
    if pnl_pct < 30:
        return "high"                                           # rule6
    if pnl_pct < 60:
        return "medium"                                         # rule7
    return "low"


def compute_confidence_v3(*, support, threat, pnl_pct, time_anchored,
                          by_outcome, held_outcome, recent_action):
    """返回 (confidence, reasons[])。底座→R1→R2→R3→R4 顺序，每条只能维持或降低，绝不升。"""
    reasons = []
    articles_nonempty = bool(support) or bool(threat)
    conf = _base_confidence_v3(articles_nonempty, pnl_pct, time_anchored)
    pnl_show = f"{pnl_pct:+.1f}%" if isinstance(pnl_pct, (int, float)) else "n/a"
    reasons.append(f"底座矩阵:{conf}(pnl={pnl_show})")

    # R1 市场测谎：钱包方向(support 侧)核心催化剂被市场反向定价
    rejected = [c for c in support if c.get("market_reaction") == "rejected"]
    if support and rejected:
        if len(rejected) == len(support):                       # 全面背离
            conf = _min_conf(conf, "low")
            reasons.append("R1:支持侧全部被市场反向定价→打low")
        else:                                                   # 轻微背离
            conf = _min_conf(conf, "medium")
            reasons.append("R1:支持侧部分被市场反向定价→封medium")

    # R2 对冲：主仓 shares < 另一侧×3（均衡=做市/对冲，非单边方向注）
    by = by_outcome or {}
    main = (by.get(held_outcome) or {}).get("shares", 0) or 0
    other = max((v.get("shares", 0) or 0 for k, v in by.items() if k != held_outcome), default=0)
    if other > 0 and main < other * 3:
        conf = _min_conf(conf, "medium")
        reasons.append("R2:两侧均衡(对冲/做市)→封medium")

    # R3 退出信号：近48h结算前大额反向减仓
    if recent_action == "clear_exit":
        conf = _min_conf(conf, "medium")
        reasons.append("R3:近48h大额退出减仓→封medium")

    # R4 证据双空：支持侧与威胁侧都为空
    if not support and not threat:
        conf = _min_conf(conf, "low")
        reasons.append("R4:支持/威胁证据双空→打low")

    # ── 升级模块（预留）─────────────────────────────────────────────────────
    # 现在为空：v3 无任何「升级」路径，矩阵只降不升。
    # TODO(v3+): 当未来验证出确凿「该升」的可信信号（且能解释为何可信）再在此追加。

    return conf, reasons


# ── 字段映射（读封板模块输出，不改它们）──────────────────────────────────────
def _market_reaction(c: dict) -> str:
    """price_reaction.market_check → 中性枚举。印证=confirmed 不一致=rejected 微弱=weak 不可用=unknown。"""
    pr = c.get("price_reaction") or {}
    if not pr.get("available"):
        return "unknown"
    mc = pr.get("market_check", "")
    if "印证" in mc:
        return "confirmed"
    if "不一致" in mc:
        return "rejected"
    if "微弱" in mc:
        return "weak"
    return "unknown"


def _catalysts_for_reasoner(items):
    """裁成 ⑥ 数据契约形：只 title / material_tag / market_reaction（+幅度供前端,不进矩阵）。"""
    out = []
    for c in items or []:
        pr = c.get("price_reaction") or {}
        out.append({
            "title": c.get("title", ""),
            "material_tag": c.get("type", ""),
            "market_reaction": _market_reaction(c),
            "move_pct": pr.get("move_pct") if pr.get("available") else None,
            "same_window": bool(pr.get("same_window")),
        })
    return out


def classify_position_type(two_side: dict, held_outcome: str) -> str:
    by = (two_side or {}).get("by_outcome") or {}
    if not (two_side or {}).get("hedged"):
        return "single_side_conviction"
    held = (by.get(held_outcome) or {}).get("shares", 0) or 0
    other = max((v.get("shares", 0) or 0 for k, v in by.items() if k != held_outcome), default=0)
    if held and other and min(held, other) / max(held, other) >= 0.5:
        return "market_making"            # 两边接近 = 做市
    return "hedged"


def classify_recent_action(flag: dict) -> str:
    """behavioral_flag(ADD/EXIT/STATIC) → reasoner 契约枚举。"""
    if not flag:
        return "flat_no_movement"
    f = flag.get("flag")
    if f == "ADD":
        return "adding"
    if f == "EXIT":
        return "clear_exit"               # 大额反向减仓 → 进 R3
    return "flat_no_movement"


def build_facts(briefing: dict, behavioral_flag: dict, today: str) -> dict:
    """把已封板模块的输出（/briefing 响应 + behavioral_flag）拼成 ⑥ 的数据契约 + 代码算好的矩阵结论。"""
    m = briefing.get("meta", {})
    wp = briefing.get("what_position_actions", {}) or {}
    actions = wp.get("actions", {}) or {}
    two_side = wp.get("two_side_distribution", {}) or {}
    un = wp.get("unrealized", {}) or {}
    pc = briefing.get("price_context", {}) or {}
    cats = briefing.get("catalysts", {}) or {}

    held = m.get("analyzed_side", "Yes")
    support = _catalysts_for_reasoner(cats.get("positive", []))
    threat = _catalysts_for_reasoner(cats.get("negative", []))
    pnl_pct = un.get("unrealized_pct")
    time_anchored = bool(actions.get("entry_time"))
    recent_action = classify_recent_action(behavioral_flag)

    confidence, reasons = compute_confidence_v3(
        support=support, threat=threat, pnl_pct=pnl_pct, time_anchored=time_anchored,
        by_outcome=two_side.get("by_outcome"), held_outcome=held, recent_action=recent_action)

    return {
        "market_question": m.get("market"),
        "outcome": held,
        "today": today,
        "price_room_left": pc.get("remaining_upside_pct_if_win"),
        "price_already_moved": pc.get("price_delta_pct"),
        "resolution_date_human": m.get("settle"),
        "position_type": classify_position_type(two_side, held),
        "recent_action": recent_action,
        "support_catalysts": support,
        "threat_catalysts": threat,
        "confidence": confidence,
        "confidence_reasons": reasons,
    }


# ── B. reasoner 网关调用 + 守卫 ──────────────────────────────────────────────
def _strip_fence(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n?", "", t)
        t = re.sub(r"\n?```$", "", t).strip()
    return t


def _gateway(prompt: str, facts: dict, max_tokens: int = 900) -> str:
    key = os.environ.get("CLASSROOM_API_KEY")
    if not key:
        raise ReasonerError("NO_API_KEY", "CLASSROOM_API_KEY 未配置")
    full = prompt + "\n\n=== THE JSON OBJECT (your entire universe of facts) ===\n" + \
        json.dumps(facts, ensure_ascii=False)
    resp = requests.post(GATEWAY_URL,
                         headers={"Content-Type": "application/json", "x-api-key": key},
                         json={"model": "claude-sonnet-4.5", "input": full, "maxTokens": max_tokens},
                         timeout=30)
    if resp.status_code != 200:
        raise ReasonerError("GATEWAY_ERROR", f"网关 {resp.status_code}: {resp.text[:160]}")
    return resp.json()["output"]


def _scan_iron_laws(reasoning: str):
    for w in LAW1_VERDICT:
        if w in reasoning:
            raise ReasonerError("LAW1_VERDICT", f"reasoning 出现评判对错词「{w}」")
    for w in LAW3_DIRECTIVE:
        if w in reasoning:
            raise ReasonerError("LAW3_DIRECTIVE", f"reasoning 出现替用户决定词「{w}」")
    if DURATION_RE.search(reasoning):
        raise ReasonerError("DURATION_COMPUTED", "reasoning 出现时长推算（禁止日期/时长数学）")


def run_reasoner_v3(facts: dict) -> dict:
    """读 prompt + facts → 网关 → 解析 + 五道守卫。返回 {follow_call, confidence, reasoning, confidence_reasons}。"""
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    raw = _strip_fence(_gateway(prompt, facts))
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        raise ReasonerError("BAD_JSON", f"模型未返回合法 JSON: {raw[:160]}")

    fc = str(obj.get("follow_call", "")).strip().upper()
    fc_norm = next((e for e in FOLLOW_ENUM if fc.startswith(e)), None)
    if not fc_norm:
        raise ReasonerError("INVALID_FOLLOW_CALL", f"非法 follow_call: {obj.get('follow_call')!r}")

    conf_out = str(obj.get("confidence", "")).strip().lower()
    if conf_out != facts["confidence"]:                         # CONFIDENCE_TAMPERED 守卫
        raise ReasonerError("CONFIDENCE_TAMPERED",
                            f"AI 篡改置信度 {facts['confidence']}→{conf_out}（代码算定,不准改）")

    reasoning = str(obj.get("reasoning", "")).strip()
    _scan_iron_laws(reasoning)                                  # 三铁律 + 时长守卫

    return {"follow_call": fc_norm, "confidence": conf_out,
            "reasoning": reasoning, "confidence_reasons": facts["confidence_reasons"]}


def reason_v3(briefing: dict, behavioral_flag: dict, today: str) -> dict:
    """⑥ 顶层：briefing(已封板输出) + behavioral_flag → facts(含矩阵) → reasoner。"""
    facts = build_facts(briefing, behavioral_flag, today)
    out = run_reasoner_v3(facts)
    out["facts"] = facts                                        # 透传给前端/调试（含降级原因）
    return out
