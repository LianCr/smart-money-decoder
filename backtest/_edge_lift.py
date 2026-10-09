"""
backtest/_edge_lift.py — 硬盘 × 市场价基准：decoder 在"市场自己也拿不准"的盘上有没有真本事

和 _market_lift.py（路 A）的三处刻意不同：
  1. 只取模型训练截止之后的盘：建仓 ≥ ENTRY_MIN、结算在 [CLOSED_MIN, CLOSED_MAX]。
     老盘的结局模型可能"记得"，测出来的是记忆不是判断。
  2. 只取硬盘：建仓价在 [BAND_LO, BAND_HI]。近明牌盘赢了是送分，不进样本。
  3. 抽样对结局盲：每盘在合格买家里随机抽，不按输赢配额（路 A 输家全取会让"实际 vs 价格"失真）；
     也不要求"持到结算"——判的是"建仓那一刻跟这一边对不对"，离场与否无关，顺带去掉幸存者偏差。

打分 = 市场价基准（与 scorecard.price_baseline 同口径）：
  期望命中 = Σ 建仓价，实际命中 = 押的那边赢了几个；GO 子集超出期望才算判断的贡献。
  另给 Poisson-binomial 尾概率：只信价格的话，中这么多（或更多）的概率。

🔴 decoder 原样调用（红线 1：不为指标调松门槛）。烧 token：每样本 ~1 次 decoder + 1 次关键词 + 1 次 Tavily。
下划线前缀 = 内部诊断脚本。用法：python -m backtest._edge_lift [输出.jsonl]
"""
import json
import random
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

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


def _ts(s):
    return int(datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp())


ENTRY_MIN = _ts("2026-06-01")     # 建仓不早于此（模型截止之后）
CLOSED_MIN = _ts("2026-07-01")
CLOSED_MAX = _ts("2026-10-08")
BAND_LO, BAND_HI = 0.25, 0.75     # 硬盘：市场给的胜率在这个区间
MIN_COST = 5000                   # 建仓首日累计 ≥ $5k（聪明钱口径同路 A）
BIG_TRADE = 1000                  # data-api CASH 过滤：只拉单笔 ≥ $1k 的成交
ENTRY_WINDOW = 86400              # 首笔大单后 24h 内的买入算"建仓"
PER_MARKET = 3                    # 每盘最多抽几个（同盘样本相关，限量）
MARKETS_PER_EVENT = 2
TARGET_SAMPLES = 100              # 预算闸：成功 decode 这么多就停
MAX_DECODE_ATTEMPTS = 140         # 硬闸：含失败的 decoder 尝试上限
NOT_POLITICS = ("tweets", "elon musk", "gta vi")
random.seed(26)


def _log(m): print(m, file=sys.stderr, flush=True)


def _events():
    off = 0
    while off < 3000:
        try:
            evs = requests.get(f"{GAMMA}/events", params={
                "closed": "true", "order": "volume", "ascending": "false", "limit": 100, "offset": off,
                "end_date_min": "2026-06-25", "end_date_max": "2026-10-08"}, timeout=20).json()
        except Exception:
            off += 100; continue
        if not isinstance(evs, list):           # 偶发错误体（dict）——跳过这页，别把 key 当事件迭代
            off += 100; continue
        if not evs:
            return
        for e in evs:
            yield e
        off += 100


def _big_buys(cid):
    """单笔 ≥$1k 的成交（offset 上限 10000 由 API 定）。"""
    out, off = [], 0
    while off <= 9900:
        try:
            tr = requests.get(f"{DATA}/trades", params={"market": cid, "limit": 100, "offset": off,
                                                         "filterType": "CASH", "filterAmount": BIG_TRADE},
                              timeout=20).json()
        except Exception:
            break
        if not isinstance(tr, list) or not tr:
            break
        out += [x for x in tr if x.get("conditionId") == cid and x.get("side") == "BUY"]
        if len(tr) < 100:
            break
        off += 100
    return out


def _entries(cid, closed_ts):
    """(wallet,outcome) → 建仓首日仓位；只留硬盘价、够大、在截止之后的。"""
    by = defaultdict(list)
    for x in _big_buys(cid):
        if x.get("proxyWallet") and x.get("outcome") and x.get("timestamp"):
            by[(x["proxyWallet"].lower(), x["outcome"])].append(x)
    out = []
    for (w, oc), xs in by.items():
        xs.sort(key=lambda x: x["timestamp"])
        t0 = xs[0]["timestamp"]
        first = [x for x in xs if x["timestamp"] <= t0 + ENTRY_WINDOW]
        cost = sum(float(x["size"]) * float(x["price"]) for x in first)
        size = sum(float(x["size"]) for x in first)
        if size <= 0 or cost < MIN_COST:
            continue
        px = cost / size
        if not (BAND_LO <= px <= BAND_HI) or t0 < ENTRY_MIN or t0 > closed_ts - 86400:
            continue
        out.append({"wallet": w, "outcome": oc, "entry_price": round(px, 4), "size": size,
                    "token": first[0].get("asset"), "entry_time": t0, "title": first[0].get("title"),
                    "cost": round(cost)})
    return out


def _tail_prob(prices, k):
    """Poisson-binomial：各自按价格独立赢，至少赢 k 个的概率。"""
    dist = [1.0]
    for p in prices:
        nxt = [0.0] * (len(dist) + 1)
        for i, q in enumerate(dist):
            nxt[i] += q * (1 - p); nxt[i + 1] += q * p
        dist = nxt
    return sum(dist[k:])


def _summary(rows, label):
    if not rows:
        return f"  {label}: 0 个"
    prices = [r["entry_price"] for r in rows]
    hits = sum(r["won"] for r in rows); exp = sum(prices)
    return (f"  {label}: N={len(rows)} · 实际中 {hits} · 按价格预期 {exp:.1f} · 超出 {hits - exp:+.1f}"
            f" · 只信价格中≥{hits}个的概率 {_tail_prob(prices, hits):.0%}"
            f" · 涉及 {len({r['cid'] for r in rows})} 个盘")


def report(rows):
    go = [r for r in rows if r["go"]]; avoid = [r for r in rows if not r["go"]]
    print("=" * 72)
    print(f"硬盘 × 市场价基准（建仓价 {BAND_LO}–{BAND_HI} · 建仓≥2026-06-01 · 结算 07-01~10-08）")
    print(_summary(rows, "全部样本"))
    print(_summary(go, "GO（ROOM LEFT/CHASED）"))
    print(_summary(avoid, "躲（NO BASIS）"))
    for c in ("high", "medium", "low"):
        sub = [r for r in go if (r.get("conf") or "").lower().startswith(c[:3])]
        if sub:
            print(_summary(sub, f"GO·{c}"))
    print("真本事的样子：GO 超出 > 0 且尾概率小；躲 超出 ≤ 0。样本小时两者都可能是运气。")
    print("=" * 72)


def main():
    if "--report" in sys.argv:
        out = Path(next((a for a in sys.argv[1:] if not a.startswith("--")), "backtest/edge_lift_samples.jsonl"))
        report([json.loads(l) for l in out.read_text().splitlines()]); return
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "backtest/edge_lift_samples.jsonl")
    rows = [json.loads(l) for l in out.read_text().splitlines()] if out.exists() else []
    done = {(r["cid"], r["wallet"], r["outcome"]) for r in rows}
    seen_cid = {r["cid"] for r in rows}
    attempts = 0
    for e in _events():
        if len(rows) >= TARGET_SAMPLES or attempts >= MAX_DECODE_ATTEMPTS:
            break
        title = (e.get("title") or "").lower()
        if not _is_political_event(e) or any(k in title for k in NOT_POLITICS):
            continue
        mkts = sorted([m for m in (e.get("markets") or []) if m.get("closed") and m.get("conditionId")],
                      key=lambda m: -float(m.get("volume") or 0))[:MARKETS_PER_EVENT]
        for m in mkts:
            if len(rows) >= TARGET_SAMPLES or attempts >= MAX_DECODE_ATTEMPTS:
                break
            cid = m["conditionId"]
            try:
                res = get_market_resolution(cid)
            except Exception:
                continue
            if not res or not res.get("winning_outcome"):
                continue
            if not (CLOSED_MIN <= (res.get("resolved_time") or 0) <= CLOSED_MAX):
                continue
            cands = [p for p in _entries(cid, res["resolved_time"])
                     if (cid, p["wallet"], p["outcome"]) not in done]
            already = sum(1 for r in rows if r["cid"] == cid)
            random.shuffle(cands)                       # 🔴 对结局盲：随机抽，不看输赢
            got = 0
            for pos in cands[:max(0, PER_MARKET - already)]:
                if attempts >= MAX_DECODE_ATTEMPTS or len(rows) >= TARGET_SAMPLES:
                    break
                attempts += 1
                try:
                    news = get_news_for_market(pos["title"] or res["question"], pos["entry_time"],
                                               as_of=pos["entry_time"])
                    if news.get("error"):
                        continue
                    a = _assemble(pos, res, pos["entry_price"], news)
                    card = _decode_retry(a, _date(pos["entry_time"]))
                except (DecoderError, Exception) as ex:
                    _log(f"    跳过 decode（{type(ex).__name__}）"); continue
                r = {"cid": cid, "question": res["question"], "wallet": pos["wallet"],
                     "outcome": pos["outcome"], "winner": res["winning_outcome"],
                     "won": pos["outcome"] == res["winning_outcome"], "entry_price": pos["entry_price"],
                     "cost": pos["cost"], "entry_date": _date(pos["entry_time"]),
                     "fc": card["follow_call"], "conf": card.get("confidence"),
                     "go": card["follow_call"] in ENDORSE, "n_articles": len(news.get("articles") or [])}
                rows.append(r); done.add((cid, r["wallet"], r["outcome"])); got += 1
                with out.open("a") as f:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            if got:
                seen_cid.add(cid)
                _log(f"  {res['question'][:48]:48} | +{got} | 累计 {len(rows)} 样本 · decoder 尝试 {attempts}")
    report(rows)


if __name__ == "__main__":
    main()
