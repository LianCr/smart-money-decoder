"""
fetcher/social.py — 585 Social Pulse（社媒情绪动量）

🔴 这是"情绪"不是"事实"：群众怎么议论，可能被刷量操纵。和新闻(事实)并排时，前端务必视觉上分开。
🔴 仅实时：acceleration/pct_last_1h 都相对"现在"算，无法重构历史 as-of 动量（进不了回测，已验）。
纯数据、免费（同其它 Heisenberg 端点），不调 LLM——给原始指标+原帖，不替用户解读情绪。

口径：关键词(花括号,逗号分隔无空格) + hours_back(字符串) → 585 →
  聚合 acceleration / author_diversity_pct(<20%=疑似刷量噪音) / tweet_count + 高互动有机帖。
"""
from fetcher.heisenberg import AGENTS, call, results

ORGANIC_MIN = 20.0          # author_diversity_pct ≥ 20% 视为有机，否则疑似刷量（文档定义）
# 🔴 通用词会让 585 的 OR 匹配跑偏（"deal/final" 匹配到足球转会"here we go"高互动帖）→ 从关键词里剔除
SOCIAL_STOP = {"final", "deal", "deals", "agreement", "pact", "accord", "treaty", "talks", "talk",
               "win", "wins", "control", "ban", "next", "new", "plan", "vote", "poll", "race",
               "bid", "by", "the", "of", "in", "on", "out", "transit", "fees", "rights"}


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def social_pulse(keywords, hours_back="168", max_posts=4):
    """keywords: list[str]。返回 dict 或 None（拉不到/无数据时诚实 None，前端留空）。"""
    kws = [str(k).strip() for k in (keywords or []) if str(k).strip() and str(k).strip().lower() not in SOCIAL_STOP][:4]
    if not kws:
        return None
    kw = "{" + ",".join(kws) + "}"
    try:
        rs = results(call(AGENTS["social"][0], {"keywords": kw, "hours_back": str(hours_back)}))
    except Exception:
        return None
    if not rs:
        return None
    agg = rs[0]                                   # 聚合指标附在每条上，取第一条即可
    div = _f(agg.get("author_diversity_pct"))
    # 相关性过滤：帖子内容须含 ≥1 关键词（再杀一层 OR 误匹配的噪音）；全滤光则退回原始
    kl = [k.lower() for k in kws]
    pool = [p for p in rs if any(k in (p.get("content") or "").lower() for k in kl)] or rs
    seen, posts = set(), []
    for p in sorted(pool, key=lambda x: -((_f(x.get("like_count")) or 0) + (_f(x.get("retweet_count")) or 0))):
        u, c = p.get("username"), (p.get("content") or "").strip()
        if not c or u in seen:
            continue
        seen.add(u)
        posts.append({"username": u, "content": c[:220], "url": p.get("url"),
                      "likes": _f(p.get("like_count")), "retweets": _f(p.get("retweet_count")),
                      "created_on": p.get("created_on")})
        if len(posts) >= max_posts:
            break
    return {
        "keywords": kw,
        "acceleration": _f(agg.get("acceleration")),       # >1 升温 / <1 降温
        "author_diversity_pct": div,                        # <20% 疑似刷量
        "tweet_count": int(_f(agg.get("tweet_count")) or 0),
        "organic": (div is not None and div >= ORGANIC_MIN),
        "posts": posts,
        "note": "社媒=情绪非事实，可能被刷量；author_diversity<20% 当噪音看。仅实时，不进回测。",
    }
