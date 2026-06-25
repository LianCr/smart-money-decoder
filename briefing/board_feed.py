"""
briefing/board_feed.py — 统一看板 ⑤区(综述+时间线新闻流) + ②区(what the bet) 的组合层。

🔴 纯组合：只**读**已封板模块的输出，一行不改它们——
   GDELT 催化剂 = market_context 的 timeline_events（缓存命中零 token）
   Tavily 催化剂 = briefing 的 catalysts（已在 briefing 缓存）
   gamma context + resolution = 免费 gamma API
   市场反应符号 = 复用 price_reaction.compute_reaction（前一日close→次日close，不改它）
不碰 dual_catalyst / price_reaction / 六道守卫 / 数据层逻辑。
"""
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

from analyzer.price_reaction import compute_reaction
from briefing.market_context import _gateway, DIRECTIVE_WORDS, FEAR_WORDS
from fetcher.heisenberg import call as hz_call, results as hz_results, AGENTS as HZ_AGENTS

GAMMA = "https://gamma-api.polymarket.com"
REACT_THRESHOLD = 5.0           # 与 price_reaction.MEANINGFUL_MOVE_PCT 同口径


# ── 持有侧 token（市场反应符号统一以"钱包押的那一侧"价格涨跌为准）──────────────
def held_token(cid: str, outcome: str):
    m = (hz_results(hz_call(HZ_AGENTS["markets"][0], {"condition_id": cid})) or
         hz_results(hz_call(HZ_AGENTS["markets"][0], {"condition_id": cid, "closed": "True"})))
    if not m:
        return None
    m = m[0]
    return (m["side_a_token_id"] if str(m.get("side_a_outcome")).lower() == outcome.lower()
            else m["side_b_token_id"])


# ── 持有侧 token 日线序列（≤ as_of，568，免费，供上帝视角时间轴）────────────────
def price_series(token: str, as_of: str, days: int = 60):
    if not token:
        return []
    end = int(datetime.strptime(as_of, "%Y-%m-%d").replace(tzinfo=timezone.utc, hour=23, minute=59).timestamp())
    start = end - days * 86400
    try:
        rs = hz_results(hz_call(HZ_AGENTS["candles"][0], {"token_id": token, "interval": "1d",
                       "start_time": str(start), "end_time": str(end)}))
    except Exception:
        return []
    out = []
    for r in sorted(rs, key=lambda r: str(r.get("candle_time", ""))):
        d = str(r.get("candle_time", ""))[:10]
        try:
            c = float(r.get("close"))
        except (TypeError, ValueError):
            continue
        if d and d <= as_of:                       # 🔴 防泄漏：绝不取 as_of 之后
            out.append({"date": d, "price": round(c, 4)})
    return out


# ── 免费 gamma：resolution_criteria(②) + context_description(⑤综述第三源)──────
def gamma_meta(slug: str):
    resolution, context = None, None
    if not slug:
        return resolution, context
    try:
        r = requests.get(f"{GAMMA}/markets", params={"slug": slug}, timeout=12).json()
        mk = r[0] if isinstance(r, list) and r else (r if isinstance(r, dict) else None)
        if mk:
            resolution = (mk.get("description") or "").strip() or None
            evs = mk.get("events") or []
            if evs and evs[0].get("id"):
                er = requests.get(f"{GAMMA}/events", params={"id": evs[0]["id"]}, timeout=12).json()
                ev = er[0] if isinstance(er, list) and er else er
                em = (ev or {}).get("eventMetadata") or {}
                context = (em.get("context_description") or "").strip() or None
    except Exception:
        pass                         # gamma 挂 → 退化成两源，不阻塞
    return resolution, context


# ── 统一市场反应符号（方向无关：持有侧涨=印证 / 跌=不买账；复用 compute_reaction）──
def _reaction(tok, date, as_of):
    if not tok or not date:
        return {"available": False}
    r = compute_reaction(tok, date, as_of=as_of)
    if not r.get("available"):
        return {"available": False}
    mv = r["move_pct"]
    kind = "weak" if abs(mv) < REACT_THRESHOLD else ("confirm" if mv > 0 else "reject")
    return {"available": True, "kind": kind, "move_pct": mv, "window": r.get("window")}


def _domain(url):
    try:
        return urlparse(url).netloc.replace("www.", "") or None
    except Exception:
        return None


def _norm(url, title):
    u = re.sub(r"[?#].*$", "", str(url or "")).strip().lower().rstrip("/")
    return u or str(title or "").strip().lower()


# ── 三源合并新闻流（GDELT + Tavily，按时间倒序，每条带 source 链接 + 反应符号）──
def build_news_stream(gdelt_events, tavily_cats, tok, as_of):
    items, seen = [], set()
    for e in gdelt_events or []:                    # GDELT（market_context timeline catalyst）
        if e.get("type") != "catalyst":
            continue
        k = _norm(e.get("url"), e.get("title"))
        if k in seen:
            continue
        seen.add(k)
        url = (e.get("url") or "").strip()
        src = e.get("source")
        # GDELT 不经 dual_catalyst 分类 → 方向标为 None（诚实：不杜撰支持/威胁）
        items.append({"date": e.get("timestamp"), "title": e.get("title"),
                      "summary": e.get("fact_summary"),
                      "url": url or (f"https://{src}" if src else ""),   # 老缓存无 url → 退化到来源域名
                      "origin": "GDELT", "direction": None})
    # Tavily（briefing catalysts）：方向标直接取 dual_catalyst 已分好的正负
    for side, direction in (("positive", "support"), ("negative", "threat")):
        for c in (tavily_cats.get(side) or []):
            k = _norm(c.get("url"), c.get("title"))
            if k in seen:
                continue
            seen.add(k)
            items.append({"date": c.get("date"), "title": c.get("title"),
                          "summary": c.get("reason"), "url": (c.get("url") or "").strip(),
                          "origin": "Tavily", "direction": direction})
    daycount = {}
    for it in items:
        if it["date"]:
            daycount[it["date"]] = daycount.get(it["date"], 0) + 1
    for it in items:
        it["reaction"] = _reaction(tok, it["date"], as_of)
        it["same_window"] = bool(it["date"] and daycount.get(it["date"], 0) > 1)
    items.sort(key=lambda x: x.get("date") or "", reverse=True)
    return items


def _guard_directive(text):
    bad = [w for w in DIRECTIVE_WORDS + FEAR_WORDS if w in (text or "")]
    return text if not bad else None


# ── ⑤ 综述：三源合并（巨鲸动态 + GDELT + Tavily + gamma 叙事），守诚实 ─────────────
def merged_summary(market_q, outcome, behavior, gdelt_facts, tavily_facts, gamma_context):
    src = []
    if behavior:
        src.append(f"【巨鲸动态】{behavior['fact']}")
    if gdelt_facts:
        src.append("【价格异动相关事件·GDELT】" + "；".join(gdelt_facts))
    if tavily_facts:
        src.append("【新闻检索·Tavily】" + "；".join(tavily_facts))
    if gamma_context:
        src.append("【Polymarket 盘面叙事·gamma】" + gamma_context[:600])
    if not src:
        return None
    prompt = (
        f"市场「{market_q}」，分析侧 {outcome}。下面是三源合并的客观素材。\n"
        "写一段 ≤170 字**简体中文**冷静客观综述，保留「巨鲸动态 / 事态进展」结构：先点巨鲸动作，再整合三源最新事态。\n"
        "🔴 只陈列事实，**绝不给投资判断或倾向**（禁该跟/别跟/胜率/值得/edge/跟单价值等词），不夸大不恐吓，"
        "不说『导致』（同窗多条只时间相关）。\n素材：\n" + "\n".join(src)
    )
    out = _gateway(prompt, 360).strip()
    return _guard_directive(out) or "（综述含导向/恐吓词被守卫拦下，待修）"


# ── ② What the bet is：一句话讲清这一注（grounded 在官方结算规则，防幻觉）──────
def what_the_bet(market_q, outcome, resolution_criteria):
    rc = (resolution_criteria or "").strip()
    prompt = (
        f"预测市场问题：「{market_q}」。这个钱包押的是 **{outcome}**。\n"
        f"市场官方结算规则原文：「{rc[:600] or '(未提供)'}」\n"
        "用**简体中文**写**一句话**讲清这一注在赌什么：押什么 + 什么算赢。"
        "🔴 只能依据上面的问题与结算规则，**不得编造规则里没有的条件**，不给任何投资判断。"
    )
    return _gateway(prompt, 200).strip()
