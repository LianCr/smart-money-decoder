"""
fetcher/price.py — C·价格盘口 fetcher（v3 简报数据层 · 批4）

职责：给定 outcome token，算"还有没有空间"——当前/历史时点价、隐含概率、剩余空间、赔率、
相对入场价的变化。是 decoder `price_info` 的等价物，但建在 568 上、且**回测可 as-of**。

数据源：568 Candlesticks（历史 K线，token_id → close）+ 574 结算值（已结算时）。全免费 key。

🔴 数字纪律（继承红线 #5：数字数学只能代码做）：
- 隐含概率 = 该 outcome token 现价（二元市场 price≈P(outcome)）。
- 剩余空间/赔率/价差全由代码从现价算，不喂 AI 去算。
- as_of < 结算 → 用 568 历史价（回测口径，防泄漏）；as_of ≥ 结算 → 用结算值(赢1/输0)。
- 短引信盘 T-7 未创建 → 568 返 None，如实返 None（不编造），下游降级。
"""

from datetime import datetime, timezone

from fetcher.heisenberg import AGENTS, HeisenbergError, call, results


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def price_at(token_id, date_str):
    """568 取 date_str 当日（或之前最近）的 close。拿不到→None（如市场尚未创建）。"""
    end = int(datetime.strptime(date_str, "%Y-%m-%d")
              .replace(tzinfo=timezone.utc, hour=23, minute=59, second=59).timestamp())
    start = end - 10 * 86400
    agent, _ = AGENTS["candles"]
    rs = results(call(agent, {"token_id": token_id, "interval": "1d",
                              "start_time": str(start), "end_time": str(end)}))
    if not rs:
        return None
    rs = sorted(rs, key=lambda r: str(r.get("candle_time", "")))
    return _f(rs[-1].get("close"))


def get_price_context(token_id, outcome, market, entry_price=None, as_of_date="2026-06-20"):
    """
    组装该 outcome 在 as_of 时点的价格结构。market = 574 返回的市场 dict。
    返回含：current_price / implied_probability / 剩余空间 / 赔率 / 相对入场价变化。
    """
    settle_date = str(market.get("closed_date") or market.get("end_date") or "")[:10]
    settled_by_asof = bool(settle_date) and as_of_date >= settle_date

    out = {"as_of": as_of_date, "analyzed_side": outcome}

    if settled_by_asof:
        won = outcome.lower() == str(market.get("winning_outcome", "")).lower()
        cur = 1.0 if won else 0.0
        out["price_source"] = "结算值(已resolve)"
    else:
        cur = price_at(token_id, as_of_date)
        out["price_source"] = "568历史close" if as_of_date < datetime.now(tz=timezone.utc).strftime("%Y-%m-%d") else "568最新close"

    if cur is None:
        out["current_price"] = None
        out["note"] = "拿不到该时点价（市场可能尚未创建/无成交）→ 下游降级，不编造"
        return out

    out["current_price"] = round(cur, 4)
    out["implied_probability_pct"] = round(cur * 100, 2)   # 二元 price≈P(outcome)

    # 剩余空间 / 赔率（代码算，红线 #5）
    if 0 < cur < 1:
        out["remaining_upside_per_share_usd"] = round(1 - cur, 4)      # 赢则每股还能到 $1
        out["remaining_upside_pct_if_win"] = round((1 - cur) / cur * 100, 2)  # 从此刻入、赢的回报%
        out["downside_per_share_usd"] = round(cur, 4)                  # 输则归零
        out["odds_to_one"] = round((1 - cur) / cur, 2)                 # x:1
    else:
        out["remaining_upside_pct_if_win"] = 0.0
        out["note_space"] = "已在端点(0或1)，无剩余空间"

    # 相对入场价（如给了 entry_price）
    if entry_price:
        out["entry_price"] = round(entry_price, 4)
        out["price_delta"] = round(cur - entry_price, 4)
        out["price_delta_pct"] = round((cur - entry_price) / entry_price * 100, 2)

    return out


# ── 冒烟测（免费 key、不烧老师 token）──────────────────────────────────────────
if __name__ == "__main__":
    import json
    # 拿 Starmer-31 的 Yes token + 市场
    agent, _ = AGENTS["markets"]
    m = results(call(agent, {"market_slug": "starmer-out-by-may-31-2026", "closed": "True"}))[0]
    yes_tok = m["side_a_token_id"] if m["side_a_outcome"] == "Yes" else m["side_b_token_id"]

    print("批4 price.py 冒烟测 · Starmer out by May 31 · 分析侧 Yes\n" + "=" * 64)

    print("【历史时点价 price_at（回测原语）】")
    for d in ("2026-05-13", "2026-05-20", "2026-05-28", "2026-06-20"):
        print(f"  {d}  close={price_at(yes_tok, d)}")

    print("\n【价格结构 · as_of=2026-05-13（市场开放时，入场视角）entry_price=0.1858】")
    print(" ", json.dumps(get_price_context(yes_tok, "Yes", m, entry_price=0.1858,
                                            as_of_date="2026-05-13"), ensure_ascii=False, indent=2))

    print("\n【价格结构 · as_of=2026-06-20（已结算）】")
    print(" ", json.dumps(get_price_context(yes_tok, "Yes", m, entry_price=0.1858,
                                            as_of_date="2026-06-20"), ensure_ascii=False))

    print("\n价格 fetcher 就绪。")
