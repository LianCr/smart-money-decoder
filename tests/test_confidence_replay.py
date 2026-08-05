"""
tests/test_confidence_replay.py — 回验闭环契约（P1-6 / T2.5）

钉死的契约（对应 confidence_replay.py 的红线头）：
  1. 读取归一：同 (cid,as_of) 多次重建折叠取最新 ts（n_builds/variants 留痕）；
     confidence 大小写/medium 在读方折叠，不认识进 other 档；旧格式行（无
     rationale/guard_flags）按缺省容忍。
  2. 方向比对：lean YES+结算 Yes=hit、NO+Yes=miss；lean ∈ {unclear,None,脏值} =
     NO BASIS 单列，**永不进命中率分子分母——即使已结算也不算**。
  3. 🔴 绝不回填：confidence_log 是只读输入（settle/compute 前后字节哈希必须一致，
     坏行也只跳过、绝不隔离改名）；已结算条冻结——settle 不覆盖、直接调写路径必须
     raise ReplayIntegrityError；log 里出现更晚的重建也不许改已结算条的判断。
  4. 分档：样本 < MIN_BUCKET_N → hit_rate_pct=None + insufficient=True（绝不显示
     误导百分比）；空档 hit_rate=None 非 0。
  5. compute() 纯读：不落盘、不打网络。
"""

import hashlib
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")

import confidence_replay as cr

# 🔴 测试绝不碰真 .data/：档案与日志全部重定向到临时目录
_tmp = tempfile.mkdtemp()
cr.ARCHIVE = Path(_tmp) / "replay_test.json"
cr.CONFIDENCE_LOG = Path(_tmp) / "confidence_log.jsonl"

passed = 0
failed = 0


def check(name, got, want):
    global passed, failed
    if got == want:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name}: got={got!r} want={want!r}")


def write_log(lines):
    cr.CONFIDENCE_LOG.parent.mkdir(parents=True, exist_ok=True)
    with cr.CONFIDENCE_LOG.open("w", encoding="utf-8") as f:
        for ln in lines:
            f.write((ln if isinstance(ln, str) else json.dumps(ln, ensure_ascii=False)) + "\n")


def log_line(cid, as_of, lean, conf, ts, guard_flags=None, old_format=False):
    d = {"ts": ts, "cid": cid, "market": f"Market {cid}?", "as_of": as_of,
         "market_lean": lean, "lean_strength": 70, "confidence": conf,
         "pivotal_unknown": "x"}
    if not old_format:                     # 新格式（PR #21 后）才有这两个字段
        d["rationale"] = "r"
        d["guard_flags"] = guard_flags or []
    return d


def md5(p):
    return hashlib.md5(Path(p).read_bytes()).hexdigest()


# ── 1. 读取归一 + 同盘重建折叠 ───────────────────────────────────────────────
print("读取归一 + 折叠")
write_log([
    # c1@d1 三次重建：取最新 ts（HIGH→high），variants 留痕，guard_flagged 取最新条
    log_line("c1", "2026-06-25", "YES", "med", 100, old_format=True),
    log_line("c1", "2026-06-25", "YES", "HIGH", 300, guard_flags=["DURATION_COMPUTED"]),
    log_line("c1", "2026-06-25", "YES", "med", 200, old_format=True),
    log_line("c2", "2026-06-25", "NO", "medium", 110),          # medium → med
    log_line("c3", "2026-06-25", "YES", "weird", 120),          # 脏 confidence → other 档
    log_line("c4", "2026-06-25", "unclear", "high", 130),       # → nobasis
    log_line("c5", "2026-06-25", None, "low", 140),             # lean 缺失 → nobasis
    log_line("c6", "2026-06-25", "NO", "low", 150),
    log_line("c7", "2026-06-25", "YES", "high", 160),           # resolver 查无结果 → pending
    "this line is not json {{{",                                 # 坏行：跳过，不隔离
])
log_hash_0 = md5(cr.CONFIDENCE_LOG)

out = cr.compute()
check("总判断数=7（坏行跳过、同盘折叠）", out["total"], 7)
check("全部未结算 → pending_n=5（nobasis 单列不算 pending）", out["pending_n"], 5)
check("nobasis_n=2（unclear + lean 缺失）", out["nobasis_n"], 2)
check("settled_n=0", out["settled_n"], 0)
c1 = next(r for r in out["rows"] if r["cid"] == "c1")
check("折叠取最新 ts 的判断（HIGH→high）", c1["confidence"], "high")
check("n_builds=3 留痕", c1["n_builds"], 3)
check("confidence_variants 留痕", c1["confidence_variants"], ["high", "med"])
check("guard_flagged 取最新条", c1["guard_flagged"], True)
c2 = next(r for r in out["rows"] if r["cid"] == "c2")
check("medium 折叠为 med", c2["confidence"], "med")
check("旧格式行 guard_flagged=False", c2["guard_flagged"], False)
c3 = next(r for r in out["rows"] if r["cid"] == "c3")
check("脏 confidence → other", c3["confidence"], "other")
check("compute() 纯读：不创建档案文件", cr.ARCHIVE.exists(), False)
check("compute() 纯读：log 字节哈希不变", md5(cr.CONFIDENCE_LOG), log_hash_0)
check("空样本档 hit_rate=None 非 0", out["buckets"]["high"]["hit_rate_pct"], None)

# ── 2. settle：方向比对正负样本 + resolver 边界 ──────────────────────────────
print("settle 方向比对")
_results = {"c1": "Yes", "c2": "No", "c3": "Yes", "c4": "Yes", "c6": "Yes"}
_calls = []


def _resolver(cid):
    _calls.append(cid)
    return _results.get(cid)


n = cr.settle(_resolver)
check("新结算 5 条（c7 查无结果保持 pending）", n, 5)
out = cr.compute()
by_cid = {r["cid"]: r for r in out["rows"]}
check("YES + Yes → hit", by_cid["c1"]["status"], "hit")
check("NO + No → hit", by_cid["c2"]["status"], "hit")
check("NO + Yes → miss", by_cid["c6"]["status"], "miss")
check("nobasis 已结算仍是 nobasis（方向不可比，赢了也不算）", by_cid["c4"]["status"], "nobasis")
check("查无结果 → pending", by_cid["c7"]["status"], "pending")
check("settled_n 只数方向可比的条", out["settled_n"], 4)
check("nobasis 不进分子分母：nobasis_n 仍=2", out["nobasis_n"], 2)

_calls.clear()
n2 = cr.settle(_resolver)
check("重复 settle → 0（增量）", n2, 0)
check("已结算条不再打 resolver", "c1" in _calls, False)

n3 = cr.settle(lambda cid: (_ for _ in ()).throw(RuntimeError("574 挂了")))
check("resolver 抛异常 → 0 不炸", n3, 0)
n4 = cr.settle(lambda cid: "MAYBE")
check("脏结算值不入档", n4, 0)
check("c7 仍 pending", next(r for r in cr.compute()["rows"] if r["cid"] == "c7")["status"], "pending")

# ── 3. 🔴 绝不回填三连 ──────────────────────────────────────────────────────
print("绝不回填")
check("settle 前后 confidence_log 字节哈希一致（只读输入）", md5(cr.CONFIDENCE_LOG), log_hash_0)

n5 = cr.settle(lambda cid: "No" if cid == "c1" else None)   # 试图用相反结果重结算 c1
c1_now = next(r for r in cr.compute()["rows"] if r["cid"] == "c1")
check("已结算条 final_result 不被覆盖", c1_now["final_result"], "Yes")

# 直接调写路径试图改已结算条 → 必须 raise
from core.jsonstore import load_json
_, d = load_json(cr.ARCHIVE, default={})
key = "c1_2026-06-25"
try:
    cr._upsert_judgment(d, key, {"cid": "c1", "as_of": "2026-06-25", "market_lean": "NO"})
    check("改已结算条的判断 → raise ReplayIntegrityError", "没抛", "ReplayIntegrityError")
except cr.ReplayIntegrityError:
    check("改已结算条的判断 → raise ReplayIntegrityError", "ReplayIntegrityError", "ReplayIntegrityError")
try:
    cr._fill_verdict(d, key, "No")
    check("改已结算条的结果 → raise ReplayIntegrityError", "没抛", "ReplayIntegrityError")
except cr.ReplayIntegrityError:
    check("改已结算条的结果 → raise ReplayIntegrityError", "ReplayIntegrityError", "ReplayIntegrityError")

# log 里出现更晚的重建（判断翻向）也不许改已结算条
with cr.CONFIDENCE_LOG.open("a", encoding="utf-8") as f:
    f.write(json.dumps(log_line("c1", "2026-06-25", "NO", "low", 999)) + "\n")
cr.settle(_resolver)
c1_after = next(r for r in cr.compute()["rows"] if r["cid"] == "c1")
check("已结算条冻结：更晚的重建不改判断", c1_after["market_lean"], "YES")
check("已结算条冻结：status 仍 hit", c1_after["status"], "hit")

# ── 4. 分档 + 样本不足 ──────────────────────────────────────────────────────
print("分档")
# 当前已结算方向可比：c1 hit(high) · c2 hit(med) · c3 hit(other) · c6 miss(low)
_saved_min = cr.MIN_BUCKET_N
cr.MIN_BUCKET_N = 5
out = cr.compute()
check("n<N → hit_rate_pct=None", out["buckets"]["high"]["hit_rate_pct"], None)
check("n<N → insufficient=True", out["buckets"]["high"]["insufficient"], True)
check("n 照实显示", out["buckets"]["high"]["n"], 1)
check("hits 照实显示", out["buckets"]["high"]["hits"], 1)
check("min_bucket_n 随 payload 下发", out["min_bucket_n"], 5)

cr.MIN_BUCKET_N = 1
out = cr.compute()
check("n>=N → 出百分比（high 1/1）", out["buckets"]["high"]["hit_rate_pct"], 100.0)
check("n>=N → insufficient=False", out["buckets"]["high"]["insufficient"], False)
check("low 档 0/1 → 0.0（真 0 不是 None）", out["buckets"]["low"]["hit_rate_pct"], 0.0)
check("other 档独立成档", out["buckets"]["other"]["n"], 1)

# ── 5. guard_flags 交叉（F4 数据面）─────────────────────────────────────────
print("guard 交叉")
# c1 guard_flagged=True(hit)；c2/c3/c6 False(hit,hit,miss)
check("flagged 档 n", out["guard_cross"]["flagged"]["n"], 1)
check("flagged 档 hits", out["guard_cross"]["flagged"]["hits"], 1)
check("clean 档 n", out["guard_cross"]["clean"]["n"], 3)
check("clean 档 hit_rate（2/3）", out["guard_cross"]["clean"]["hit_rate_pct"], 66.7)
cr.MIN_BUCKET_N = 5
out = cr.compute()
check("guard 交叉同守样本不足规矩", out["guard_cross"]["clean"]["hit_rate_pct"], None)
cr.MIN_BUCKET_N = _saved_min

# ── 6. 空输入 + 损坏档案 ────────────────────────────────────────────────────
print("边界")
_tmp2 = tempfile.mkdtemp()
cr.ARCHIVE = Path(_tmp2) / "replay_test.json"
cr.CONFIDENCE_LOG = Path(_tmp2) / "confidence_log.jsonl"
out = cr.compute()
check("log 不存在 → 空 payload 不炸", out["total"], 0)
check("空档全 None 非 0", all(out["buckets"][b]["hit_rate_pct"] is None for b in out["buckets"]), True)
check("settle 无输入 → 0", cr.settle(lambda cid: "Yes"), 0)

write_log([log_line("cX", "2026-07-01", "YES", "high", 100)])
cr.settle(lambda cid: "Yes")
cr.ARCHIVE.write_text('{"半截', encoding="utf-8")     # 模拟损坏档案
out = cr.compute()
check("损坏档案 → 隔离后以空档继续（判断从 log 重新可见）", out["total"], 1)
backups = list(cr.ARCHIVE.parent.glob("replay_test.json.corrupt-*"))
check("损坏原件被隔离保留", len(backups), 1)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
