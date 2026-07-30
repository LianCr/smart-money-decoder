"""
scorecard.py — 诚实记分牌（decode / board 判断的自我验证）

这是产品唯一能回答"我的判断后来被现实证明对了多少"的机制。

🔴 三条灵魂红线（落进代码，任何改动不许越）：
  1. 顶上是「判断方向命中率」，**永不算「跟单收益率」**（不碰任何 $ 收益，那是假精确诱导跟单）。
  2. NO BASIS **不计入命中率**分子分母，单独统计。
  3. compute_scorecard() **纯代码冷数字**，不调任何 AI、不让 AI 评价自己的成绩。

从装上这一刻往后累积：第一天空、之前的判断已丢不可重现（**绝不造假回填**）。
存档=代码、抓结算由调用方注入 resolver(cid)（api 层用 574，免费）→ ~0 token。
不碰封板模块：record 钩子在 api 层调；结算用注入的 resolver，本模块不直接依赖 heisenberg。
"""
import json
import threading
import time
from pathlib import Path

ARCHIVE = Path(".data/scorecard.json")
# 🔒 档案写锁：推荐榜 ai_verify 并行后，多条看板 pipeline 会并发 record_judgment——
# "读档→改→写档"没有锁会互相覆盖丢记录（判断存档是记分牌的地基，丢一条就是假账）
_LOCK = threading.Lock()
ENDORSED = {"ROOM LEFT", "CHASED"}     # 这两个 = AI 背书该方向；NO BASIS = 不背书（单列）


def _load() -> dict:
    if ARCHIVE.exists():
        try:
            return json.loads(ARCHIVE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save(d: dict) -> None:
    try:
        ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
        ARCHIVE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def record_judgment(*, wallet, cid, market_question, outcome, market_price,
                    follow_call, confidence, source, settle_date=None) -> None:
    """decode/board 出 follow_call 时调（best-effort，绝不抛错阻塞上游）。
    key=(钱包,仓,来源)：重复 decode 更新同一条、不灌水；**已结算条不覆盖 final_result**。"""
    if not wallet or not cid or not follow_call:
        return
    try:
        with _LOCK:
            d = _load()
            key = f"{wallet.lower()}_{cid}_{source}"
            prev = d.get(key, {})
            d[key] = {
                "wallet": wallet, "cid": cid, "market_question": market_question,
                "outcome": outcome, "market_price": market_price,
                "follow_call": follow_call, "confidence": confidence, "source": source,
                "decided_at": prev.get("decided_at") or int(time.time()),
                "updated_at": int(time.time()), "settle_date": settle_date,
                "final_result": prev.get("final_result"),     # 已结算不覆盖（结果是历史事实）
                "settled_at": prev.get("settled_at"),
            }
            _save(d)
    except Exception:
        pass


def fetch_settlements(resolver) -> int:
    """增量抓结算：只遍历 final_result 为空的条，用 resolver(cid)->"Yes"/"No"/None 填。
    已结算的跳过（不重抓）。resolver 由调用方注入（api 层用 574）。返回新结算条数。
    🔒 resolver 打外网可能慢——锁覆盖整个读改写周期是刻意的：结算回填正确性 > 并发度
    （此函数只被 /scorecard 单点调用，凑巧撞上 record_judgment 时也只是排队几秒）。"""
    with _LOCK:
        d = _load()
        n = 0
        for r in d.values():
            if r.get("final_result"):          # 已结算 → 跳过
                continue
            cid = r.get("cid")
            if not cid:
                continue
            try:
                winner = resolver(cid)
            except Exception:
                winner = None
            if winner in ("Yes", "No"):
                r["final_result"] = winner
                r["settled_at"] = int(time.time())
                n += 1
        if n:
            _save(d)
    return n


def compute_scorecard() -> dict:
    """纯代码冷数字 + 行表。不调 AI。命中率只算方向；NO BASIS 单列、不进命中率。"""
    d = _load()
    rows, settled_endorsed, hits = [], 0, 0
    nobasis_total, nobasis_clear = 0, 0
    for r in d.values():
        fc = r.get("follow_call")
        outcome = r.get("outcome")
        winner = r.get("final_result")
        settled = winner in ("Yes", "No")
        is_nobasis = fc == "NO BASIS"
        wallet_won = settled and winner == outcome
        if is_nobasis:
            status = "nobasis"
            nobasis_total += 1
            if wallet_won:
                nobasis_clear += 1          # 事后看其实有清晰方向（AI 当时过谨慎、错过）
        elif not settled:
            status = "pending"
        else:
            settled_endorsed += 1
            status = "hit" if wallet_won else "miss"
            if wallet_won:
                hits += 1
        rows.append({
            "wallet": r.get("wallet"), "market_question": r.get("market_question"),
            "outcome": outcome, "follow_call": fc, "confidence": r.get("confidence"),
            "source": r.get("source"), "winner": winner, "status": status,
        })
    # 已结算(hit/miss)排前，其次 nobasis，最后 pending
    _order = {"hit": 0, "miss": 0, "nobasis": 1, "pending": 2}
    rows.sort(key=lambda x: _order.get(x["status"], 3))
    return {
        "tested": len(d),
        "settled": sum(1 for r in d.values() if r.get("final_result")),
        "direction_consistent": hits,
        "settled_endorsed": settled_endorsed,
        "hit_rate_pct": round(hits / settled_endorsed * 100, 1) if settled_endorsed else None,
        "nobasis_total": nobasis_total,
        "nobasis_clear_in_hindsight": nobasis_clear,
        "rows": rows,
        "note": "命中率=判断方向命中、非跟单收益；NO BASIS 不计入命中率，单列。冷数字纯代码算，不经 AI。",
    }
