"""
backtest/_market_lift.py — v2 结算：市场优先 B 取样 + 建仓时点 lift（路 A）

口径（路 A · 带 caveat）：
  - 取样：可翻页中量政治盘 → /trades 全成交两侧重建「持到结算」的买家（赢家+输家，同机制）
    → 滤 >$5k（聪明钱）。输家是瓶颈，全取；赢家每盘限量，凑尽量平衡。
  - 时点：建仓时点（current_price≈entry_price，news as_of=entry_time，#7 无泄漏）。
  - 输赢：结算结果（持有侧==winner）。
  - lift = GO 子集（decoder 在建仓时点判 ROOM LEFT/CHASED）方向胜率 − 全集方向胜率。

⚠️ caveat（必须随 lift 一起报）：
  ① 样本仅含「持到结算者」，系统性排除了提前离场的聪明钱（赢了赎回 / 输了割肉）——可能不典型。
  ② 聪明钱罕少持大额输盘到结算，>$5k 输家是过采的稀有滞留者，代表性有限。
  → 正确口径是「离场盈亏」(v3/#25)，路 A 是 v2 收尾的务实退路。

下划线前缀 = 内部诊断脚本。
"""
import random
import sys
from collections import defaultdict

import requests
from dotenv import load_dotenv
load_dotenv()

from fetcher.polymarket import _is_political_event
from fetcher.news import get_news_for_market
from analyzer.decoder import DecoderError
from backtest.resolution import get_market_resolution
from backtest.pipeline import _assemble, _date, _decode_retry, ENDORSE

GAMMA = "https://gamma-api.polymarket.com"
DATA = "https://data-api.polymarket.com"
MIN_COST = 5000
TARGET_LOSERS = 15        # 输家瓶颈，收够即停
WINNERS_PER_MKT = 4       # 每盘赢家限量（控 decoder 调用 + 保平衡）
MAX_TRADE_PAGES = 200
CONF = {"high", "low"}
random.seed(11)


def _log(m): print(m, file=sys.stderr, flush=True)


def reconstruct_all(cid):
    """全成交 → {(wallet,outcome):{cost,buy_sz,sell_sz,min_ts,asset,title}}, capped。"""
    agg = defaultdict(lambda: {"cost": 0.0, "buy_sz": 0.0, "sell_sz": 0.0, "min_ts": None, "asset": None, "title": None})
    off = 0; capped = False
    while off < MAX_TRADE_PAGES * 100:
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
            sz = float(x.get("size") or 0); pr = float(x.get("price") or 0); ts = x.get("timestamp")
            d = agg[(w, oc)]
            if x.get("side") == "BUY":
                d["cost"] += sz * pr; d["buy_sz"] += sz
                d["asset"] = d["asset"] or x.get("asset")
                d["min_ts"] = ts if d["min_ts"] is None else min(d["min_ts"], ts)
                d["title"] = x.get("title") or d["title"]
            elif x.get("side") == "SELL":
                d["sell_sz"] += sz
        if len(tr) < 100:
            break
        off += 100
    else:
        capped = True
    return agg, capped


def decode_at_entry(pos, res):
    news = get_news_for_market(pos["title"] or res["question"], pos["entry_time"], as_of=pos["entry_time"])
    if news.get("error"):
        return None
    a = _assemble(pos, res, pos["entry_price"], news)   # 建仓时点 current≈entry
    try:
        card = _decode_retry(a, _date(pos["entry_time"]))
    except DecoderError:
        return None
    return card["follow_call"], card["confidence"]


def main():
    samples = []          # {won, go, conf, fc, mkt}
    losers = 0; seen = set(); examined_mkts = 0
    for off in (1900, 2400, 3000, 3600, 4200, 4800, 5400, 6000):
        if losers >= TARGET_LOSERS:
            break
        try:
            evs = requests.get(f"{GAMMA}/events", params={"closed": "true", "order": "volume", "ascending": "false", "limit": 70, "offset": off}, timeout=15).json()
        except Exception:
            continue
        for e in (evs if isinstance(evs, list) else []):
            if losers >= TARGET_LOSERS:
                break
            if not _is_political_event(e) or e.get("title") in seen:
                continue
            v = float(e.get("volume") or 0)
            if not (80_000 <= v <= 3_000_000):
                continue
            seen.add(e.get("title"))
            cid = None
            for m in (e.get("markets") or []):
                if m.get("conditionId") and m.get("closed"):
                    cid = m["conditionId"]; break
            if not cid:
                continue
            try:
                res = get_market_resolution(cid)
                if not res or not res.get("winning_outcome"):
                    continue
                winner = res["winning_outcome"]
                agg, capped = reconstruct_all(cid)
                if capped:
                    continue
                wins_c, loses_c = [], []
                for (w, oc), d in agg.items():
                    if (d["buy_sz"] - d["sell_sz"]) > 1 and d["cost"] > MIN_COST and d["min_ts"] and d["asset"] and d["buy_sz"] > 0:
                        pos = {"outcome": oc, "entry_price": round(d["cost"] / d["buy_sz"], 4),
                               "size": d["buy_sz"], "token": d["asset"], "entry_time": d["min_ts"], "title": d["title"]}
                        (wins_c if oc == winner else loses_c).append(pos)
                if not loses_c and not wins_c:
                    continue
                random.shuffle(wins_c)
                pick = loses_c + wins_c[:WINNERS_PER_MKT]   # 输家全取，赢家限量
                got = 0
                for pos in pick:
                    r = decode_at_entry(pos, res)
                    if r is None:
                        continue
                    fc, conf = r
                    won = (pos["outcome"] == winner)
                    samples.append({"won": won, "go": fc in ENDORSE, "conf": conf, "fc": fc,
                                    "entry": pos["entry_price"], "mkt": e.get("title", "")[:26]})
                    if not won:
                        losers += 1
                    got += 1
                examined_mkts += 1
                _log(f"  {e.get('title','')[:30]:30} | 该盘取 {got}（输{len(loses_c)}/赢{min(len(wins_c),WINNERS_PER_MKT)}）| 累计输家 {losers}")
            except Exception as ex:
                _log(f"  跳过（{type(ex).__name__}）"); continue

    # ── lift 计算 ──
    N = len(samples)
    if N == 0:
        print("无样本"); return
    full_w = sum(s["won"] for s in samples)
    go = [s for s in samples if s["go"]]
    avoid = [s for s in samples if not s["go"]]
    go_w = sum(s["won"] for s in go)
    full_wr = full_w / N
    go_wr = (go_w / len(go)) if go else None
    avoid_wr = (sum(s["won"] for s in avoid) / len(avoid)) if avoid else None
    print("\n" + "=" * 64)
    print(f"v2 第一版 lift（路 A · 结算输赢 · 建仓时点 · {examined_mkts} 盘）")
    print(f"样本 N={N}  |  赢 {full_w} / 输 {N-full_w}  |  全集方向胜率 {full_wr:.0%}")
    print(f"decoder 建仓时点：GO(跟) {len(go)} / 躲 {len(avoid)}")
    if go:
        print(f"  GO 子集方向胜率 {go_wr:.0%}（{go_w}/{len(go)}）")
    if avoid is not None and avoid:
        print(f"  躲 子集方向胜率 {avoid_wr:.0%}（{sum(s['won'] for s in avoid)}/{len(avoid)}）")
    if go:
        print(f"  >>> LIFT = GO胜率 − 全集胜率 = {go_wr:.0%} − {full_wr:.0%} = {go_wr-full_wr:+.0%}")
    # 信心校准
    for c in ("high", "low"):
        sub = [s for s in go if s["conf"] == c]
        if sub:
            print(f"  GO·{c}信心：胜率 {sum(s['won'] for s in sub)/len(sub):.0%}（{sum(s['won'] for s in sub)}/{len(sub)}）")
    # 价格分布（暴露近明牌污染）
    nearmoney = [s for s in samples if s["entry"] >= 0.90 or s["entry"] <= 0.10]
    nm_w = sum(s["won"] for s in nearmoney)
    print(f"  近明牌样本（entry≥0.90 或 ≤0.10）：{len(nearmoney)}/{N}，其中赢 {nm_w}"
          + (f"，胜率 {nm_w/len(nearmoney):.0%}（几乎全 NO BASIS、抬高全集基线）" if nearmoney else ""))
    # ── edge-band 切片：只看有 edge 空间的中段价（decoder 的 GO 才真在判别 edge）──
    band = [s for s in samples if 0.10 < s["entry"] < 0.90]
    if band:
        b_w = sum(s["won"] for s in band); b_wr = b_w / len(band)
        bgo = [s for s in band if s["go"]]
        bgo_wr = (sum(s["won"] for s in bgo) / len(bgo)) if bgo else None
        print("-" * 64)
        print(f"【edge-band 切片 0.10<entry<0.90 · N={len(band)}】剔除近明牌后，GO 才真在判 edge：")
        print(f"  全集胜率 {b_wr:.0%}（{b_w}/{len(band)}）| GO {len(bgo)} 个"
              + (f"，胜率 {bgo_wr:.0%}（{sum(s['won'] for s in bgo)}/{len(bgo)}）→ LIFT {bgo_wr-b_wr:+.0%}" if bgo else "（无 GO）"))
    print("-" * 64)
    print("⚠️ CAVEAT（随 lift 一起报，不可省）：")
    print("  ① 样本仅含『持到结算者』，系统性排除提前离场的聪明钱（赢赎回/输割肉）——可能不典型。")
    print("  ② 聪明钱罕少持大额输盘到结算，>$5k 输家是过采的稀有滞留者，代表性有限。")
    print("  ③ 方向胜率对 edge 盲：近明牌(≥0.90)赢家胜率近 100% 但 ~0 回报，decoder 正确判 NO BASIS")
    print("     却被记为『漏掉赢家』→ 拉低 lift。低/负 lift 可能是 decoder 正确回避零 edge，而非失手。")
    print("     → 看 edge-band 切片更公允；真口径是『离场盈亏』(v3/#25/#26)。")
    print("  ④ 本数为 v2 务实退路，回答『decoder 判断力是否成立』，非『跟它能赚多少』。")
    print("=" * 64)


if __name__ == "__main__":
    main()
