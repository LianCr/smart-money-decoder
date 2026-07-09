"""
tests/test_cachefiles.py — core/cachefiles.newest_dated 纯逻辑测试（无网络，tempdir 不碰真缓存）

背景（对应 bug）：/dashboard 刷新改在"今天"重建后，同一钱包会有多份日期快照；
默认读取必须取**最新日期**那份，旧快照永不误删 → 刷新失败可回退。覆盖：
  1. 多份日期快照取最新（ISO 字典序）
  2. 只匹配本钱包前缀，不吃别的钱包的文件
  3. 前缀是别人前缀的子串时不误配（0xab vs 0xabc）
  4. 日期段不合法的文件名一律忽略
  5. 空目录 / 目录不存在 → None
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")

from core.cachefiles import newest_dated

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


with tempfile.TemporaryDirectory() as td:
    d = Path(td)
    (d / "0xabc_2026-06-25.json").write_text("{}")
    (d / "0xabc_2026-07-08.json").write_text("{}")
    (d / "0xdef_2026-07-30.json").write_text("{}")          # 别的钱包，更新但不该被拿到
    (d / "0xabc_notadate.json").write_text("{}")            # 日期段非法 → 忽略
    (d / "0xabc_2026-7-8.json").write_text("{}")            # 位数不对 → 忽略
    (d / "0xabc_extra_2026-08-01.json").write_text("{}")    # 前缀后多一段 → 忽略

    # 1. 取最新日期
    got = newest_dated(d, "0xabc")
    check("多份快照取最新 as_of", got and got[1], "2026-07-08")
    check("多份快照取最新 路径", got and got[0].name, "0xabc_2026-07-08.json")

    # 2. 别的钱包文件不串
    got = newest_dated(d, "0xdef")
    check("别的钱包只拿自己的", got and got[1], "2026-07-30")

    # 3. 前缀子串不误配（0xab 不该吃 0xabc 的文件）
    check("前缀子串不误配 → None", newest_dated(d, "0xab"), None)

    # 4. 只有非法日期文件的钱包 → None
    (d / "0xbad_hello.json").write_text("{}")
    check("只有非法文件名 → None", newest_dated(d, "0xbad"), None)

# 5. 空目录 / 不存在的目录
with tempfile.TemporaryDirectory() as td:
    check("空目录 → None", newest_dated(td, "0xabc"), None)
check("目录不存在 → None", newest_dated("/nonexistent/dir/xyz", "0xabc"), None)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
