"""
fetcher/theme_markets.py — 主题盘（2026-10-30）

首页趋势全换成两条主题线：
  ① 美国 2026 中期选举（11/3 投票）：Gamma `tag_slug=midterms` 事件按 24h 成交量 → 横幅赔率卡
     + 扫榜发现入口（成交量最大的选举子盘 cid → get_market_holders 找大户）
  ② Tech & Immigration：用户想要 H-1B / F-1 / OPT 话题，但实测（2026-10-30）Polymarket 上**没有
     直接以它们为题、有成交量的盘** → 关键词搜最接近的移民/科技盘，并在 note 里如实说明，不编造。

全部免 key 公开接口；进程内 10 分钟 TTL 缓存（首页每次加载都会打，不能每次穿透上游）。
上游任何失败 → 返回空 markets，端点照常 200（主题卡是锦上添花，不许拖垮首页）。
"""
import json
import re
import time

from fetcher import pm_backend

GAMMA = pm_backend.GAMMA
DATA = pm_backend.DATA
ELECTION_DATE = "2026-11-03"
TTL_SECONDS = 600
# 移民组优先（用户要 H-1B/F-1/OPT 话题），科技组补位；关键词按"标题整词"判相关，防 Deportivo 这类误匹配
TECH_IMMIGRATION_GROUPS = (
    ("immigration", ("h-1b", "h1b", "f-1 visa", "opt program", "student visa", "visa", "gold card",
                     "immigration", "deport", "green card")),
    ("tech", ("tech layoffs", "best ai model", "largest company")),
)
NEAR_SETTLED = 0.97          # 头号选项 ≥97¢ = 已无悬念，不上卡
TECH_NOTE = ("No live Polymarket market is titled H-1B, F-1 or OPT yet; these are the closest "
             "live immigration and tech markets, ranked by 24h volume.")

_get = pm_backend._get        # 测试缝
_cache = {}

_ELECTION_RE = re.compile(
    r"\b(midterms?|senate|governor|gubernatorial|election|elected|primary|nominee|electoral|"
    r"balance of power|congress(ional)?|house (seat|race|majority|control)|control the house|"
    r"win the house|(the )?house in 20\d\d|ballot|runoff)\b", re.I)


def is_election_question(q):
    return bool(q) and bool(_ELECTION_RE.search(str(q)))


def _cached(key, fn):
    hit = _cache.get(key)
    now = time.time()
    if hit and now - hit[0] < TTL_SECONDS:
        return hit[1]
    val = fn()
    _cache[key] = (now, val)
    return val


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _yes_price(m):
    try:
        prices = json.loads(m.get("outcomePrices") or "null")
    except (TypeError, ValueError):
        return None
    return _f(prices[0]) if isinstance(prices, list) and prices else None


def _live(m):
    return isinstance(m, dict) and m.get("active") and not m.get("closed") and _yes_price(m) is not None


def _outcomes(ev):
    live = [m for m in ev.get("markets") or [] if _live(m)]
    if len(live) == 1:
        y = _yes_price(live[0])
        return [{"name": "Yes", "price": round(y, 4)}, {"name": "No", "price": round(1 - y, 4)}]
    rows = [{"name": m.get("groupItemTitle") or m.get("question"), "price": round(_yes_price(m), 4)} for m in live]
    return sorted(rows, key=lambda r: -r["price"])[:4]


def _events():
    return _cached("midterm_events", lambda: _get(f"{GAMMA}/events", {
        "tag_slug": "midterms", "active": "true", "closed": "false",
        "order": "volume24hr", "ascending": "false", "limit": 12}) or [])


def election_pulse(limit=6):
    try:
        evs = _events()
    except Exception:
        evs = []
    cards = []
    for ev in evs:
        outs = _outcomes(ev)
        if not outs:
            continue
        cards.append({"title": ev.get("title"), "slug": ev.get("slug"),
                      "url": f"https://polymarket.com/event/{ev.get('slug')}",
                      "volume24hr": _f(ev.get("volume24hr")), "outcomes": outs})
        if len(cards) >= limit:
            break
    return {"as_of": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "election_date": ELECTION_DATE, "markets": cards}


def election_condition_ids(limit=8):
    """扫榜发现入口：选举事件里成交量最大的活子盘 → [(cid, question)]。"""
    try:
        evs = _events()
    except Exception:
        return []
    subs = [m for ev in evs for m in ev.get("markets") or [] if _live(m) and (_f(m.get("volumeNum")) or 0) > 0]
    subs.sort(key=lambda m: -(_f(m.get("volumeNum")) or 0))
    seen, out = set(), []
    for m in subs:
        cid = m.get("conditionId")
        if cid and cid not in seen:
            seen.add(cid)
            out.append((cid, m.get("question")))
        if len(out) >= limit:
            break
    return out


def _top_holder(cid):
    try:
        toks = (_get(f"{DATA}/v2/holders", {"condition": cid, "limit": 5}) or {}).get("data") or []
        hs = sorted((h for t in toks for h in t.get("holders") or []), key=lambda h: -(_f(h.get("amount")) or 0))
    except Exception:
        return None
    if not hs:
        return None
    h = hs[0]
    return {"wallet": h.get("proxy_wallet"), "name": h.get("name") or h.get("pseudonym"),
            "amount": _f(h.get("amount"))}


def _title_matches(title, kw):
    """关键词整词出现在标题里（多词按词序，末词可复数）；deport 允许 deport/deported/deportation(s)。"""
    words = [re.escape(w) for w in kw.split()]
    if words and words[-1] == "deport":
        words[-1] = r"deport(?:s|ed|ing|ations?)?"
    elif words:
        words[-1] += r"(?:s|es)?"                     # Gold Cards / visas / layoffs
    return bool(re.search(r"\b" + r"\s+".join(words) + r"\b", str(title or ""), re.I))


def _search_events(keywords, seen):
    evs = []
    for kw in keywords:
        try:
            r = _get(f"{GAMMA}/public-search", {"q": kw, "events_status": "active", "limit_per_type": 8}) or {}
        except Exception:
            continue
        for ev in r.get("events") or []:
            slug = ev.get("slug")
            if slug in seen or ev.get("closed") or not ev.get("active") or not _title_matches(ev.get("title"), kw):
                continue
            seen.add(slug)
            evs.append(ev)
    return sorted(evs, key=lambda e: -(_f(e.get("volume24hr")) or 0))


def tech_immigration(groups=TECH_IMMIGRATION_GROUPS, limit=6):
    def build():
        cards, seen = [], set()
        for group, keywords in groups:
            for ev in _search_events(keywords, seen):
                live = [m for m in ev.get("markets") or [] if _live(m)]
                if not live:
                    continue
                top = max(live, key=lambda m: _yes_price(m) or 0)
                if (_yes_price(top) or 0) >= NEAR_SETTLED:
                    continue
                cards.append({"group": group, "title": ev.get("title"),
                              "url": f"https://polymarket.com/event/{ev.get('slug')}",
                              "volume24hr": _f(ev.get("volume24hr")),
                              "top_outcome": {"name": top.get("groupItemTitle") or "Yes",
                                              "price": round(_yes_price(top), 4)},
                              "top_holder": _top_holder(top.get("conditionId"))})
                if len(cards) >= limit:
                    return cards
        return cards
    try:
        cards = _cached(("tech", repr(groups)), build)
    except Exception:
        cards = []
    return {"as_of": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "note": TECH_NOTE, "markets": cards}
