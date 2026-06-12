"""
tests/test_full_activity.py — backtest/full_activity.py 纯逻辑 mock 测试（无网络）

只测 _filter_page：按时间窗 [start_time, end_time] 筛一页（newest-first），
并判断是否已越过老边界（出现早于 start_time 的记录 → 可停翻页）。

覆盖：
  1. 无窗口 → 全留，不停
  2. start_time 过滤旧记录 + 触发老边界停翻
  3. end_time 过滤过新记录，不停
  4. 双边窗口
  5. 缺 timestamp 静默跳过
  6. 老边界判定独立于「该条是否入选」（早于 start 的被剔除但仍置停标志）
  7. 边界值闭区间（等于 start/end 都算窗内）
"""

import sys
sys.path.insert(0, ".")

from backtest.full_activity import _filter_page

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


def ts_list(records):
    return [r["timestamp"] for r in records]


# newest-first 的一页（降序）
PAGE = [
    {"timestamp": 5000, "conditionId": "a"},
    {"timestamp": 4000, "conditionId": "b"},
    {"timestamp": 3000, "conditionId": "c"},
    {"timestamp": 2000, "conditionId": "d"},
    {"timestamp": 1000, "conditionId": "e"},
]

# 1. 无窗口 → 全留，不停
kept, stop = _filter_page(PAGE, None, None)
check("无窗口全留", ts_list(kept), [5000, 4000, 3000, 2000, 1000])
check("无窗口不停翻", stop, False)

# 2. start_time=3000 → 剔除 <3000（2000/1000），并触发老边界
kept, stop = _filter_page(PAGE, 3000, None)
check("start 过滤旧记录", ts_list(kept), [5000, 4000, 3000])
check("start 触发老边界停翻", stop, True)

# 3. end_time=3500 → 剔除 >3500（5000/4000），不触发停（没碰到老边界）
kept, stop = _filter_page(PAGE, None, 3500)
check("end 过滤过新记录", ts_list(kept), [3000, 2000, 1000])
check("end 不触发停翻", stop, False)

# 4. 双边窗口 [2000,4000] → 留 4000/3000/2000；有 <2000 故停
kept, stop = _filter_page(PAGE, 2000, 4000)
check("双边窗口筛选", ts_list(kept), [4000, 3000, 2000])
check("双边窗口触发停翻", stop, True)

# 5. 缺 timestamp 静默跳过
kept, stop = _filter_page(
    [{"conditionId": "x"}, {"timestamp": 4000}, {"timestamp": None}], None, None)
check("缺/None timestamp 跳过", ts_list(kept), [4000])

# 6. 老边界标志独立于入选：早于 start 的被剔除，但仍要置 stop=True
kept, stop = _filter_page([{"timestamp": 500}], 1000, None)
check("早于 start 被剔除", ts_list(kept), [])
check("早于 start 仍置停标志", stop, True)

# 7. 闭区间：等于 start/end 都算窗内
kept, stop = _filter_page(
    [{"timestamp": 4000}, {"timestamp": 2000}], 2000, 4000)
check("闭区间含端点", ts_list(kept), [4000, 2000])
check("端点不误判老边界", stop, False)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
