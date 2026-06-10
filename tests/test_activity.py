"""
tests/test_activity.py

测试 fetcher/activity.py 里的核心过滤逻辑。
全程不需要网络，只测纯逻辑的 _find_latest_buy。

运行方法（在项目根目录）：
    python tests/test_activity.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fetcher.activity import _find_latest_buy

TARGET_ID = "0xabc123"
OTHER_ID  = "0xother456"


def _make_record(condition_id, side, type_, timestamp=1700000000):
    """快速构造一条活动记录"""
    return {
        "conditionId": condition_id,
        "side":        side,
        "type":        type_,
        "timestamp":   timestamp,
    }


def test_normal_hit():
    """正常命中：有一条匹配的 BUY TRADE"""
    records = [_make_record(TARGET_ID, "BUY", "TRADE", 1700000000)]
    assert _find_latest_buy(records, TARGET_ID) == 1700000000
    print("✓ 正常命中，返回正确 timestamp")


def test_multiple_buys_returns_latest():
    """多条命中：返回 timestamp 最大的那条（不依赖排序）"""
    records = [
        _make_record(TARGET_ID, "BUY", "TRADE", 1700000050),
        _make_record(TARGET_ID, "BUY", "TRADE", 1700000100),  # 这条更新
        _make_record(TARGET_ID, "BUY", "TRADE", 1700000020),
    ]
    assert _find_latest_buy(records, TARGET_ID) == 1700000100
    print("✓ 多条BUY正确取最大 timestamp")


def test_sell_excluded():
    """side=SELL 应被排除"""
    records = [_make_record(TARGET_ID, "SELL", "TRADE", 1700000000)]
    assert _find_latest_buy(records, TARGET_ID) is None
    print("✓ SELL 被正确排除")


def test_redeem_excluded():
    """type=REDEEM 应被排除（即使 side=BUY）"""
    records = [_make_record(TARGET_ID, "BUY", "REDEEM", 1700000000)]
    assert _find_latest_buy(records, TARGET_ID) is None
    print("✓ REDEEM 被正确排除")


def test_different_market_excluded():
    """conditionId 不匹配应被排除"""
    records = [_make_record(OTHER_ID, "BUY", "TRADE", 1700000000)]
    assert _find_latest_buy(records, TARGET_ID) is None
    print("✓ 不同市场被正确排除")


def test_empty_list():
    """空列表返回 None，不崩溃"""
    assert _find_latest_buy([], TARGET_ID) is None
    print("✓ 空列表返回 None")


def test_missing_fields_no_crash():
    """字段缺失时用 .get() 静默跳过，不崩溃"""
    records = [
        {"conditionId": TARGET_ID},          # 缺 side / type / timestamp
        {"side": "BUY"},                      # 缺 conditionId
        {},                                   # 全空
    ]
    assert _find_latest_buy(records, TARGET_ID) is None
    print("✓ 缺字段不崩溃，返回 None")


def test_mixed_records():
    """混合场景：只有 BUY+TRADE 的目标市场记录应被选出"""
    records = [
        _make_record(TARGET_ID, "BUY",  "TRADE",  1700000200),  # ✅ 应选中
        _make_record(TARGET_ID, "SELL", "TRADE",  1700000300),  # ❌ SELL
        _make_record(TARGET_ID, "BUY",  "REDEEM", 1700000400),  # ❌ REDEEM
        _make_record(OTHER_ID,  "BUY",  "TRADE",  1700000500),  # ❌ 其他市场
    ]
    assert _find_latest_buy(records, TARGET_ID) == 1700000200
    print("✓ 混合场景正确筛选")


if __name__ == "__main__":
    tests = [
        test_normal_hit,
        test_multiple_buys_returns_latest,
        test_sell_excluded,
        test_redeem_excluded,
        test_different_market_excluded,
        test_empty_list,
        test_missing_fields_no_crash,
        test_mixed_records,
    ]

    print("=" * 50)
    print("运行 fetcher/activity.py 核心逻辑测试")
    print("=" * 50)

    passed, failed = 0, 0
    for t in tests:
        try:
            t()
            passed += 1
        except AssertionError as e:
            print(f"✗ {t.__name__} 失败：{e}")
            failed += 1
        except Exception as e:
            print(f"✗ {t.__name__} 异常：{e}")
            failed += 1

    print("=" * 50)
    print(f"结果：{passed} 通过 / {failed} 失败")
    if failed == 0:
        print("全部测试通过 ✓")
