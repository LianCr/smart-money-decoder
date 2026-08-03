"""
tests/test_jsonstore.py — core/jsonstore 纯 IO 逻辑测试（无网络，tempdir 不碰真 .data/）

背景（对应 P0 bug）：`.data/scorecard.json` 是产品唯一"我的判断后来准不准"的档案，
它同时踩了两个坑 ——
  ① 写入非原子（write_text 直写）：进程被冷启动/OOM 打断 → 半截 JSON
  ② 读取把解析失败当成"空档案" → 下一次写入直接覆盖掉全部历史
两者叠加 = 一条静默、不可逆的数据丢失路径，而产品红线是"绝不回填造假"，丢了就补不回。

本模块钉死的契约：
  1. 写：内容读回一致 · 父目录自动建
  2. 写：序列化失败时**原文件一字未动**，且不留 .tmp 残骸
  3. 读：正常 → ("ok", data) · 缺文件 → ("missing", default)
  4. 读：损坏 → ("corrupt", default)，且**原始字节完整保留在 .corrupt-* 备份里**（隔离不销毁）
  5. 隔离后原路径空出，后续读写正常，不会二次触发
  6. 同秒内两次损坏不互相覆盖（备份名不撞车）
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")

from core.jsonstore import atomic_write_json, load_json

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


# ── 1. 基本写读往返 + 父目录自动创建 ──────────────────────────────────────────
with tempfile.TemporaryDirectory() as td:
    p = Path(td) / "nested" / "deep" / "a.json"      # 两级父目录都不存在
    payload = {"wallet": "0xABC", "n": 25, "zh": "中文不转义", "nested": {"k": [1, 2, 3]}}
    atomic_write_json(p, payload)
    check("父目录自动创建", p.exists(), True)
    check("写读往返内容一致", json.loads(p.read_text(encoding="utf-8")), payload)
    check("中文不被转义成 \\u", "中文不转义" in p.read_text(encoding="utf-8"), True)
    check("load_json 正常 → ok", load_json(p), ("ok", payload))


# ── 2. 原子性：序列化失败 → 原文件完好、无 .tmp 残骸 ──────────────────────────
with tempfile.TemporaryDirectory() as td:
    p = Path(td) / "archive.json"
    good = {"keep": "me", "records": 25}
    atomic_write_json(p, good)

    class Unserializable:
        pass

    raised = None
    try:
        atomic_write_json(p, {"bad": Unserializable()})
    except TypeError as e:
        raised = type(e).__name__
    check("不可序列化对象 → 抛 TypeError", raised, "TypeError")
    check("🔴 写失败后原文件一字未动", json.loads(p.read_text(encoding="utf-8")), good)
    check("写失败后不留 .tmp 残骸", sorted(x.name for x in Path(td).iterdir()), ["archive.json"])


# ── 3. 缺文件 → missing，default 原样返回 ──────────────────────────────────────
with tempfile.TemporaryDirectory() as td:
    p = Path(td) / "nope.json"
    check("文件不存在 → missing + default", load_json(p, default={}), ("missing", {}))
    check("default 未给时为 None", load_json(p), ("missing", None))
    check("读不存在的文件不会把它创建出来", p.exists(), False)


# ── 4. 🔴 损坏隔离：半截 JSON 的原始字节必须完整幸存在备份里 ───────────────────
with tempfile.TemporaryDirectory() as td:
    p = Path(td) / "scorecard.json"
    truncated = '{"0xa_c1_board": {"wallet": "0xA", "final_result": "Ye'   # 写到一半被砍
    p.write_text(truncated, encoding="utf-8")

    status, data = load_json(p, default={})
    check("损坏 → status=corrupt（不是 missing、不是 ok）", status, "corrupt")
    check("损坏 → 返回 default 让调用方能继续跑", data, {})
    check("损坏文件已从原路径移走", p.exists(), False)

    backups = list(Path(td).glob("scorecard.json.corrupt-*"))
    check("产生了恰好 1 份隔离备份", len(backups), 1)
    check("🔴 备份里是原始字节，一字不差", backups[0].read_text(encoding="utf-8"), truncated)


# ── 5. 隔离后原路径空出：后续读写恢复正常，不二次触发 ─────────────────────────
with tempfile.TemporaryDirectory() as td:
    p = Path(td) / "s.json"
    p.write_text("{broken", encoding="utf-8")
    load_json(p, default={})                              # 第一次读 → 隔离

    check("隔离后再读 → missing（不是又一次 corrupt）", load_json(p, default={}), ("missing", {}))
    atomic_write_json(p, {"fresh": True})
    check("隔离后写入正常", load_json(p), ("ok", {"fresh": True}))
    check("隔离备份仍只有 1 份（第二次读没再造）",
          len(list(Path(td).glob("s.json.corrupt-*"))), 1)


# ── 6. 同秒内两次损坏，备份名不撞车（否则第一份证据被第二份盖掉）───────────────
with tempfile.TemporaryDirectory() as td:
    p = Path(td) / "s.json"
    p.write_text("first-corrupt", encoding="utf-8")
    load_json(p, default={})
    p.write_text("second-corrupt", encoding="utf-8")
    load_json(p, default={})

    backups = sorted(Path(td).glob("s.json.corrupt-*"))
    check("两次损坏 → 两份独立备份", len(backups), 2)
    check("两份内容都在、没互相覆盖",
          sorted(b.read_text(encoding="utf-8") for b in backups),
          ["first-corrupt", "second-corrupt"])


# ── 7. 非 dict 顶层（list / 标量）同样支持，不做类型假设 ───────────────────────
with tempfile.TemporaryDirectory() as td:
    p = Path(td) / "list.json"
    atomic_write_json(p, [1, "两", {"三": 3}])
    check("顶层 list 往返一致", load_json(p), ("ok", [1, "两", {"三": 3}]))


print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
