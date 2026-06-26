"""
fetcher/positions.py — Heisenberg 版"钱包最大政治仓"查找器（v3 简报入口）

为什么不用 fetcher/polymarket.py 的 get_top_political_position：
它打真实 data-api/gamma-api.polymarket.com，那两个公开 API 会挂（实测 HTTP 000 挂 18s）→ API_TIMEOUT。
而整个简报数据层跑的是 Heisenberg（可达、2026 数据世界）。让入口也走 Heisenberg = 数据世界一致 + 不依赖会挂的外部 API。

口径：拉钱包近 60 天成交(556)，按 (市场,outcome) 算**当前净持仓**(买入份额−卖出份额，×均买价)，
取净持仓最大的**未结算**政治盘（live 简报问"现在还要不要跟"，已结算盘没意义、绝不返回）。
🔴 用净持仓**不用累计买入成本**：一个边买边卖、已基本清仓的盘，历史买入额可能很大但他已跑掉，
   按买入成本会误选成"最大仓"给用户看个幽灵盘——净持仓才反映他现在还重仓在哪。返回 {market_id, outcome, market_question}。
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


def get_top_political_position_hz(wallet, as_of="2026-06-20", min_cost=300.0, max_pages=15):
    """返回该钱包最大**未结算**政治持仓 {market_id, outcome, market_question} 或 {error,reason,message}。
    max_pages：翻几页成交（默认 15 全量）；扫榜时可调小(如 6)换速度——大户最大净仓多在近几页。"""
    wallet = (wallet or "").strip()
    if not (wallet.startswith("0x") and len(wallet) == 42):
        return {"error": True, "reason": "INVALID_ADDRESS", "message": "钱包地址格式不对（应为 0x + 40 位）"}

    end = datetime.strptime(as_of, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    start = end - timedelta(days=60)
    try:
        trades = paginate(AGENTS["trades"][0],
                          {"proxy_wallet": wallet, "condition_id": "ALL",
                           "start_time": str(int(start.timestamp())), "end_time": str(int(end.timestamp()))},
                          max_pages=max_pages)
    except HeisenbergError as e:
        return {"error": True, "reason": e.reason, "message": e.message}
    if not trades:
        return {"error": True, "reason": "NO_POSITIONS", "message": "该钱包近 60 天无成交记录"}

    # 按 (cid, outcome) 聚合：买入份额/成本 + 卖出份额 → 当前净持仓
    agg, slugs = {}, {}
    for t in trades:
        cid, o = t.get("condition_id"), t.get("outcome")
        if not cid:
            continue
        size = _f(t.get("size")) or 0
        price = _f(t.get("price")) or 0
        side = str(t.get("side", "")).upper()
        d = agg.setdefault(cid, {}).setdefault(o, {"buy_shares": 0.0, "buy_cost": 0.0, "sell_shares": 0.0})
        if side == "BUY":
            d["buy_shares"] += size
            d["buy_cost"] += size * price
        elif side == "SELL":
            d["sell_shares"] += size
        slugs[cid] = str(t.get("slug", ""))

    def _net_cost(d):
        """当前净持仓规模 = max(买入份额−卖出份额, 0) × 该侧均买价（剩余成本基础）。已清仓→≈0，自然落榜。"""
        net = max(d["buy_shares"] - d["sell_shares"], 0.0)
        avg = d["buy_cost"] / d["buy_shares"] if d["buy_shares"] else 0.0
        return net * avg

    # 按当前净持仓降序，取净持仓最大的【未结算政治盘】（live 简报绝不返回已结算盘）
    ranked = sorted(agg.items(), key=lambda kv: -sum(_net_cost(d) for d in kv[1].values()))
    saw_pol_settled = False
    for cid, outs in ranked:
        total = sum(_net_cost(d) for d in outs.values())
        if total < min_cost:
            break                                  # 已降序，后面更小，停
        # 574 默认只返未结算市场；空 = 已结算/不存在 → 该盘不能进 live 简报
        m = results(call(AGENTS["markets"][0], {"condition_id": cid}))
        q_blob_for_settled = slugs.get(cid, "").lower()
        if not m:
            # 确认它是不是"政治但已结算"（仅用于给用户更准的提示）
            if any(k in q_blob_for_settled for k in POLITICAL_KW):
                saw_pol_settled = True
            continue
        m = m[0]
        q = str(m.get("question", ""))
        blob = (q + " " + slugs.get(cid, "")).lower()
        if any(k in blob for k in SPORT_KW):
            continue
        end_d = str(m.get("end_date", ""))[:10]
        live = (not bool(m.get("closed"))) and (not end_d or end_d > as_of)   # 🔴 未结算 + 未到期
        if not live:
            if any(k in blob for k in POLITICAL_KW):
                saw_pol_settled = True
            continue
        if any(k in blob for k in POLITICAL_KW):
            outcome = max(outs.items(), key=lambda kv: _net_cost(kv[1]))[0]   # 净持仓更大的一侧
            return {"market_id": cid, "outcome": outcome, "market_question": q}

    # 没有未结算的政治持仓 → 诚实报错（绝不拿已结算盘充数）
    msg = ("该钱包当前没有未结算的政治持仓（持仓可能均已结算），换个有活跃政治持仓的钱包再试"
           if saw_pol_settled else "该钱包近 60 天无达标的未结算政治持仓")
    return {"error": True, "reason": "NO_OPEN_POSITIONS", "message": msg}


if __name__ == "__main__":
    import json
    for w in ["0x9d84ce0306f8551e02efef1680475fc0f1dc1344",
              "0xbf961d0c79db0bf55050cadc0995835f09c09942"]:
        print(w[:12], "→", json.dumps(get_top_political_position_hz(w), ensure_ascii=False))
