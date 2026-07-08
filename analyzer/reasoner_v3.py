"""
analyzer/reasoner_v3.py — ⑥ Edge / Reasoning 的代码层：纯代码矩阵 + facts 契约（零网关调用）

  compute_confidence_v3 —— 代码算置信度（v2 底座删 rule5 + R1→R4 只降不升），附「降级原因」列表。
  build_facts           —— 把封板模块输出拼成 ⑥ 的数据契约（价格/时长/对冲/催化剂 + 矩阵结论）。

（旧 B 段 run_reasoner_v3/reason_v3 网关 prose 已在瘦身后移除：follow_call 改由
 api 层代码判定、信心由 market_thesis 直出，本模块只剩纯代码、零 token。）

🔴 红线：不改任何封板模块（dual_catalyst / price_reaction / 六道守卫 / decoder v2 矩阵 / fetcher 数据层），
   只读它们的输出。decoder._compute_confidence（v2，/analyze 在用）原封不动，这里是独立 v3 矩阵。
"""
CONF_ORDER = {"low": 0, "medium": 1, "high": 2}


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
