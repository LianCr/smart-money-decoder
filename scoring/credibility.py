"""
scoring/credibility.py — F4 可信度分：这个盘的价格值不值得信（纯代码零 LLM）

上游 575 Market Insights / 568 K线 早就按盘算好了硬指标（流动性/集中度/参与度/
量能/波动），但此前只被拼成文本喂 prompt、算完就扔。本模块把它们合成一个
**确定性可信度分**（deterministic: true）：扣分制 0-100 + A-F 档，每个子指标带
机器可读的 delta 审计尾迹——同输入永远同输出，能独立于 LLM 的非确定性存在。

🔴 红线（任何改动不许越）：
  1. **可信度评价信号、永不修理判断**——本模块不读不写任何 AI 判断字段
     （入参 dict 出现判断 key 直接 raise；源码级零访问由测试钉死）。
     它回答"这个盘的价格质量如何"，不回答也不影响"该信 YES 还是 NO"。
  2. **零 IO 零网络零业务 import**：输入全靠调用方注入的纯 dict（来自已缓存的
     575/568 结构化数据），本模块只做算术——放哪都能跑、怎么跑都一样。
  3. **只扣不加**：起点 100，各子指标按扣分表减、每项设上限防重复计罪，floor 0。
  4. **缺数据诚实**：575 整体缺 → score/tier 双 null（绝不装 100 也不装 0）；
     单子指标缺 → verdict="missing"、不扣分、payload 标 partial=true。
  5. self_check（guard 触发 × 历史命中率交叉）目前 **info-only 不计分**——
     样本 < 阈值时给它计分资格就是拿噪声当信号；升为计分项须另场评审。

阈值注：扣分表是首版标定（对三份真实政治盘缓存样本 sanity：100/A、85/B、75/B，
旧二元 trust 逻辑对同样三盘全给 HIGH）。犹豫度带沿用上游既有阈值。
T2.2 已兑现迁入 scoring/：扣分表正本在 scoring/constants.py。
"""

# ── 扣分表：T2.2 起唯一正本在 scoring/constants.py（与上游 575/568 采集层共用的门在那里合并）──
from scoring.constants import (
    LIQ_PCT_LOW, LIQ_PCT_MID, LIQ_D_LOW, LIQ_D_MID, LIQ_D_FLAG, LIQ_CAP,
    CONC_TOP1, CONC_TOP10, CONC_D_TOP1, CONC_D_TOP10, CONC_D_WHALE, CONC_D_TRADE,
    CONC_D_SQUEEZE, CONC_CAP, PART_LOW, PART_MID, PART_D_LOW, PART_D_MID,
    VOLU_D_COLLAPSE, VOLU_D_DECLINE, VOLA_HIGH, VOLA_MID, VOLA_D_HIGH, VOLA_D_MID,
    AGE_YOUNG_DAYS, AGE_D_YOUNG, TIERS, BAD_DELTA,
)

_FORBIDDEN = ("market_lean", "confidence", "rationale")   # 判断字段，进不了本模块


def _firewall(*dicts):
    """入参防火墙：判断字段一露头就 raise——防手滑把上游整包判断塞进来。"""
    for d in dicts:
        if isinstance(d, dict):
            for k in _FORBIDDEN:
                if k in d:
                    raise ValueError(f"判断字段 {k} 不得进入可信度计算——可信度评价信号，不修理判断")


def _ff(x):
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def _verdict(delta, missing=False):
    if missing:
        return "missing"
    if delta == 0:
        return "ok"
    return "bad" if delta <= BAD_DELTA else "warn"


def _sub(key, delta, raw, missing=False, info=False):
    return {"key": key, "verdict": "info" if info else _verdict(delta, missing),
            "delta": delta, "raw": raw}


def build_credibility(price_raw, vol, guard_flags=None, guard_cross=None,
                      days_to_resolution=None) -> dict:
    """硬指标 → 可信度分。price_raw=575 结构化数据（缺=None）、vol=近 14 日已实现
    日波动（缺=None）、guard_flags=本次构建触发的守卫、guard_cross=回验档案的
    guard×命中率交叉（样本不足如实标注）。返回 payload 契约 dict（见测试）。"""
    _firewall(price_raw, guard_cross)
    flags = list((price_raw or {}).get("flags") or [])
    subs = []

    if price_raw is None:
        for k in ("liquidity", "concentration", "participants", "volume", "volatility", "age"):
            subs.append(_sub(k, 0, None, missing=True))
    else:
        # 流动性：盘越深，价格越难被单笔砸出假信号
        pct = _ff(price_raw.get("liquidity_percentile"))
        if pct is None:
            subs.append(_sub("liquidity", 0, None, missing=True))
        else:
            d = LIQ_D_LOW if pct < LIQ_PCT_LOW else (LIQ_D_MID if pct < LIQ_PCT_MID else 0)
            if "liquidity_risk_flag" in flags:
                d += LIQ_D_FLAG
            d = max(d, LIQ_CAP)
            subs.append(_sub("liquidity", d, {"pct": pct, "tier": price_raw.get("liquidity_tier")}))

        # 集中度：头部越重，价格越像少数人的意见而非市场共识
        top1, top10 = _ff(price_raw.get("top1_wallet_pct")), _ff(price_raw.get("top10_wallet_pct"))
        if top1 is None and top10 is None:
            subs.append(_sub("concentration", 0, None, missing=True))
        else:
            d = 0
            if top1 is not None and top1 >= CONC_TOP1:
                d += CONC_D_TOP1
            if top10 is not None and top10 >= CONC_TOP10:
                d += CONC_D_TOP10
            if "whale_control_flag" in flags:
                d += CONC_D_WHALE
            if "trade_concentration_flag" in flags:
                d += CONC_D_TRADE
            if "squeeze_risk_flag" in flags:
                d += CONC_D_SQUEEZE
            d = max(d, CONC_CAP)
            subs.append(_sub("concentration", d, {"top1": top1, "top10": top10}))

        # 参与：人少的盘，价格是几个人的赌局不是人群的判断
        uniq = price_raw.get("unique_traders_7d")
        if uniq is None:
            subs.append(_sub("participants", 0, None, missing=True))
        else:
            d = PART_D_LOW if uniq < PART_LOW else (PART_D_MID if uniq < PART_MID else 0)
            subs.append(_sub("participants", d, {"uniq": uniq}))

        # 量能：没人交易的价格是"上次成交的遗迹"，不是现在的共识
        trend = price_raw.get("volume_trend")
        collapse = "volume_collapse_risk_flag" in flags
        if trend is None and not collapse:
            subs.append(_sub("volume", 0, None, missing=True))
        else:
            d = (VOLU_D_COLLAPSE if collapse else 0) + (VOLU_D_DECLINE if trend == "Significant Decline" else 0)
            subs.append(_sub("volume", d, {"trend": trend, "collapse": collapse}))

        # 犹豫度：市场自己都没拿定主意，当下价位就不值得当锚
        v = _ff(vol)
        if v is None:
            subs.append(_sub("volatility", 0, None, missing=True))
        else:
            d = VOLA_D_HIGH if v >= VOLA_HIGH else (VOLA_D_MID if v >= VOLA_MID else 0)
            subs.append(_sub("volatility", d, {"vol": round(v, 4)}))

        # 年龄（T1，575 created_at）：新盘价格发现未完成，价位还没被人群消化
        age = _ff(price_raw.get("market_age_days"))
        if age is None:
            subs.append(_sub("age", 0, None, missing=True))    # 旧缓存 thesis 无此字段 → 如实缺
        else:
            subs.append(_sub("age", AGE_D_YOUNG if age < AGE_YOUNG_DAYS else 0, {"age_days": age}))

    # 判断层自检（info-only 不计分，红线 5）：本次触发了几道守卫 + 历史上
    # 触发守卫的判断命中率是否更差——样本不足就如实说不足，绝不硬给百分比
    gc = guard_cross or {}
    fl, cl = gc.get("flagged") or {}, gc.get("clean") or {}
    insufficient = bool(fl.get("insufficient", True) or cl.get("insufficient", True))
    subs.append(_sub("self_check", 0, {
        "guard_flags_n": len(guard_flags or []),
        "flagged": fl.get("hit_rate_pct"), "clean": cl.get("hit_rate_pct"),
        "insufficient": insufficient,
    }, info=True))

    scored = [s for s in subs if s["key"] != "self_check"]
    if price_raw is None:
        score = tier = None
        partial = True
    else:
        score = max(0, 100 + sum(s["delta"] for s in scored))
        tier = next((t for floor, t in TIERS if score >= floor), "F")
        partial = any(s["verdict"] == "missing" for s in scored)

    return {
        "deterministic": True,
        "score": score, "tier": tier, "partial": partial,
        "subs": subs,
        "risk_flags": flags,
        "days_to_resolution": days_to_resolution,
    }
