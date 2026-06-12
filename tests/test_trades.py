"""
tests/test_trades.py — fetcher/trades.py 纯逻辑 mock 测试（无网络）

只测 _earliest_buy 的过滤与取最早逻辑，覆盖：
  1. 空结果 → None
  2. 多条 BUY 取最早（min 时间戳）
  3. 全 SELL 无 BUY → None
  4. 字段缺失不崩
  5. 混入别的 conditionId 要被排除
"""

import sys
sys.path.insert(0, ".")

from fetcher.trades import _earliest_buy

CID = "0xabc"
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


# 1. 空结果
check("空列表 → None", _earliest_buy([], CID), None)

# 2. 多条 BUY 取最早（min）
records = [
    {"conditionId": CID, "side": "BUY", "timestamp": 3000},
    {"conditionId": CID, "side": "BUY", "timestamp": 1000},  # 最早
    {"conditionId": CID, "side": "BUY", "timestamp": 2000},
]
check("多条 BUY 取最早=1000", _earliest_buy(records, CID), 1000)

# 3. 全 SELL → None
records = [
    {"conditionId": CID, "side": "SELL", "timestamp": 1000},
    {"conditionId": CID, "side": "SELL", "timestamp": 2000},
]
check("全 SELL → None", _earliest_buy(records, CID), None)

# 4. 字段缺失不崩（缺 timestamp / 缺 side / 空 dict）
records = [
    {"conditionId": CID, "side": "BUY"},                 # 缺 timestamp，跳过
    {"conditionId": CID, "timestamp": 5000},             # 缺 side，跳过
    {},                                                  # 空 dict，跳过
    {"conditionId": CID, "side": "BUY", "timestamp": 4000},  # 唯一有效
]
check("字段缺失不崩，取唯一有效=4000", _earliest_buy(records, CID), 4000)

# 5. 别的 conditionId 要被排除
records = [
    {"conditionId": "0xother", "side": "BUY", "timestamp": 500},   # 别的市场，排除
    {"conditionId": CID,       "side": "BUY", "timestamp": 1500},
]
check("混入别的 cid 被排除，取 1500", _earliest_buy(records, CID), 1500)

# 6. SELL 早于 BUY，但只认 BUY 的最早
records = [
    {"conditionId": CID, "side": "SELL", "timestamp": 100},   # 更早但是 SELL
    {"conditionId": CID, "side": "BUY",  "timestamp": 800},
    {"conditionId": CID, "side": "BUY",  "timestamp": 1200},
]
check("SELL 更早也忽略，取最早 BUY=800", _earliest_buy(records, CID), 800)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
