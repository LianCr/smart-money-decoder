"""
fetcher/actions.py — B·持仓+动作 fetcher（v3 简报数据层 · 批3）

职责：给定钱包 + 市场(condition_id) + 分析侧(outcome)，组装"他做了什么动作"。
建在 fetcher/heisenberg.py 地基之上，全免费 key、不烧老师 token。

数据源：
- 556 Trades   → 建仓时点 / 进场均价 / 加减仓 / 两侧分布(对冲检测)
- 568 Candles  → 当前价 → 浮盈亏（针对"分析侧"，不是鲸鱼净对冲）
- 574 Markets  → 分析侧 token 映射 / 赢方 / 离结算多久

口径纪律（继承路 B）：
- 只算"分析侧"这一腿的动作与浮盈亏（鲸鱼可能两边对冲，但我们跟的是被分析的那一侧）。
- 两侧分布单独给出做对冲标记，让用户看清这是单边客还是做市玩家（接 #28）。
- 真实已实现盈亏走 556+574 自重建/569；本模块浮盈亏=未实现，用 568 现价×成本基础。
"""

from datetime import datetime, timezone

from core.config import BRIEFING_AS_OF
from fetcher.heisenberg import AGENTS, HeisenbergError, call, paginate, results


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _parse_ts(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _get_market(cid):
    agent, _ = AGENTS["markets"]
    rs = results(call(agent, {"condition_id": cid, "closed": "True"}))
    if not rs:  # 未结算市场默认不返回 → 再不带 closed 查一次
        rs = results(call(agent, {"condition_id": cid}))
    return rs[0] if rs else None


def _current_price(token_id, as_of_date):
    """568 取截至 as_of 的最后一根 close（当前/快照价）。"""
    end = int(datetime.strptime(as_of_date, "%Y-%m-%d")
              .replace(tzinfo=timezone.utc, hour=23, minute=59, second=59).timestamp())
    start = end - 10 * 86400
    agent, _ = AGENTS["candles"]
    rs = results(call(agent, {"token_id": token_id, "interval": "1d",
                              "start_time": str(start), "end_time": str(end)}))
    if not rs:
        return None
    rs = sorted(rs, key=lambda r: str(r.get("candle_time", "")))
    return _f(rs[-1].get("close"))


def get_position_actions(wallet, cid, outcome, as_of_date=BRIEFING_AS_OF):
    """组装该钱包在该市场、analyzed 侧(outcome) 的动作画像。子源失败不拖垮整体。"""
    out = {"wallet": wallet, "condition_id": cid, "analyzed_side": outcome}

    # 1) 574：分析侧 token + 赢方 + 结算
    try:
        m = _get_market(cid)
    except HeisenbergError as e:
        return {**out, "error": f"574 {e.reason}: {e.message}"}
    if not m:
        return {**out, "error": "574 查不到该市场"}

    a_out, b_out = str(m.get("side_a_outcome", "")), str(m.get("side_b_outcome", ""))
    if outcome.lower() == a_out.lower():
        token = m.get("side_a_token_id")
    elif outcome.lower() == b_out.lower():
        token = m.get("side_b_token_id")
    else:
        return {**out, "error": f"outcome={outcome} 对不上 574 两侧({a_out}/{b_out})"}

    closed_date = m.get("closed_date") or m.get("end_date")
    cd = _parse_ts(closed_date)
    asof = datetime.strptime(as_of_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    days_to_settle = round((cd - asof).total_seconds() / 86400, 1) if cd else None
    out["market"] = {
        "question": m.get("question"), "winning_outcome": m.get("winning_outcome"),
        "closed": bool(m.get("closed")), "settle_date": str(closed_date)[:10] if closed_date else None,
        "days_to_settlement": days_to_settle,
        "settle_note": ("已结算" if (days_to_settle is not None and days_to_settle <= 0)
                        else (f"还有约{days_to_settle}天" if days_to_settle is not None else "未知")),
    }

    # 2) 556：该钱包在此盘全量成交
    try:
        agent, wp = AGENTS["trades"]
        trades = paginate(agent, {wp: wallet, "condition_id": cid}, max_pages=20)
    except HeisenbergError as e:
        return {**out, "error": f"556 {e.reason}: {e.message}"}

    # 两侧分布（对冲检测）
    side_buys = {}
    for t in trades:
        if str(t.get("side", "")).upper() == "BUY":
            o = t.get("outcome")
            side_buys.setdefault(o, {"trades": 0, "shares": 0.0, "cost": 0.0})
            side_buys[o]["trades"] += 1
            side_buys[o]["shares"] += _f(t.get("size")) or 0
            side_buys[o]["cost"] += (_f(t.get("size")) or 0) * (_f(t.get("price")) or 0)
    hedged = {"Yes", "No"}.issubset(set(side_buys.keys()))
    out["two_side_distribution"] = {
        "hedged": hedged,
        "by_outcome": {k: {"trades": v["trades"], "shares": round(v["shares"], 1)}
                       for k, v in side_buys.items()},
        "note": ("两边都大额建仓 = 做市/对冲玩家（非单边赌徒，接 #28）" if hedged
                 else "仅单边建仓"),
    }

    # 分析侧这一腿的动作
    leg = [t for t in trades if str(t.get("outcome", "")).lower() == outcome.lower()]
    buys = [t for t in leg if str(t.get("side", "")).upper() == "BUY"]
    sells = [t for t in leg if str(t.get("side", "")).upper() == "SELL"]
    buy_shares = sum(_f(t.get("size")) or 0 for t in buys)
    buy_cost = sum((_f(t.get("size")) or 0) * (_f(t.get("price")) or 0) for t in buys)
    sell_shares = sum(_f(t.get("size")) or 0 for t in sells)
    sell_proceeds = sum((_f(t.get("size")) or 0) * (_f(t.get("price")) or 0) for t in sells)
    net_shares = buy_shares - sell_shares
    net_cost = buy_cost - sell_proceeds
    ts_sorted = sorted([_parse_ts(t.get("timestamp")) for t in buys if _parse_ts(t.get("timestamp"))])

    out["actions"] = {
        "entry_time": ts_sorted[0].strftime("%Y-%m-%d %H:%M") if ts_sorted else None,
        "last_add_time": ts_sorted[-1].strftime("%Y-%m-%d %H:%M") if ts_sorted else None,
        "num_buys": len(buys), "num_sells": len(sells),
        "added_over_time": len(buys) > 1,
        "avg_entry_price": round(buy_cost / buy_shares, 4) if buy_shares else None,
        "net_shares": round(net_shares, 1),
        "net_cost_usd": round(net_cost, 2),
    }

    # 3) 现价 → 浮盈亏（分析侧）
    #    已结算市场：现价=结算值（赢方1/输方0），结算后无 K线，必须走 resolve 值；
    #    未结算市场：568 最新 close。
    if out["market"]["closed"]:
        won = outcome.lower() == str(m.get("winning_outcome", "")).lower()
        cur = 1.0 if won else 0.0
        price_source = "结算值(已resolve)"
    else:
        try:
            cur = _current_price(token, as_of_date)
        except HeisenbergError:
            cur = None
        price_source = "568最新close"

    if cur is not None and net_shares:
        cur_value = net_shares * cur
        unrealized = cur_value - net_cost
        out["unrealized"] = {
            "current_price": cur, "price_source": price_source,
            "current_value_usd": round(cur_value, 2),
            "unrealized_pnl_usd": round(unrealized, 2),
            "unrealized_pct": round(unrealized / net_cost * 100, 2) if net_cost else None,
            "note": "已结算→此为最终实现盈亏(分析侧)" if out["market"]["closed"] else "持仓中浮盈亏",
        }
    else:
        out["unrealized"] = {"current_price": cur, "price_source": price_source,
                             "note": "无净仓或拿不到现价"}

    return out


# ── 冒烟测（免费 key、不烧老师 token）──────────────────────────────────────────
if __name__ == "__main__":
    import json
    KEN = "0x9d84ce0306f8551e02efef1680475fc0f1dc1344"
    # 用 574 按 slug 解析 Starmer-31 的 cid（分析侧 Yes，赌他下台）
    agent, _ = AGENTS["markets"]
    m = results(call(agent, {"market_slug": "starmer-out-by-may-31-2026", "closed": "True"}))[0]
    cid = m["condition_id"]

    res = get_position_actions(KEN, cid, "Yes")

    print("批3 actions.py 冒烟测 · ImJustKen · Starmer out by May 31 · 分析侧 Yes\n" + "=" * 66)
    if "error" in res:
        print("ERROR:", res["error"])
    else:
        print("【市场/离结算(574)】", json.dumps(res["market"], ensure_ascii=False))
        print("\n【两侧分布/对冲(556)】", json.dumps(res["two_side_distribution"], ensure_ascii=False))
        print("\n【分析侧动作(556)】", json.dumps(res["actions"], ensure_ascii=False))
        print("\n【浮盈亏(568现价)】", json.dumps(res["unrealized"], ensure_ascii=False))
    print("\n动作 fetcher 就绪。")
