#!/usr/bin/env python3
"""
backtest/route_b.py — 路 B 第一版：$1000 跟单收益率（口径校准，非扩样本）

目标：跑通"AI 说 GO 的注跟入 $1000、算真实收益率 vs 无脑全抄基线"的口径，先校准尺子。
不是测"收益率多少"，是测"这套口径能不能跑通、数字可不可信"。

数据源纪律（关键）：
- 信号正本 = git 跟踪的 `backtest/cases.json`（封板诚实 5/6 版），**不用 .cache/backtest/result.json**
  （那是另一次不同 run 的残留：样本集不同 + Powell 在歧义处翻成 CHASED，已与正本分叉，见 KNOWN_ISSUES #14）。
- cid/价格/结算 = Heisenberg 免费 key 现查（574/568/556/569），**不烧老师 token**。

口径（每个被跟仓位）：
- entry = decoder 判断那一刻 T-1（GO 信号发出时），p_follow 用 568 取 T-1 当日 close（不用鲸鱼建仓价）。
- 跟入 $1000 → shares = 1000/p_follow；赢(分析侧==winning_outcome)→payout=shares×$1，输→0；收益=payout−1000。
- 569 只做交叉校验；所有鲸鱼都两边对冲，故 569 是对冲净值、不可信 → 以 568+574 自重建为准（标记不剔除）。

GO 桶 = T-1 call ∈ {CHASED, ROOM LEFT}；基线 = 全部样本（同 T-1 entry，apples-to-apples）。
lift = GO 平均收益率 − 基线平均收益率 = AI 筛选的真实价值。

运行：.venv/bin/python backtest/route_b.py   （免费 key，不烧老师 token）
"""

import os
import sys
import json
import time
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

URL = "https://narrative.agent.heisenberg.so/api/v2/semantic/retrieve/parameterized"
KEY = os.environ.get("HEISENBERG_API_KEY")
MAX_LIMIT = 200
FOLLOW_USD = 1000.0
GO_CALLS = {"CHASED", "ROOM LEFT"}

CAR = "0x7c3db723f1d4d8cb9c550095203b686cb11e5c6b"
KEN = "0x9d84ce0306f8551e02efef1680475fc0f1dc1344"

CASES_PATH = os.path.join(os.path.dirname(__file__), "cases.json")


# 正本市场 → (精确 slug, 鲸鱼)。slug 由鲸鱼成交 + cases.json 问句双重核实（探针验证过，
# 避免关键词歧义：us-iran 撞 5 盘、airspace 撞 israel、powell 撞 may-14/16/31）。
def resolve_market(market):
    m = market.lower()
    if "project freedom" in m:
        return "will-trump-restart-project-freedom-by-june-30", CAR
    if "diplomatic meeting" in m and "june 10" in m:
        return "us-x-iran-diplomatic-meeting-by-june-10-2026", CAR
    if "airspace" in m and "june 8" in m:
        return "iran-closes-its-airspace-by-june-8", CAR
    if "starmer" in m and "may 31" in m:
        return "starmer-out-by-may-31-2026", KEN
    if "starmer" in m and "may 15" in m:
        return "starmer-out-by-may-15-2026", KEN
    if "powell" in m and "may 15" in m:
        return "jerome-powell-out-as-fed-chair-by-may-15-2026", KEN
    return None, None


# ---------------------------------------------------------------------------
def call(agent_id, params, limit=MAX_LIMIT, offset=0):
    body = {"agent_id": agent_id, "params": params,
            "pagination": {"limit": min(limit, MAX_LIMIT), "offset": offset},
            "formatter_config": {"format_type": "raw"}}
    r = requests.post(URL, headers={"Authorization": f"Bearer {KEY}"}, json=body, timeout=30)
    if r.status_code != 200:
        return None, f"{r.status_code}: {r.text[:160]}"
    return r.json(), None


def results(payload):
    d = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(d, dict):
        return d.get("results", [])
    return d if isinstance(d, list) else []


def to_unix(date_str, end_of_day=False):
    d = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if end_of_day:
        d = d.replace(hour=23, minute=59, second=59)
    return int(d.timestamp())


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
def get_market(slug):
    payload, err = call(574, {"market_slug": slug, "closed": "True"}, limit=3)
    if err:
        return None, err
    rs = results(payload)
    return (rs[0] if rs else None), None


def price_at(token_id, date_str):
    """568 取 date_str 当日最后一根 close（decoder 判断那一刻的市价）。空则放宽到 ±2 天 1d。"""
    s, e = to_unix(date_str), to_unix(date_str, end_of_day=True)
    payload, err = call(568, {"token_id": token_id, "interval": "1h",
                              "start_time": str(s), "end_time": str(e)})
    rs = results(payload) if not err else []
    if not rs:  # 放宽
        payload, err = call(568, {"token_id": token_id, "interval": "1d",
                                  "start_time": str(s - 2 * 86400), "end_time": str(e)})
        rs = results(payload) if not err else []
    if not rs:
        return None
    rs = sorted(rs, key=lambda r: str(r.get("candle_time", "")))
    return fnum(rs[-1].get("close"))


def whale_two_sided(whale, cid):
    """556 看鲸鱼在此盘是否两边都 BUY（对冲标记）。"""
    outs = set()
    for off in range(0, 4000, MAX_LIMIT):
        payload, err = call(556, {"proxy_wallet": whale, "condition_id": cid}, offset=off)
        if err:
            break
        page = results(payload)
        for t in page:
            if str(t.get("side", "")).upper() == "BUY":
                outs.add(t.get("outcome"))
        if len(page) < MAX_LIMIT:
            break
        time.sleep(0.1)
    return {"Yes", "No"}.issubset(outs), outs


def realized_569(whale, cid, t1_date, closed_date):
    """569 交叉校验（informational）：锚 T-1 ~ 结算后几天的已实现 PnL。"""
    start = t1_date
    try:
        cd = datetime.fromisoformat(str(closed_date).replace("Z", "+00:00"))
        end = (cd.replace(hour=0, minute=0, second=0)).strftime("%Y-%m-%d")
        end = (cd).strftime("%Y-%m-%d")
    except (ValueError, AttributeError):
        end = t1_date
    payload, err = call(569, {"wallet": whale, "granularity": "1d",
                              "start_time": start, "end_time": end, "condition_id": cid})
    if err:
        return None
    total = 0.0
    for r in results(payload):
        v = fnum(r.get("pnl"))
        if v:
            total += v
    return total


# ---------------------------------------------------------------------------
def main():
    if not KEY:
        sys.exit("❌ 没设 HEISENBERG_API_KEY（写进 .env，脚本自动读）")

    cases = json.load(open(CASES_PATH)).get("cases", [])
    print("路 B 第一版 · $1000 跟单收益率（口径校准）")
    print(f"信号正本：backtest/cases.json（{len(cases)} 样本，封板诚实版）· 价格/结算：Heisenberg 免费 key\n")

    rows = []
    for c in cases:
        market = c.get("market", "")
        slug, whale = resolve_market(market)
        if not slug:
            print(f"⚠️ 无法解析市场，跳过：{market}")
            continue
        m, err = get_market(slug)
        if not m:
            print(f"⚠️ 574 查不到 {slug}：{err}")
            continue
        # 守卫：574 问句要对得上正本，防 slug 错配
        if market.split("?")[0][:18].lower() not in str(m.get("question", "")).lower():
            print(f"⚠️ slug 问句不匹配！正本='{market}' vs 574='{m.get('question')}' — 跳过防污染")
            continue

        cid = m.get("condition_id")
        win_out = str(m.get("winning_outcome", ""))
        side = str(c.get("wallet_side", ""))           # decoder 分析的那一侧
        # 分析侧 → token_id
        if side.lower() == str(m.get("side_a_outcome", "")).lower():
            token = m.get("side_a_token_id")
        elif side.lower() == str(m.get("side_b_outcome", "")).lower():
            token = m.get("side_b_token_id")
        else:
            print(f"⚠️ wallet_side={side} 对不上 574 两侧，跳过：{market}")
            continue

        t1 = c.get("t1", {}) or {}
        t1_call = str(t1.get("call", "?"))
        t1_date = str(t1.get("date", ""))

        p_follow = price_at(token, t1_date)
        if not p_follow or p_follow <= 0:
            print(f"⚠️ 568 拿不到 {market} 的 T-1 价，跳过")
            continue

        won = (side.lower() == win_out.lower())
        # 自重建跟单收益（568+574，确定性）
        shares = FOLLOW_USD / p_follow
        payout = shares * 1.0 if won else 0.0
        ret_usd = payout - FOLLOW_USD
        ret_pct = ret_usd / FOLLOW_USD * 100

        # 一致性守卫：与 cases.json bet_won 对齐
        if c.get("bet_won") is not None and bool(c["bet_won"]) != won:
            print(f"⚠️ bet_won 不一致！cases={c.get('bet_won')} vs 574 推断={won}（{market}）")

        hedged, outs = whale_two_sided(whale, cid)
        r569 = realized_569(whale, cid, t1_date, m.get("closed_date"))

        rows.append({
            "market": market, "whale": "Car" if whale == CAR else "ImJustKen",
            "side": side, "call": t1_call, "is_go": t1_call in GO_CALLS,
            "t1_date": t1_date, "p_follow": p_follow, "shares": shares,
            "won": won, "ret_usd": ret_usd, "ret_pct": ret_pct,
            "hedged": hedged, "r569": r569,
        })
        time.sleep(0.15)

    # ---- 输出 ----
    def avg(xs):
        return sum(xs) / len(xs) if xs else 0.0

    print("\n" + "=" * 92)
    print("全样本明细（基线 = 全抄每一注，同 T-1 entry）")
    print("=" * 92)
    print(f"{'市场':<40}{'鲸鱼':<10}{'侧':<5}{'T-1判断':<10}{'p_follow':>9}{'结局':>6}{'收益%':>9}")
    for r in rows:
        print(f"{r['market'][:38]:<40}{r['whale']:<10}{r['side']:<5}{r['call']:<10}"
              f"{r['p_follow']:>9.4f}{'赢' if r['won'] else '输':>6}{r['ret_pct']:>9.2f}")

    go = [r for r in rows if r["is_go"]]
    print("\n" + "=" * 92)
    print("GO 注（decoder 判 CHASED/ROOM LEFT = 背书跟）")
    print("=" * 92)
    for r in go:
        print(f"· {r['market'][:46]}")
        print(f"    判断={r['call']} | p_follow={r['p_follow']:.4f} | 份额={r['shares']:,.0f} | "
              f"结局={'赢' if r['won'] else '输'} | 收益=${r['ret_usd']:,.2f} ({r['ret_pct']:+.2f}%)")

    hedged_rows = [r for r in rows if r["hedged"]]
    if hedged_rows:
        print("\n" + "=" * 92)
        print("⚑ 对冲标记样本（保留不剔除；569 交叉校验降级、以 568+574 自重建为准）")
        print("=" * 92)
        for r in hedged_rows:
            print(f"· {r['market'][:46]:<48} 569实现PnL={r['r569']} ←对冲净值不可信，已用自重建")

    go_avg = avg([r["ret_pct"] for r in go])
    base_avg = avg([r["ret_pct"] for r in rows])
    lift = go_avg - base_avg

    print("\n" + "#" * 92)
    print("数字（路 B 第一版）")
    print("#" * 92)
    print(f"  GO 注平均收益率   ：{go_avg:+.2f}%   （{len(go)} 注：{', '.join('赢' if r['won'] else '输' for r in go)}）")
    print(f"  基线(全抄)平均收益：{base_avg:+.2f}%   （{len(rows)} 注）")
    print(f"  lift = GO − 基线  ：{lift:+.2f}%")
    print(f"  样本数：GO {len(go)} / 总 {len(rows)} / 对冲标记 {len(hedged_rows)}")

    print("\n" + "-" * 92)
    print("🔴 必读局限（尺子的诚实交代，别误读成『decoder 不行』）")
    print("-" * 92)
    print("""  · 这 6 个样本是 v2 为测『判断方向』挑的，不是为测『跟单收益』挑的。
  · 所以 GO 全是 T-1 晚点 CHASED 信号（价已≈0.99、没空间）→ 跟入收益≈0，即便方向对。
  · 路 B 第一版因此只能测出【防御性价值】（decoder 把 -100% 的输盘判 NO BASIS 躲掉了），
    测不出【进攻性价值】（GO 赚钱）。这不是 decoder 不行——是尺子诚实告诉我们：
    要展示进攻收益，需要【早时点 ROOM LEFT 样本】，那要下一步 #27『看动作·早进场』才拿得到。
  · 小样本(6)、会波动、不具统计结论性。第一版目的是校准尺子，不是下收益率结论。""")


if __name__ == "__main__":
    main()
