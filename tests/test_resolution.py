"""
tests/test_resolution.py — backtest/resolution.py 纯逻辑 mock 测试（无网络）

测 _winner_from_prices（定格价→获胜方）与 _parse_ts（容错时间解析）。
覆盖 gamma 的真实字段形态：JSON 字符串、["0","1"]/["1","0"]、非标准时间格式。
"""

import sys
from datetime import datetime, timezone
sys.path.insert(0, ".")

from backtest.resolution import _winner_from_prices, _parse_ts, _parse_json_field

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


# ── _parse_json_field：gamma 的字段是 JSON 字符串 ──────────────────────────────
check("JSON 字符串解析", _parse_json_field('["Yes", "No"]'), ["Yes", "No"])
check("已是 list 原样", _parse_json_field(["Yes", "No"]), ["Yes", "No"])
check("坏字符串 → None", _parse_json_field("not json"), None)

# ── _winner_from_prices ───────────────────────────────────────────────────────
# No 赢：["0","1"]（真实实探形态，JSON 字符串）
check("No 赢（JSON 串 ['0','1']）", _winner_from_prices('["Yes","No"]', '["0","1"]'), "No")
# Yes 赢：["1","0"]
check("Yes 赢（['1','0']）", _winner_from_prices('["Yes","No"]', '["1","0"]'), "Yes")
# list 形态也支持
check("list 形态 Yes 赢", _winner_from_prices(["Yes", "No"], ["1", "0"]), "Yes")
# 未干净结算（0.5/0.5）→ None
check("0.5/0.5 未结算 → None", _winner_from_prices('["Yes","No"]', '["0.5","0.5"]'), None)
# 接近但未定格（0.92）→ None（低于 0.99 阈值）
check("0.92 未定格 → None", _winner_from_prices('["Yes","No"]', '["0.92","0.08"]'), None)
# 长度不匹配 → None
check("长度不匹配 → None", _winner_from_prices('["Yes","No"]', '["1"]'), None)
# 多结果市场：第三个赢
check("多结果取 argmax", _winner_from_prices('["A","B","C"]', '["0","0","1"]'), "C")

# ── _parse_ts：容错各种时间格式 ───────────────────────────────────────────────
def u(y, mo, d, h, mi, s):
    return int(datetime(y, mo, d, h, mi, s, tzinfo=timezone.utc).timestamp())

# closedTime 真实形态：空格分隔 + 两位偏移 +00
check("closedTime 非标准格式", _parse_ts("2026-06-11 06:13:57+00"), u(2026, 6, 11, 6, 13, 57))
# endDate 真实形态：ISO + Z
check("endDate ISO+Z", _parse_ts("2026-06-11T03:59:00Z"), u(2026, 6, 11, 3, 59, 0))
# 无时区 → 按 UTC
check("无时区按 UTC", _parse_ts("2026-06-11T03:59:00"), u(2026, 6, 11, 3, 59, 0))
# 空 / None → None
check("空字符串 → None", _parse_ts(""), None)
check("None → None", _parse_ts(None), None)
check("坏格式 → None", _parse_ts("not a date"), None)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
