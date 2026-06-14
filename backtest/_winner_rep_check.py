"""
backtest/_winner_rep_check.py — 赢家侧代表性体检（诊断，非生产）

回答一个数：A 取样里「未赎回的赢家」（留在 /holders 榜上）和「已赎回的赢家」（押对、持到
结算、但已赎回离场）在**仓位大小**上差多少？
  - 差小 → A 的二阶瑕疵可忽略，放心用 A（保住高量盘红利）。
  - 差大 → /holders 赢家侧系统性偏小/偏怪，会咬 lift 的分子，需对赢家侧补 B。

识别（用单盘全成交 + /holders）：
  winning 侧买家（trade.outcome==winner & BUY）→ 按钱包聚合 净winning股 = buy - sell。
  净>0（持到结算的真赢家）里：
    在 /holders winning token 榜 → 「未赎回」
    不在榜（有净仓却不在持仓快照）→ 「已赎回离场」
  比两组的 BUY 成本（usdc）分布。

只挑能「全量翻完」的中量盘（翻页到底、未触 cap），高量盘翻不动则跳过并标注。
下划线前缀 = 内部诊断，可删。
"""
import sys
from collections import defaultdict
from statistics import median, mean

import requests
from dotenv import load_dotenv
load_dotenv()

from fetcher.polymarket import _is_political_event
from backtest.resolution import get_market_resolution

GAMMA = "https://gamma-api.polymarket.com"
DATA = "https://data-api.polymarket.com"
MAX_PAGES = 150   # 15000 笔封顶；超过=高量盘，翻不全则跳过


def _log(m): print(m, file=sys.stderr, flush=True)


def winning_buyers(cid, winner):
    """全成交聚合 winning 侧：{wallet:{cost,buy_sz,sell_sz}}, winning_token_asset, capped。"""
    agg = defaultdict(lambda: {"cost": 0.0, "buy_sz": 0.0, "sell_sz": 0.0})
    wtok = None; off = 0; capped = False
    while off < MAX_PAGES * 100:
        try:
            tr = requests.get(f"{DATA}/trades", params={"market": cid, "limit": 100, "offset": off}, timeout=12).json()
        except Exception:
            break
        if not isinstance(tr, list) or not tr:
            break
        for x in tr:
            if x.get("conditionId") != cid:      # 安全：防 market 过滤不严混入别盘
                continue
            if x.get("outcome") != winner:
                continue
            w = x.get("proxyWallet"); sz = float(x.get("size") or 0)
            pr = float(x.get("price") or 0)
            if not w:
                continue
            wtok = wtok or x.get("asset")
            if x.get("side") == "BUY":
                agg[w]["cost"] += sz * pr; agg[w]["buy_sz"] += sz   # usdcSize 常为 None，用 size×price
            elif x.get("side") == "SELL":
                agg[w]["sell_sz"] += sz
        if len(tr) < 100:
            break
        off += 100
    else:
        capped = True
    return agg, wtok, capped


def main():
    # 中量盘在更深的排名（量太高翻不全）。扫多个深 offset 找 volume∈[80k,3M] 的政治盘。
    seeds = []
    seen = set()
    for off in (700, 1100, 1500, 1900, 2400, 3000):
        if len(seeds) >= 12:
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
                cid = m.get("conditionId")
                if cid and m.get("closed"):
                    seeds.append((cid, e.get("title", "")[:34], v)); seen.add(e.get("title")); break
    _log(f"中量政治盘候选：{len(seeds)}")

    all_unre = []; all_red = []
    done = 0
    for cid, t, v in seeds:
        if done >= 5:
            break
        try:
            res = get_market_resolution(cid)
            if not res:
                continue
            winner = res["winning_outcome"]
            agg, wtok, capped = winning_buyers(cid, winner)
            if capped or not agg or not wtok:
                _log(f"  跳过 {t}（{'量太大翻不全' if capped else '无 winning 成交'}）"); continue
            h = requests.get(f"{DATA}/holders", params={"market": cid, "limit": 500}, timeout=12).json()
            U = set()
            for tok in (h if isinstance(h, list) else []):
                if tok.get("token") == wtok:
                    U = {x.get("proxyWallet") for x in tok.get("holders", [])}
            # 净 winning 股 > 0 = 持到结算的真赢家
            unre = [d["cost"] for w, d in agg.items() if (d["buy_sz"] - d["sell_sz"]) > 1 and w in U and d["cost"] > 0]
            red  = [d["cost"] for w, d in agg.items() if (d["buy_sz"] - d["sell_sz"]) > 1 and w not in U and d["cost"] > 0]
            if len(unre) < 3 or len(red) < 3:
                _log(f"  跳过 {t}（赢家分组太少 unre{len(unre)}/red{len(red)}）"); continue
            all_unre += unre; all_red += red
            done += 1
            _log(f"  {t:34} vol={v:>11,.0f} | 未赎回赢家 {len(unre)}(中位${median(unre):,.0f}) "
                 f"| 已赎回赢家 {len(red)}(中位${median(red):,.0f})")
        except Exception as e:
            _log(f"  跳过 {t}（{type(e).__name__}）"); continue

    print("\n" + "=" * 60)
    if all_unre and all_red:
        mu, mr = median(all_unre), median(all_red)
        print(f"汇总（{done} 个中量盘）：")
        print(f"  未赎回赢家 N={len(all_unre)}  仓位中位 ${mu:,.0f}  均值 ${mean(all_unre):,.0f}")
        print(f"  已赎回赢家 N={len(all_red)}  仓位中位 ${mr:,.0f}  均值 ${mean(all_red):,.0f}")
        ratio = mr / mu if mu else 0
        print(f"  已赎回/未赎回 中位倍数 = {ratio:.1f}x")
        verdict = "差大（赢家侧偏小、big winner 已离场→A 会咬 lift，赢家侧需补 B）" if ratio >= 2 else \
                  "差小（二阶瑕疵可忽略，A 够用）" if ratio <= 1.5 else "中等（边界，谨慎用 A + 标注）"
        print(f"  → 判断：{verdict}")
    else:
        print("有效中量盘不足，无法判断（可能候选都翻不动 / 分组太少）")
    print("=" * 60)


if __name__ == "__main__":
    main()
