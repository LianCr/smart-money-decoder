"""
fetcher/positions.py — Heisenberg 版"钱包最大政治仓"查找器（v3 简报入口）

为什么不用 fetcher/polymarket.py 的 get_top_political_position：
它打真实 data-api/gamma-api.polymarket.com，那两个公开 API 会挂（实测 HTTP 000 挂 18s）→ API_TIMEOUT。
而整个简报数据层跑的是 Heisenberg（可达、2026 数据世界）。让入口也走 Heisenberg = 数据世界一致 + 不依赖会挂的外部 API。

口径：拉钱包近 60 天成交(556)，按 (市场,outcome) 聚合买入成本，取成本最大的政治盘（优先未结算），
返回 {market_id(=condition_id), outcome, market_question}，喂给 assemble_briefing。
"""

from datetime import datetime, timedelta, timezone

from fetcher.heisenberg import AGENTS, HeisenbergError, call, paginate, results

POLITICAL_KW = (
    "trump", "biden", "starmer", "election", "president", "fed", "powell", "senate",
    "congress", "governor", "prime minister", "parliament", "putin", "zelensky",
    "netanyahu", "nominee", "primary", "referendum", "cabinet", "resign", "impeach",
    "nato", "ceasefire", "shutdown", "tariff", "mayor", "supreme court", "epstein",
    "macron", "milei", "maduro", "venezuela", "gaza", "ukraine", "nuclear", "sanction",
    "out by", "out as", "vance", "newsom", "labour", "tory",
)
SPORT_KW = ("fifa", "world-cup", "nba", "nfl", "nhl", "ufc", "mlb", "soccer", "tennis",
            "-cup-", "premier-league", "hockey", "baseball", "home-run", "temperature")


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def get_top_political_position_hz(wallet, as_of="2026-06-20", min_cost=300.0):
    """返回该钱包最大政治持仓 {market_id, outcome, market_question} 或 {error,reason,message}。"""
    wallet = (wallet or "").strip()
    if not (wallet.startswith("0x") and len(wallet) == 42):
        return {"error": True, "reason": "INVALID_ADDRESS", "message": "钱包地址格式不对（应为 0x + 40 位）"}

    end = datetime.strptime(as_of, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    start = end - timedelta(days=60)
    try:
        trades = paginate(AGENTS["trades"][0],
                          {"proxy_wallet": wallet, "condition_id": "ALL",
                           "start_time": str(int(start.timestamp())), "end_time": str(int(end.timestamp()))},
                          max_pages=15)
    except HeisenbergError as e:
        return {"error": True, "reason": e.reason, "message": e.message}
    if not trades:
        return {"error": True, "reason": "NO_POSITIONS", "message": "该钱包近 60 天无成交记录"}

    # 按 (cid, outcome) 聚合买入成本
    agg, slugs = {}, {}
    for t in trades:
        if str(t.get("side", "")).upper() != "BUY":
            continue
        cid, o = t.get("condition_id"), t.get("outcome")
        cost = (_f(t.get("size")) or 0) * (_f(t.get("price")) or 0)
        if not cid:
            continue
        agg.setdefault(cid, {}).setdefault(o, 0.0)
        agg[cid][o] += cost
        slugs[cid] = str(t.get("slug", ""))

    # 按总买入成本排序，找成本最大的政治盘（优先未结算）；非政治留作兜底
    ranked = sorted(agg.items(), key=lambda kv: -sum(kv[1].values()))
    fallback = None
    for cid, outs in ranked:
        total = sum(outs.values())
        if total < min_cost and fallback is not None:
            break
        outcome = max(outs.items(), key=lambda kv: kv[1])[0]   # 主仓侧（买入成本更大那侧）
        m = results(call(AGENTS["markets"][0], {"condition_id": cid})) \
            or results(call(AGENTS["markets"][0], {"condition_id": cid, "closed": "True"}))
        if not m:
            continue
        m = m[0]
        q = str(m.get("question", ""))
        blob = (q + " " + slugs.get(cid, "")).lower()
        is_sport = any(k in blob for k in SPORT_KW)
        is_pol = any(k in blob for k in POLITICAL_KW) and not is_sport
        is_open = not bool(m.get("closed"))
        cand = {"market_id": cid, "outcome": outcome, "market_question": q,
                "_open": is_open, "_pol": is_pol, "_cost": round(total, 2)}
        if fallback is None:
            fallback = cand
        if is_pol and total >= min_cost:          # 命中政治+达标 → 优先返回
            return {k: cand[k] for k in ("market_id", "outcome", "market_question")}

    if fallback:                                   # 无政治盘则返回最大仓兜底
        return {k: fallback[k] for k in ("market_id", "outcome", "market_question")}
    return {"error": True, "reason": "ALL_BELOW_MIN_VALUE", "message": "未找到达标持仓"}


if __name__ == "__main__":
    import json
    for w in ["0x9d84ce0306f8551e02efef1680475fc0f1dc1344",
              "0xbf961d0c79db0bf55050cadc0995835f09c09942"]:
        print(w[:12], "→", json.dumps(get_top_political_position_hz(w), ensure_ascii=False))
