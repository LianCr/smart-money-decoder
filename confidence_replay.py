"""
confidence_replay.py — 信心回验闭环（P1-6 / T2.5：confidence_log 的读取方）

红线 4 撤掉信心守卫的正当性来源是"可观测：每次 confidence/lean 记进
`.data/confidence_log.jsonl`，待盘真结算由记分牌回验高信心是否真命中"。
写入方（analyzer/market_thesis._log_confidence）六周前就有了，本模块是拖欠的
另一半：读日志 → 查结算 → 按方向对答案 → high/med/low 分档命中率。

🔴 灵魂红线（与 scorecard.py 同源，任何改动不许越）：
  1. 命中 = **判断方向命中**（market_lean vs 结算结果），永不算跟单收益率。
  2. lean 未定（unclear / 缺失 / 脏值）= NO BASIS **单列**，不进命中率分子分母
     ——即使盘已结算、即使"猜对了"也不算。
  3. compute() **纯代码冷数字**，不调任何 AI。
  4. **绝不回填**：confidence_log 是只读输入（本模块对它零写入，坏行只跳过、
     绝不隔离改名——隔离是对自家档案的礼遇，不是对别家输入的权利）；
     已结算条**冻结**——判断与结果都不许再改，任何试图改写的代码路径
     raise ReplayIntegrityError（tests/test_confidence_replay.py 钉死）。
  5. 样本 < MIN_BUCKET_N 的档如实标 insufficient、不显示误导百分比。

口径说明（进 payload 的 note）：n = 市场级判断数——同一 (cid, as_of) 的多次
缓存重建折叠为一条、取最新 ts（最后服务用户的那份判断），n_builds 与
confidence_variants 留痕（P1-7 非确定性的诚实可观测，不藏）。

结算由调用方注入 resolver(cid) -> "Yes"/"No"/None（api 层用 574，免费零 token），
本模块不直接依赖 heisenberg —— 与 scorecard.fetch_settlements 同款契约。
"""
import threading
import time
from pathlib import Path

from core.config import REPLAY_MIN_BUCKET_N
from core.jsonstore import CORRUPT, OK, atomic_write_json, load_json, quarantine
from core.log import get_logger

LOG = get_logger("confidence_replay")

CONFIDENCE_LOG = Path(".data/confidence_log.jsonl")   # 只读输入（写入方在 market_thesis）
ARCHIVE = Path(".data/confidence_replay.json")        # 回验档案（本模块唯一落盘点）
_LOCK = threading.Lock()
MIN_BUCKET_N = REPLAY_MIN_BUCKET_N
CONF_BUCKETS = ("high", "med", "low", "other")        # other = 写方吐了不认识的信心值


class ReplayIntegrityError(RuntimeError):
    """试图改写已结算的历史记录——绝不回填红线的机器强制。"""


# ── 读取归一（写方不折叠大小写/medium，值集不闭合——读方兜）─────────────────

def _norm_confidence(v) -> str:
    s = str(v or "").strip().lower()
    if s == "medium":
        s = "med"
    return s if s in ("high", "med", "low") else "other"


def _norm_lean(v):
    """归一到 "YES"/"NO"，其余（unclear/缺失/脏值）→ None = NO BASIS。"""
    if v is None:
        return None
    s = str(v).strip().upper()
    if s.startswith("YES"):
        return "YES"
    if s.startswith("NO"):
        return "NO"
    return None


def _read_log() -> list:
    """读 confidence_log（只读！）。坏行跳过——JSONL 追加写丢半行是已接受语义
    （DEV_LOG 2026-08-01），跳过即可；🔴 绝不对输入文件做隔离/改名/写入。"""
    try:
        raw = CONFIDENCE_LOG.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError:
        return []
    import json
    out = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict):
            out.append(e)
    return out


def _collapse(entries) -> dict:
    """同 (cid, as_of) 折叠：取最新 ts 那条为准（最后服务用户的判断），
    n_builds / confidence_variants 留痕。返回 {key: 判断条}。"""
    groups = {}
    for e in entries:
        cid, as_of = e.get("cid"), e.get("as_of")
        if not cid or not as_of:
            continue
        groups.setdefault(f"{cid}_{as_of}", []).append(e)
    out = {}
    for key, g in groups.items():
        g.sort(key=lambda e: e.get("ts") or 0)
        latest = g[-1]
        out[key] = {
            "cid": latest.get("cid"), "as_of": latest.get("as_of"),
            "market": latest.get("market"),
            "market_lean": latest.get("market_lean"),                  # 原样存（logged 事实）
            "confidence": _norm_confidence(latest.get("confidence")),  # 归一存（分档身份）
            "n_builds": len(g),
            "confidence_variants": sorted({_norm_confidence(e.get("confidence")) for e in g}),
            "guard_flagged": bool(latest.get("guard_flags")),          # 旧格式行无此字段 → False
            "logged_ts": latest.get("ts"),
        }
    return out


# ── 档案（唯一写路径全走下面两个函数，冻结检查在此强制）──────────────────────

def _load() -> dict:
    status, d = load_json(ARCHIVE, default={})
    if status == CORRUPT:
        LOG.warning("⚠ 回验档案损坏：原件已隔离为 .corrupt-* 备份，本次以空档案继续"
                    "（判断可从 confidence_log 重新收集；已结算结果在备份里可人工抢救）")
    elif status == OK and not isinstance(d, dict):
        quarantine(ARCHIVE)
        LOG.warning("⚠ 回验档案结构异常（顶层不是对象）：已隔离为 .corrupt-* 备份")
        return {}
    return d


def _save(d: dict) -> None:
    try:
        atomic_write_json(ARCHIVE, d)
    except Exception as e:
        LOG.warning(f"⚠ 回验档案写入失败（档案保持原样未被破坏）：{type(e).__name__}: {e}")


def _upsert_judgment(d: dict, key: str, entry: dict) -> bool:
    """写入/更新一条判断。🔴 已结算条冻结：结果出来之后再改当时的判断=事后篡改，raise。
    返回是否真的变了（调用方据此决定要不要落盘）。"""
    prev = d.get(key)
    if prev and prev.get("final_result"):
        raise ReplayIntegrityError(f"已结算条冻结，拒绝改写判断：{key}")
    merged = dict(entry)
    merged["final_result"] = (prev or {}).get("final_result")
    merged["settled_at"] = (prev or {}).get("settled_at")
    changed = merged != prev
    d[key] = merged
    return changed


def _fill_verdict(d: dict, key: str, winner) -> bool:
    """填结算结果（只填空、严格 Yes/No 白名单）。🔴 已有结果的条 raise——结果是历史事实。"""
    e = d[key]
    if e.get("final_result"):
        raise ReplayIntegrityError(f"已结算条冻结，拒绝覆盖结果：{key}")
    if winner not in ("Yes", "No"):
        return False
    e["final_result"] = winner
    e["settled_at"] = int(time.time())
    return True


def _ingest(d: dict) -> int:
    """从 confidence_log 收集判断进档案（内存操作，落盘由调用方决定）。
    已结算条跳过（冻结）——log 里更晚的重建也不许改已定案的历史。返回变更条数。"""
    n = 0
    for key, entry in _collapse(_read_log()).items():
        if key in d and d[key].get("final_result"):
            continue
        if _upsert_judgment(d, key, entry):
            n += 1
    return n


# ── 对外两个入口 ─────────────────────────────────────────────────────────────

def settle(resolver) -> int:
    """增量回验：收集新判断 + 只对 pending 条查结算（resolver(cid)->"Yes"/"No"/None，
    调用方注入；单 cid 异常不拖累其余）。返回新结算条数。
    🔒 锁覆盖整个读改写周期（与 scorecard.fetch_settlements 同理由：正确性 > 并发度）。"""
    with _LOCK:
        d = _load()
        changed = _ingest(d)
        n = 0
        for key, e in d.items():
            if e.get("final_result"):
                continue
            cid = e.get("cid")
            if not cid:
                continue
            try:
                winner = resolver(cid)
            except Exception:
                winner = None
            if winner in ("Yes", "No"):
                _fill_verdict(d, key, winner)
                n += 1
        if changed or n:
            _save(d)
    return n


def _status(e: dict) -> str:
    lean = _norm_lean(e.get("market_lean"))
    if lean is None:
        return "nobasis"                       # 方向未定 → 单列，结算了也不比
    winner = e.get("final_result")
    if winner not in ("Yes", "No"):
        return "pending"
    hit = (lean == "YES" and winner == "Yes") or (lean == "NO" and winner == "No")
    return "hit" if hit else "miss"


def compute() -> dict:
    """纯代码冷数字。**纯读**：不落盘、不打网络——档案里的判断与 log 里尚未
    settle 的新判断在内存合并后出数（新判断以 pending 形态即时可见）。"""
    d = _load()
    _ingest(d)                                 # 内存合并，不 _save——GET 不写盘
    buckets = {b: {"n": 0, "hits": 0} for b in CONF_BUCKETS}
    cross = {"flagged": {"n": 0, "hits": 0}, "clean": {"n": 0, "hits": 0}}
    rows, nobasis_n, pending_n, settled_n = [], 0, 0, 0
    for key, e in d.items():
        st = _status(e)
        if st == "nobasis":
            nobasis_n += 1
        elif st == "pending":
            pending_n += 1
        else:
            settled_n += 1
            b = e.get("confidence") if e.get("confidence") in CONF_BUCKETS else "other"
            g = "flagged" if e.get("guard_flagged") else "clean"
            buckets[b]["n"] += 1
            cross[g]["n"] += 1
            if st == "hit":
                buckets[b]["hits"] += 1
                cross[g]["hits"] += 1
        rows.append({
            "key": key, "cid": e.get("cid"), "as_of": e.get("as_of"),
            "market": e.get("market"), "market_lean": e.get("market_lean"),
            "confidence": e.get("confidence"), "n_builds": e.get("n_builds"),
            "confidence_variants": e.get("confidence_variants"),
            "guard_flagged": e.get("guard_flagged"),
            "final_result": e.get("final_result"), "status": st,
            "logged_ts": e.get("logged_ts"),
        })
    for c in list(buckets.values()) + list(cross.values()):
        c["insufficient"] = c["n"] < MIN_BUCKET_N
        c["hit_rate_pct"] = (round(c["hits"] / c["n"] * 100, 1)
                             if c["n"] and not c["insufficient"] else None)
    _order = {"hit": 0, "miss": 0, "nobasis": 1, "pending": 2}
    rows.sort(key=lambda x: (_order.get(x["status"], 3), -(x.get("logged_ts") or 0)))
    return {
        "buckets": buckets,
        "guard_cross": cross,
        "nobasis_n": nobasis_n, "pending_n": pending_n,
        "settled_n": settled_n, "total": len(d),
        "min_bucket_n": MIN_BUCKET_N,
        "rows": rows,
        "note": "命中=判断方向命中（market_lean vs 结算），永不算跟单收益；方向未定(NO BASIS)单列"
                "不进命中率；原判断绝不回填、已结算条冻结；纯代码零 AI。n=市场级判断"
                "（同盘缓存重建折叠取最新，n_builds/variants 留痕）；样本<阈值的档如实标"
                "样本不足、不显示百分比。",
    }
