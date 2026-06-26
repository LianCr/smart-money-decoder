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
# 🔴 地理/通用名词：是"语境"不是"主体"，单独命中不算相关（"South Korea"里的 south/korea 会把 KOSPI/影响者新闻拉进来）。
# 相关性门优先用**非地理的特异主体词**(如人名)，地理词只在没有更特异词时才用。
GEO_COMMON = {"south", "north", "east", "west", "korea", "korean", "china", "chinese", "japan", "japanese",
              "russia", "russian", "iran", "iranian", "israel", "israeli", "ukraine", "ukrainian",
              "america", "american", "united", "states", "kingdom", "britain", "british", "europe", "european",
              "france", "french", "germany", "german", "india", "indian", "usa", "president", "presidential",
              "election", "elections", "government", "minister", "senate", "congress", "house", "court",
              "party", "country", "city", "state", "nation", "national"}
GENERIC_HIT_FRAC = 0.35     # 在返回帖里命中率 > 35% 的关键词 = OR 拉进来的泛词，剔出相关性门


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
    # 🔴 相关性门（修复"Lee Jae-myung 盘混进 Tom Lee/KOSPI/足球"bug）：
    # OR 查询会把只命中泛词(lee/south/korea)的无关帖拉进来。按"命中率"挑**特异**关键词：
    # 剔掉在返回帖里命中 >35% 的泛词 + 优先非地理主体词；用特异词做门。**特异词全无命中 → 该主题无社媒覆盖 → 诚实返 None，绝不拿泛匹配凑数。**
    kl = [k.lower() for k in kws]
    n = max(len(rs), 1)
    freq = {k: sum(1 for p in rs if k in (p.get("content") or "").lower()) / n for k in kl}
    # 主体词 = 非地理的特异词(命中率≤35%)；没有则退回非地理任意词；再没有退回最稀有的
    subject = ([k for k in kl if freq[k] <= GENERIC_HIT_FRAC and k not in GEO_COMMON]
               or [k for k in kl if k not in GEO_COMMON] or [min(kl, key=lambda k: freq[k])])

    def _relevant(content):
        c = (content or "").lower()
        matched = [k for k in kl if k in c]
        if not any(k in subject for k in matched):           # 必须命中主体词（剔只命中地理/泛词的噪音）
            return False
        distinctive = any(("-" in k or len(k) >= 8) for k in matched if k in subject)
        if distinctive or len(kl) < 2:                       # 主体词够特异(连字名/长词) 或 单关键词盘 → 单命中即可
            return True
        return len(matched) >= 2                              # 多关键词盘需 ≥2 共现，杀单词噪音(Turkey 足球 / 北朝鲜核)

    pool = [p for p in rs if _relevant(p.get("content"))]
    if not pool:
        return None
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
