"""
tests/test_business_file_reads.py — `.data/` 业务文件损坏时必须"隔离"而不是"静默变空"

背景：`.data/recommendations.json`（推荐榜）与 `.data/hot_traders.json`（首页热门条）
不是缓存 —— 它们重建一次要几分钟、烧 token，而且是用户打开网站第一眼看到的东西。
原来的读法是 `try: json.loads(...) except: pass`，损坏时静默退成空榜：
用户看到一个空白首页，日志里什么都没有，排查时无从下手；更糟的是下一次写入
会把损坏文件直接盖掉，连"到底坏成什么样"的证据都没了。

契约（本文件钉死，直接对应 P0-1 的读侧）：
  1. 文件正常   → 原样返回内容
  2. 文件不存在 → 返回空壳（"还没扫过"是合法状态，不是错误）
  3. 文件损坏   → 返回空壳**且原件被隔离成 `.corrupt-*` 备份**（字节一字不差）
  4. 顶层结构不对（合法 JSON 但不是对象）→ 同样不当数据用，不炸

🔴 本测试不 import `api.main`：分层纪律——只测业务文件读隔离，不该拖上 api 装配层
（T2.3 起 import api.main 已零副作用；端点层另有 tests/test_api_endpoints.py）
（见 api/main.py 顶部），测试碰不得。这里直接测两个读路径共用的底层语义
（`core.jsonstore.load_json` + 调用方的 status 分支），与 api 层写法保持一致。
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")

from core.jsonstore import CORRUPT, OK, atomic_write_json, load_json

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


def read_business_file(path, empty_shell):
    """与 api/main.py 的 /recommendations、/hot-traders 完全同构的读法。
    改那边的语义时，这里必须同步改 —— 这就是本测试存在的意义。"""
    status, data = load_json(path, default=None)
    if status == OK and isinstance(data, dict):
        return data, status
    return empty_shell, status


SHELL = {"as_of": "2026-08-03", "candidates": []}
REAL = {"as_of": "2026-08-03", "generated_at": 1785000000,
        "candidates": [{"wallet": "0xA", "score": 88.5}, {"wallet": "0xB", "score": 71.0}]}

# ── 1. 正常文件原样返回 ───────────────────────────────────────────────────────
with tempfile.TemporaryDirectory() as td:
    p = Path(td) / "recommendations.json"
    atomic_write_json(p, REAL)
    out, status = read_business_file(p, SHELL)
    check("正常榜文件原样返回", out, REAL)
    check("正常 → status=ok", status, OK)

# ── 2. 文件不存在 = 合法状态（"还没扫过"），不是错误 ──────────────────────────
with tempfile.TemporaryDirectory() as td:
    out, status = read_business_file(Path(td) / "nope.json", SHELL)
    check("文件不存在 → 空壳", out, SHELL)
    check("文件不存在 → status=missing（不是 corrupt，别乱报警）", status, "missing")

# ── 3. 🔴 损坏 → 空壳 + 原件被隔离，证据不丢 ─────────────────────────────────
with tempfile.TemporaryDirectory() as td:
    p = Path(td) / "recommendations.json"
    atomic_write_json(p, REAL)
    full = p.read_text(encoding="utf-8")
    # 模拟写到一半被冷启动打断。切点钉在"第二个候选之前"而不是 len//2 ——
    # 后者落在哪取决于序列化后的字节数，会让下面"证据可抢救"那条断言时灵时不灵。
    truncated = full[: full.index('"0xB"')]
    p.write_text(truncated, encoding="utf-8")

    out, status = read_business_file(p, SHELL)
    check("损坏 → 返回空壳（用户看到空榜，与旧行为一致）", out, SHELL)
    check("损坏 → status=corrupt（可据此打日志报警）", status, CORRUPT)

    backups = list(Path(td).glob("recommendations.json.corrupt-*"))
    check("🔴 损坏原件被隔离成备份", len(backups), 1)
    check("🔴 备份字节一字不差", backups[0].read_text(encoding="utf-8"), truncated)
    check("能从备份里认出原来的候选（证据可用）", "0xA" in backups[0].read_text(encoding="utf-8"), True)
    check("原路径已空出，下次扫榜可正常写", p.exists(), False)

    atomic_write_json(p, REAL)                       # 下次扫榜
    out, status = read_business_file(p, SHELL)
    check("隔离后重建 → 恢复正常", out, REAL)

# ── 4. 顶层结构不对（合法 JSON 但不是对象）→ 不当数据用，也不炸 ───────────────
with tempfile.TemporaryDirectory() as td:
    p = Path(td) / "hot_traders.json"
    p.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
    out, status = read_business_file(p, SHELL)
    check("顶层是 list → 退空壳不炸", out, SHELL)
    check("顶层是 list → status 仍是 ok（JSON 本身合法）", status, OK)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
