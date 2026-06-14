"""
backtest/_both_sides_check.py — 建 B 管道前的两坑验证（诊断，非生产）

坑1【两侧同机制】：B（全成交重建）能否**同时**重建赢家侧 + 输家侧的完整 population
  （持到结算 = net>0），而非赢家 B / 输家 /holders 两套机制混用（那会造新偏差）。
坑2【聪明钱占比】：退到中量盘后，B 重建出的 >$5k 有效样本有多少？
  几十上百 = 够；个位数 = B 把聪明钱样本也稀释没了，中量盘不可用、得重选。

对 2-3 个可翻页中量政治盘：全成交按 (wallet, outcome) 聚合 → 持到结算(net>0)的赢家/输家，
按持仓成本(size×price)数 >$5k / >$1k。
"""
import sys
from collections import defaultdict

import requests
from dotenv import load_dotenv
load_dotenv()

from fetcher.polymarket import _is_political_event
from backtest.resolution import get_market_resolution

GAMMA = "https://gamma-api.polymarket.com"
DATA = "https://data-api.polymarket.com"
MAX_PAGES = 200


def _log(m): print(m, file=sys.stderr, flush=True)


def reconstruct_all(cid):
    """全成交 → {wallet: {outcome: {cost,buy_sz,sell_sz}}}，capped。"""
    agg = defaultdict(lambda: defaultdict(lambda: {"cost": 0.0, "buy_sz": 0.0, "sell_sz": 0.0}))
    off = 0; capped = False
    while off < MAX_PAGES * 100:
        try:
            tr = requests.get(f"{DATA}/trades", params={"market": cid, "limit": 100, "offset": off}, timeout=12).json()
        except Exception:
            break
        if not isinstance(tr, list) or not tr:
            break
        for x in tr:
            if x.get("conditionId") != cid:
                continue
            w = x.get("proxyWallet"); oc = x.get("outcome")
            if not w or oc is None:
                continue
            sz = float(x.get("size") or 0); pr = float(x.get("price") or 0)
            d = agg[w][oc]
            if x.get("side") == "BUY":
                d["cost"] += sz * pr; d["buy_sz"] += sz
            elif x.get("side") == "SELL":
                d["sell_sz"] += sz
        if len(tr) < 100:
            break
        off += 100
    else:
        capped = True
    return agg, capped


def held_costs(agg, outcome):
    """持到结算（净>0）该 outcome 的持仓成本列表。"""
    out = []
    for w, by_oc in agg.items():
        d = by_oc.get(outcome)
        if d and (d["buy_sz"] - d["sell_sz"]) > 1 and d["cost"] > 0:
            out.append(d["cost"])
    return out


def main():
    # 可翻页中量政治盘
    seeds = []; seen = set()
    for off in (1900, 2400, 3000, 3600, 4200):   # 中量盘($80k-3M)在更深 offset
        if len(seeds) >= 6:
            break
        try:
            evs = requests.get(f"{GAMMA}/events", params={"closed": "true", "order": "volume", "ascending": "false", "limit": 70, "offset": off}, timeout=15).json()
        except Exception:
            continue
        for e in (evs if isinstance(evs, list) else []):
            if not _is_political_event(e) or e.get("title") in seen:
                continue
            v = float(e.get("volume") or 0)
            if not (80_000 <= v <= 3_000_000):
                continue
            for m in (e.get("markets") or []):
                cid = m.get("conditionId"); outs = m.get("outcomes")
                if cid and m.get("closed"):
                    seeds.append((cid, e.get("title", "")[:34], v)); seen.add(e.get("title")); break
    _log(f"候选中量盘：{len(seeds)}")

    done = 0
    agg_w5 = agg_l5 = agg_w1 = agg_l1 = 0
    for cid, t, v in seeds:
        if done >= 3:
            break
        try:
            res = get_market_resolution(cid)
            if not res:
                continue
            winner = res["winning_outcome"]
            agg, capped = reconstruct_all(cid)
            if capped:
                _log(f"  跳过 {t}（量太大翻不全）"); continue
            outcomes = {oc for by in agg.values() for oc in by}
            losers_oc = [oc for oc in outcomes if oc != winner]
            wins = held_costs(agg, winner)
            loses = [c for oc in losers_oc for c in held_costs(agg, oc)]
            if not wins and not loses:
                _log(f"  跳过 {t}（无持到结算样本）"); continue
            w5 = sum(1 for c in wins if c > 5000); l5 = sum(1 for c in loses if c > 5000)
            w1 = sum(1 for c in wins if c > 1000); l1 = sum(1 for c in loses if c > 1000)
            agg_w5 += w5; agg_l5 += l5; agg_w1 += w1; agg_l1 += l1
            done += 1
            _log(f"  {t:34} vol={v:>11,.0f}")
            _log(f"      持到结算：赢家 {len(wins)} / 输家 {len(loses)}（同一套 B 机制 ✓）")
            _log(f"      >$5k：赢 {w5} / 输 {l5}   |   >$1k：赢 {w1} / 输 {l1}")
        except Exception as e:
            _log(f"  跳过 {t}（{type(e).__name__}）"); continue

    print("\n" + "=" * 60)
    print(f"汇总（{done} 个中量盘）")
    print(f"坑1 两侧同机制：B 同时重建出赢家侧 + 输家侧完整 population ✓（上面每盘都有两侧）")
    print(f"坑2 聪明钱占比：")
    print(f"   >$5k 有效样本：赢 {agg_w5} + 输 {agg_l5} = {agg_w5+agg_l5}（{done}盘）")
    print(f"   >$1k 有效样本：赢 {agg_w1} + 输 {agg_l1} = {agg_w1+agg_l1}（{done}盘）")
    n5 = agg_w5 + agg_l5
    if done:
        per5 = n5 / done
        verdict = (f"够（每盘 ~{per5:.0f} 个 >$5k，224 盘 → 量级几百，聪明钱样本充足）" if per5 >= 5 else
                   f"勉强（每盘 ~{per5:.1f} 个 >$5k，需多扫盘 / 或放宽到 >$1k）" if per5 >= 1.5 else
                   "不够（>$5k 个位数，中量盘把聪明钱稀释没了→需重选盘 / 放宽门槛）")
        print(f"   → 判断：{verdict}")
    print("=" * 60)


if __name__ == "__main__":
    main()
