"""
tests/test_cachepolicy.py — 缓存失效注册表契约（P1-10）+ 旧快照幸存红线（T2.4 #5）

覆盖：
  1. 注册表完整性：import services.dashboard_build 后 7 层缓存全部在册（=旧手写清单逐一对应）
  2. 🔴 T2.4 #5（零测试三年的红线）：purge 只删传入 as_of 当天的 key，**旧日期快照必须幸存**
     ——旧快照是刷新失败时的回退底，删了就是"删了好缓存、重建又失败、两头空"
  3. purge 语义：不存在的文件静默跳过、单条 resolver 炸掉不拖累其余（best-effort）
  4. 🛡 忘登记 lint：扫全仓源码的 `.cache/<dir>` 字面量，每个目录必须 ∈ 注册名 ∪ 显式豁免表
     ——新增缓存目录既不注册也不豁免 → 本测试红（P1-10 的"半新半旧板"病根从此机器可查）
"""

import json
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")

import services.dashboard_build as db          # import 即完成全部注册（它 import 三个拥有者模块）
import analyzer.market_thesis as mt
import briefing.assemble as assemble
import briefing.market_context as mc
from core import cachepolicy

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


# ── 1. 注册表完整性（= 旧手写 7 元素清单） ───────────────────────────────────
print("注册表完整性")
EXPECTED = {"dashboard", "briefing_api", "reasoner_v3", "board_ai",
            "briefing", "market_context", "market_thesis"}
check("7 层缓存全部在册", set(cachepolicy.registered_names()), EXPECTED)

# ── 2/3. purge 语义 + 旧快照幸存（T2.4 #5）──────────────────────────────────
print("purge 语义（T2.4 #5：旧快照幸存红线）")
W, CID, OUT, TODAY, OLD = "0x" + "a" * 40, "0xcid", "Yes", "2026-08-04", "2026-01-01"

with tempfile.TemporaryDirectory() as tmp:
    saved = {
        "db": {k: getattr(db, k) for k in ("DASHBOARD_CACHE", "BRIEFING_CACHE", "REASONER_CACHE", "BOARD_AI_CACHE")},
        "mt": mt.CACHE, "assemble": assemble.CACHE_DIR, "mc": mc.CACHE_DIR,
    }
    try:
        for k in saved["db"]:
            setattr(db, k, Path(tmp) / k.lower())
        mt.CACHE = Path(tmp) / "market_thesis"
        assemble.CACHE_DIR = Path(tmp) / "briefing"
        mc.CACHE_DIR = Path(tmp) / "market_context"

        # 每层各造 今天 + 旧日期 两份文件（md5 型 key 直接用 resolver 算路径）
        ctx_today = {"wallet": W, "cid": CID, "outcome": OUT, "as_of": TODAY}
        ctx_old = {"wallet": W, "cid": CID, "outcome": OUT, "as_of": OLD}
        all_today, all_old = [], []
        for name in EXPECTED:
            r = cachepolicy._REGISTRY[name]
            for ctx, bucket in ((ctx_today, all_today), (ctx_old, all_old)):
                p = r(ctx)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps({"as_of": ctx["as_of"]}), encoding="utf-8")
                bucket.append(p)

        n = cachepolicy.purge(W, CID, OUT, TODAY)
        check("purge 返回删除数=7（今天的每层各一）", n, 7)
        check("今天的 key 全部删除", [p for p in all_today if p.exists()], [])
        check("🔴 旧日期快照全部幸存（回退底不许碰）", len([p for p in all_old if p.exists()]), 7)

        n2 = cachepolicy.purge(W, CID, OUT, TODAY)
        check("重复 purge（文件已不存在）→ 0，不炸", n2, 0)

        # 单条 resolver 炸掉不拖累其余（best-effort）
        cachepolicy.register("_boom", lambda ctx: (_ for _ in ()).throw(RuntimeError("resolver 炸")))
        try:
            for p in all_today:
                p.write_text("{}", encoding="utf-8")
            check("坏 resolver 在册时其余 7 层照删", cachepolicy.purge(W, CID, OUT, TODAY), 7)
        finally:
            del cachepolicy._REGISTRY["_boom"]

        # 服务层入口 = 注册表（_purge_wallet_caches 委托）
        for p in all_today:
            p.write_text("{}", encoding="utf-8")
        check("_purge_wallet_caches 委托注册表（行为不变）", db._purge_wallet_caches(W, CID, OUT, TODAY), 7)
    finally:
        for k, v in saved["db"].items():
            setattr(db, k, v)
        mt.CACHE, assemble.CACHE_DIR, mc.CACHE_DIR = saved["mt"], saved["assemble"], saved["mc"]

# ── 4. 忘登记 lint：源码里的 .cache/<名> 必须 在册 或 显式豁免 ────────────────
print("忘登记 lint")
# 豁免表（每条带理由；新增缓存目录不注册也不豁免 → 本检查红）：
EXEMPT = {
    "news":                  "按查询关键词缓存、与钱包无关，刷新语义不适用（fetcher/news.py）",
    "decoder":               "USE_DECODER_CACHE 默认关，且 decoder 不在服务 import 图（仅回测重放）",
    "backtest":              "离线回测产物，正向流程只读 git 跟踪的静态正本",
    "event_structure.json":  "市场全集扫描的单文件缓存（非按盘/钱包 key），刷新不清它是既有语义",
}
SCAN_DIRS = ("api", "services", "core", "analyzer", "briefing", "fetcher", "backtest", "tools")
SCAN_FILES = [Path(f"{m}.py") for m in ("recommend", "hot_traders", "scorecard")]
pat = re.compile(r"\.cache/([\w][\w.-]*)")   # 首字符不许是点：排除注释里 ".cache/.data" 这类并列写法
found = set()
for d in SCAN_DIRS:
    for p in Path(d).rglob("*.py"):
        found |= {m.group(1) for m in pat.finditer(p.read_text(encoding="utf-8"))}
for p in SCAN_FILES:
    if p.exists():
        found |= {m.group(1) for m in pat.finditer(p.read_text(encoding="utf-8"))}

registered = set(cachepolicy.registered_names())
unaccounted = sorted(found - registered - set(EXEMPT))
check("源码全部 .cache/<目录> 都 在册∪豁免（忘登记=此处红）", unaccounted, [])
check("豁免表没有多余条目（豁免的目录必须真在源码里）", sorted(set(EXEMPT) - found), [])

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
