"""
analyzer/price_reaction.py — 新闻↔价格反应计算器（catalyst 份量刻度 · 市场测谎仪）

给每条催化剂一个客观的"市场份量刻度"：用 568 历史价算"该新闻发布前后市场动了多少%"，
补上双向催化剂"计数 vs 份量"两难——材质标签=定性类型，price_reaction=定量市场反应。

🔴 三条诚实红线（设计阶段钉死）：
- **归因**：只说"该新闻发布前后市场变动 X%"，**绝不说"这条新闻导致 X%"**（时间相关≠因果，
  比 Polymarket 前端那个暗示因果的标注更诚实——这是本计算器能存在的前提）。
- **多新闻同窗**：同一天多条催化剂共享同一段价格变动 → 标"合计、不可归因到单条"。
- **回测防泄漏**：p_after 窗口超过 as_of = 偷看未来价 → 反应返不可知(None)，不泄漏。

🎁 核心功能·市场测谎仪：当价格反应方向与 LLM 正负分类矛盾（LLM 说利好但市场跌 / 说利空但
市场涨）→ 显式标 ⚠️ 不一致。市场用真金白银抓 LLM 的偏差，裁判比 AI 自己更硬。

窗口：前一日 close → 次日 close（给市场一天消化）。粒度=日（Tavily published_at 只到天，
强行分钟级=假精度，不做）。短引信盘无价 → None 降级（继承 price.py）。
"""

from datetime import datetime, timedelta, timezone

from fetcher.price import price_at

MEANINGFUL_MOVE_PCT = 5.0   # 低于此视为"市场反应微弱"，不触发矛盾旗标（避免噪音误报）
_POLARITY = {"positive": +1, "negative": -1}   # 正向催化剂期望市场▲；负向期望▼


def _shift(date_str, days):
    d = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=days)
    return d.strftime("%Y-%m-%d")


def compute_reaction(token_id, news_date, as_of=None):
    """
    单条新闻的市场反应。返回 dict。
    窗口：前一日 close → 次日 close。
    as_of（YYYY-MM-DD，可选）：回测时点上界；p_after 窗口超过它 → 不可知(防泄漏)。
    """
    before_date = _shift(news_date, -1)
    after_date = _shift(news_date, +1)

    # 🔴 回测防泄漏：新闻之后的价格若超过 as_of，等于偷看未来
    if as_of is not None and after_date > as_of:
        return {"available": False, "reason": "as_of_leak_guard",
                "note": "新闻后价格尚未发生(回测防泄漏)，反应不可知"}

    p_before = price_at(token_id, before_date)
    p_after = price_at(token_id, after_date)
    if p_before is None or p_after is None or p_before == 0:
        return {"available": False, "reason": "no_price",
                "note": "新闻时点拿不到价(市场未创建/无成交) → 反应不可知，不编造"}

    move = p_after - p_before
    move_pct = move / p_before * 100
    return {
        "available": True,
        "window": [before_date, after_date],
        "price_before": round(p_before, 4),
        "price_after": round(p_after, 4),
        "move_pct": round(move_pct, 2),
        "direction": "▲" if move > 0 else ("▼" if move < 0 else "—"),
        "caveat": "该新闻发布前后市场变动，时间相关非因果",
    }


def _market_check(reaction, polarity):
    """市场测谎仪：价格反应方向 vs LLM 正负分类是否一致。"""
    if not reaction.get("available"):
        return "市场反应不可知"
    move = reaction["move_pct"]
    if abs(move) < MEANINGFUL_MOVE_PCT:
        return f"市场反应微弱(<{MEANINGFUL_MOVE_PCT:g}%)"
    expected = _POLARITY.get(polarity, 0)
    actual = 1 if move > 0 else -1
    if expected == 0:
        return "无方向预期"
    return "市场印证该分类" if actual == expected else "⚠️市场反应与该分类不一致"


def enrich_catalysts(catalysts, token_id, polarity, as_of=None):
    """
    给一组催化剂（正向或负向）逐条加 price_reaction + market_check。
    polarity: "positive"(期望市场▲) | "negative"(期望市场▼)。
    多条同窗 → 标"合计、不可归因到单条"。原地修改并返回。
    """
    # 先按"窗口"分组，识别同窗多新闻
    window_count = {}
    for c in catalysts:
        d = c.get("date")
        if d:
            window_count[d] = window_count.get(d, 0) + 1

    for c in catalysts:
        d = c.get("date")
        if not d:
            c["price_reaction"] = {"available": False, "reason": "no_date"}
            continue
        r = compute_reaction(token_id, d, as_of=as_of)
        r["market_check"] = _market_check(r, polarity)
        if window_count.get(d, 0) > 1:
            r["same_window"] = f"同窗{window_count[d]}条新闻，变动为合计、不可归因到单条"
        c["price_reaction"] = r
    return catalysts


# ── 冒烟测（免费 key、不烧老师 token）──────────────────────────────────────────
if __name__ == "__main__":
    import json
    from fetcher.heisenberg import AGENTS, call, results

    # Starmer-31 的 Yes token（押注 Yes=他下台）
    m = results(call(AGENTS["markets"][0],
                     {"market_slug": "starmer-out-by-may-31-2026", "closed": "True"}))[0]
    yes_tok = m["side_a_token_id"] if m["side_a_outcome"] == "Yes" else m["side_b_token_id"]

    print("price_reaction 冒烟测 · Starmer Yes(他下台) · 市场测谎仪\n" + "=" * 70)

    # 取双向催化剂跑出的真实催化剂日期
    positive = [  # LLM 判"支持 Yes"（辞职压力）—— 期望市场▲
        {"title": "Starmer faces wave of resignation calls", "date": "2026-05-11"},
        {"title": "Starmer fights for his job after election losses", "date": "2026-05-12"},
    ]
    negative = [  # LLM 判"威胁 Yes"（他拒绝辞职）—— 期望市场▼
        {"title": "Starmer promises he'll fight to stay on", "date": "2026-05-11"},
        {"title": "Starmer rejects calls to resign", "date": "2026-05-13"},
    ]

    enrich_catalysts(positive, yes_tok, "positive")
    enrich_catalysts(negative, yes_tok, "negative")

    print("\n【正向催化剂（LLM 说支持 Yes，期望市场▲）】")
    for c in positive:
        r = c["price_reaction"]
        print(f"  · {c['title']}  [{c['date']}]")
        if r.get("available"):
            print(f"    {r['direction']} {r['move_pct']}%  ({r['price_before']}→{r['price_after']})  → {r['market_check']}")
        else:
            print(f"    {r['note']}")

    print("\n【负向催化剂（LLM 说威胁 Yes，期望市场▼）】")
    for c in negative:
        r = c["price_reaction"]
        print(f"  · {c['title']}  [{c['date']}]")
        if r.get("available"):
            print(f"    {r['direction']} {r['move_pct']}%  ({r['price_before']}→{r['price_after']})  → {r['market_check']}")
        else:
            print(f"    {r['note']}")

    print("\n【as-of 防泄漏自检】新闻 2026-05-19，as_of=2026-05-19（p_after 窗口=5/20>as_of，应拦）")
    print(" ", json.dumps(compute_reaction(yes_tok, "2026-05-19", as_of="2026-05-19"), ensure_ascii=False))

    print("\n计算器就绪，将接进双向催化剂当份量刻度 + 测谎仪。")
