"""
backtest/pipeline.py — 回测第三块砖：T-7/T-1 历史快照 + 重放 decoder → 聚合 /backtest

流程（离线预算，结果写 .cache/backtest/result.json，由 GET /backtest 读取）：
  1. fetch_full_activity 翻钱包全活动 → 按 conditionId 聚合 BUY，定出每个市场的
     「持有侧 / 入场均价 / 仓位 / outcome token / 最早建仓时间」。
  2. 对每个市场 get_market_resolution → 拿到 winner + 实际结算时间 rt（None 则跳过）。
  3. 赢输 = 持有侧 == winner（**赢输都纳入**，避免只测 REDEEM 导致全是赢、看不到失手）。
  4. T-7 = rt-7d、T-1 = rt-1d，各取 CLOB 历史价（任一缺失=短命市场，跳过）。
  5. 新闻锚定真实 entry_time（两时点共用，省一半新闻调用）；两时点各按当时价重放 decoder。
  6. hit = (T-1 的 follow_call 背书) 与 (该仓最终赢) 是否一致。
  7. 聚合 overview（方向命中 / 高低信心校准 / 赢输构成），写文件。

成本：每个有效样本 = 1 次新闻 + 2 次 decoder。故 max_samples 控制规模、离线跑。
政治过滤暂放宽（gamma 市场不带 tags；该钱包本就政治盘为主，v1 注明）。
"""

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from fetcher.news import get_news_for_market
from fetcher.polymarket import fetch_events_by_ids, _is_political_event
from analyzer.decoder import decode_position, DecoderError
from backtest.full_activity import fetch_full_activity
from backtest.resolution import get_market_resolution
from backtest.snapshot import get_price_at

load_dotenv()

RESULT_PATH = Path(".cache/backtest/result.json")
ENDORSE     = {"ROOM LEFT", "CHASED"}   # decoder 背书「值得跟」的两档


def _log(m):
    print(m, file=sys.stderr, flush=True)


def _is_political(event_id: str | None) -> bool:
    """复用 polymarket 的政治判定：gamma /events?id= 拿 tags 过 _is_political_event。"""
    if not event_id:
        return False
    try:
        emap = fetch_events_by_ids([event_id])
        return _is_political_event(emap.get(event_id, {}))
    except Exception:
        return False


def _date(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def _iso(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if ts else None


# ── 从全活动重建每个市场的持有侧仓位 ─────────────────────────────────────────
def _reconstruct_positions(records: list[dict]) -> dict:
    """
    conditionId → {outcome, entry_price, size, token, entry_time, title}。
    持有侧 = 该市场 BUY 总 size 最大的 outcome；entry_price = 该侧 BUY 的 size 加权均价。
    """
    by = defaultdict(lambda: defaultdict(lambda: {
        "cost": 0.0, "size": 0.0, "asset": None, "min_ts": None, "title": None,
    }))
    for x in records:
        if not isinstance(x, dict) or x.get("type") != "TRADE" or x.get("side") != "BUY":
            continue
        cid, oc = x.get("conditionId"), x.get("outcome")
        if not cid or oc is None:
            continue
        sz = float(x.get("size") or 0); pr = float(x.get("price") or 0); ts = x.get("timestamp")
        d = by[cid][oc]
        d["cost"] += sz * pr; d["size"] += sz
        d["asset"] = d["asset"] or x.get("asset")
        d["min_ts"] = ts if d["min_ts"] is None else min(d["min_ts"], ts)
        d["title"] = x.get("title") or d["title"]

    out = {}
    for cid, sides in by.items():
        oc, d = max(sides.items(), key=lambda kv: kv[1]["size"])
        if d["size"] <= 0:
            continue
        out[cid] = {
            "outcome": oc,
            "entry_price": round(d["cost"] / d["size"], 4),
            "size": d["size"],
            "token": d["asset"],
            "entry_time": d["min_ts"],
            "title": d["title"],
        }
    return out


def _assemble(pos, res, current_price, news):
    """组装 decoder 输入契约（resolution_criteria 暂 None）。"""
    entry, size = pos["entry_price"], pos["size"]
    return {
        "market_question":     pos["title"] or res["question"],
        "outcome":             pos["outcome"],
        "entry_price":         entry,
        "current_price":       round(current_price, 4),
        "position_value":      round(size * current_price, 2),
        "pnl_pct":             round((current_price - entry) / entry * 100, 4) if entry else None,
        "cash_pnl":            round(size * (current_price - entry), 2),
        "resolution_criteria": None,
        "resolution_date":     _iso(res.get("scheduled_end")),
        "entry_time":          pos["entry_time"],
        "articles":            news["articles"],
        "time_anchored":       news["time_anchored"],
        "search_query":        news["search_query"],
    }


def _decode_retry(assembled, as_of, tries=3):
    """重放 decoder，传快照日 as_of；守卫偶发命中（DURATION/JSON）时重试，模型随机性常能过。"""
    last = None
    for _ in range(tries):
        try:
            return decode_position(assembled, as_of=as_of)
        except DecoderError as e:
            last = e
    raise last


def _front_card(assembled, decoder_card):
    """合成前端 Card 形（decoder 输出 + 代码直填 price_info + 市场元信息）。"""
    return {
        "market_question": assembled["market_question"],
        "outcome":         assembled["outcome"],
        "resolution_date": assembled["resolution_date"],
        "time_anchored":   assembled["time_anchored"],
        "price_info": {
            "entry_price":    assembled["entry_price"],
            "current_price":  assembled["current_price"],
            "position_value": assembled["position_value"],
            "cash_pnl":       assembled["cash_pnl"],
            "pnl_pct":        assembled["pnl_pct"],
        },
        "what_bet":      decoder_card.get("what_bet"),
        "catalyst":      decoder_card.get("catalyst", []),
        "edge_analysis": decoder_card.get("edge_analysis"),
        "follow_call":   decoder_card.get("follow_call"),
        "confidence":    decoder_card.get("confidence"),
        "reasoning":     decoder_card.get("reasoning"),
        "warnings":      decoder_card.get("warnings", []),
    }


def _overview(samples):
    def rate(subset):
        return {"hits": sum(1 for s in subset if s["hit"]), "total": len(subset)}
    hi = [s for s in samples if s["t1_card"]["confidence"] == "high"]
    lo = [s for s in samples if s["t1_card"]["confidence"] == "low"]
    return {
        "directional": rate(samples),
        "high_conf":   rate(hi),
        "low_conf":    rate(lo),
        "composition": {
            "profitable": sum(1 for s in samples if s["bet_won"]),
            "loss":       sum(1 for s in samples if not s["bet_won"]),
        },
    }


def run_backtest(wallet: str, max_samples: int = 6, min_cost: float = 1000.0) -> dict:
    _log(f"① 翻全活动 {wallet[:12]}…")
    records = fetch_full_activity(wallet)
    positions = _reconstruct_positions(records)
    _log(f"   重建 {len(positions)} 个市场仓位，开始逐个回测（目标 {max_samples} 个有效样本）")

    samples = []
    examined = 0
    for cid, pos in positions.items():
        if len(samples) >= max_samples or examined >= 200:
            break
        if not pos["token"] or not pos["entry_time"]:
            continue
        if pos["entry_price"] * pos["size"] < min_cost:
            continue
        examined += 1

        res = get_market_resolution(cid)
        if not res or not res.get("resolved_time"):
            continue
        rt = res["resolved_time"]; t7 = rt - 7 * 86400; t1 = rt - 1 * 86400
        p7 = get_price_at(pos["token"], t7); p1 = get_price_at(pos["token"], t1)
        if p7 is None or p1 is None:
            continue  # 短命市场，T-7/T-1 历史价不全，跳过

        if not _is_political(res.get("event_id")):
            continue  # 只回测政治盘（剔除体育/加密），与工具定位一致

        news = get_news_for_market(pos["title"] or res["question"], pos["entry_time"])
        if news.get("error"):
            continue

        winner = res["winning_outcome"]; bet_won = (pos["outcome"] == winner)
        try:
            a7 = _assemble(pos, res, p7, news); c7 = _decode_retry(a7, _date(t7))
            a1 = _assemble(pos, res, p1, news); c1 = _decode_retry(a1, _date(t1))
        except DecoderError as e:
            _log(f"   ⚠️ {(pos['title'] or '')[:30]} decoder 抛 {e.reason}（重试后仍失败），跳过")
            continue

        t7c = _front_card(a7, c7); t1c = _front_card(a1, c1)
        endorsed = t1c["follow_call"] in ENDORSE
        hit = (endorsed == bet_won)
        samples.append({
            "market_question": res["question"] or pos["title"],
            "resolved_outcome": (winner or "").upper(),
            "resolved_date": _date(rt),
            "t7_date": _date(t7), "t1_date": _date(t1),
            "t7_card": t7c, "t1_card": t1c,
            "hit": hit, "bet_won": bet_won,
        })
        _log(f"   ✓ [{len(samples)}] {res['question'][:36]} | 持{pos['outcome']} winner={winner} "
             f"{'赢' if bet_won else '输'} | T-1 {t1c['follow_call']} → {'命中' if hit else '失手'}")

    result = {"_mock": False, "wallet": wallet, "overview": _overview(samples), "samples": samples}
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    _log(f"\n完成：{len(samples)} 个样本，写入 {RESULT_PATH}")
    _log(f"overview: {json.dumps(result['overview'], ensure_ascii=False)}")
    return result


if __name__ == "__main__":
    w = sys.argv[1] if len(sys.argv) > 1 else "0x7c3db723f1d4d8cb9c550095203b686cb11e5c6b"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    run_backtest(w, max_samples=n)
