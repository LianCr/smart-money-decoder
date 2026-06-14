"""
backtest/_health_check.py — 市场优先取样的「打折测试 + 偏差体检」（诊断，非生产）

回答三个数（建管道前的生死检查）：
  1. 真实转化率：随机候选跑完整链路（入场重建 + 建仓时点 decoder），100 个候选活下来几个有效样本？
  2. 美元门槛：把 "sizable" 从 ≥5000股 统一回 >$5000 美元（cost=entry_price×size），还剩多少。
  3. holders 偏差体检（最关键）：候选的最终结局（赢/输）分布——/holders 快照是否系统性偏向某种结局
     （赢家赎回离场→偏向输家？这会污染 lift，与 v1「输盘读不到偏向赢盘」同源）。

下划线前缀 = 内部诊断，不入生产、可删。
"""
import random
import sys
from collections import defaultdict, Counter

import requests
from dotenv import load_dotenv
load_dotenv()

from fetcher.polymarket import _is_political_event
from fetcher.news import get_news_for_market
from analyzer.decoder import DecoderError
from backtest.resolution import get_market_resolution
from backtest.pipeline import _assemble, _date, _decode_retry

GAMMA = "https://gamma-api.polymarket.com"
DATA = "https://data-api.polymarket.com"
random.seed(7)


def _log(m): print(m, file=sys.stderr, flush=True)


def reconstruct(wallet, cid):
    """单个 (wallet, market) 的持有侧仓位（BUY 加权）→ pos dict 或 None。"""
    by = defaultdict(lambda: {"cost": 0.0, "size": 0.0, "asset": None, "min_ts": None, "title": None})
    off = 0
    while off < 400:
        try:
            tr = requests.get(f"{DATA}/trades", params={"market": cid, "user": wallet, "limit": 100, "offset": off}, timeout=12).json()
        except Exception:
            break
        if not isinstance(tr, list) or not tr:
            break
        for x in tr:
            if x.get("side") != "BUY":
                continue
            oc = x.get("outcome")
            if oc is None:
                continue
            d = by[oc]
            sz = float(x.get("size") or 0); pr = float(x.get("price") or 0)
            d["cost"] += sz * pr; d["size"] += sz
            d["asset"] = d["asset"] or x.get("asset")
            ts = x.get("timestamp")
            d["min_ts"] = ts if d["min_ts"] is None else min(d["min_ts"], ts)
            d["title"] = x.get("title") or d["title"]
        if len(tr) < 100:
            break
        off += 100
    if not by:
        return None
    oc, d = max(by.items(), key=lambda kv: kv[1]["size"])
    if d["size"] <= 0:
        return None
    return {"outcome": oc, "entry_price": round(d["cost"] / d["size"], 4), "size": d["size"],
            "token": d["asset"], "entry_time": d["min_ts"], "title": d["title"]}


def main():
    # ── 1. 已结算政治盘 seeds（含 winner）──
    evs = requests.get(f"{GAMMA}/events", params={"closed": "true", "order": "volume", "ascending": "false", "limit": 120}, timeout=15).json()
    seen = set(); seeds = []
    for e in evs:
        if not _is_political_event(e) or e.get("title") in seen:
            continue
        for m in (e.get("markets") or []):
            cid = m.get("conditionId")
            if cid and m.get("closed"):
                seeds.append(cid); seen.add(e.get("title")); break
        if len(seeds) >= 12:
            break
    _log(f"seeds（不同政治事件已结算盘）：{len(seeds)}")

    # ── 2. /holders → 候选池（带每盘 winner）──
    cands = []  # (wallet, cid, winner)
    res_cache = {}
    for cid in seeds:
        res = get_market_resolution(cid)
        if not res:
            continue
        res_cache[cid] = res
        try:
            h = requests.get(f"{DATA}/holders", params={"market": cid, "limit": 50}, timeout=12).json()
        except Exception:
            continue
        for tok in (h if isinstance(h, list) else []):
            for x in tok.get("holders", []):
                w = x.get("proxyWallet")
                if w:
                    cands.append((w, cid))
    _log(f"候选池（holders）：{len(cands)}")

    # ── 3. 随机抽样跑三检查 ──
    random.shuffle(cands)
    sample = cands[:55]
    cheap = []   # (cost, won) 已重建
    valid = 0; attempted_dec = 0; no_entry = 0; dec_fail = 0
    for w, cid in sample:
        res = res_cache[cid]
        pos = reconstruct(w, cid)
        if not pos or not pos["entry_time"]:
            no_entry += 1
            continue
        cost = pos["entry_price"] * pos["size"]
        won = (pos["outcome"] == res["winning_outcome"])
        cheap.append((cost, won))
        # 转化（含 decoder）：只对前 ~32 个有入场的跑 decoder，控成本
        if attempted_dec < 32:
            attempted_dec += 1
            news = get_news_for_market(pos["title"] or res["question"], pos["entry_time"], as_of=pos["entry_time"])
            if news.get("error"):
                dec_fail += 1; continue
            a = _assemble(pos, res, pos["entry_price"], news)   # 建仓时点 current≈entry
            try:
                _decode_retry(a, _date(pos["entry_time"]))
                valid += 1
            except DecoderError:
                dec_fail += 1

    N = len(sample)
    rec = len(cheap)
    over5k = sum(1 for c, _ in cheap if c > 5000)
    won_n = sum(1 for _, wn in cheap if wn); lost_n = rec - won_n
    print("\n" + "=" * 60)
    print(f"抽样候选 N={N}")
    print(f"① 转化率：尝试 decoder {attempted_dec} 个 → 有效 {valid}（无入场 {no_entry}，decoder失败 {dec_fail}）")
    print(f"   转化率 ≈ {valid}/{attempted_dec} = {valid/attempted_dec:.0%}（有入场的候选里）")
    print(f"② 美元门槛：已重建 {rec} 个 → cost>$5000 的 {over5k}（{over5k/rec:.0%}）")
    print(f"   （之前 ≥5000股 代理高估了；真实 >$5k 占比 {over5k/rec:.0%}）")
    print(f"③ holders 结局分布（偏差体检）：已重建 {rec} 个 → 持有获胜方(赢) {won_n} / 持有失败方(输) {lost_n}")
    print(f"   赢:输 = {won_n}:{lost_n} = {won_n/rec:.0%}:{lost_n/rec:.0%}")
    if rec:
        skew = "偏向输家（赢家已赎回离场？需警惕）" if lost_n > won_n * 1.5 else \
               ("偏向赢家" if won_n > lost_n * 1.5 else "大致均衡（含两种结局，对 lift 友好）")
        print(f"   → 判断：{skew}")
    print("=" * 60)


if __name__ == "__main__":
    main()
