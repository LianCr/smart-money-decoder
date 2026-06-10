"""
tests/test_position.py

测试 fetcher/polymarket.py 里的核心过滤逻辑。
全程不需要网络，用 mock 数据即可验证逻辑是否正确。

运行方法（在项目根目录）：
    python tests/test_position.py
"""

import sys
import os

# 让 Python 能找到上级目录的 fetcher 包
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fetcher.polymarket import (
    validate_wallet_address,
    filter_top_political_position,
    _is_political_event,
)


# ══════════════════════════════════════════════════════════════════════════════
# Mock 数据：模拟真实 API 返回的结构
# ══════════════════════════════════════════════════════════════════════════════

# 政治类 event（含 politics tag）
POLITICS_EVENT = {
    "id": "1001",
    "title": "Will Trump win the 2024 election?",
    "tags": [
        {"id": "2",  "label": "Politics",   "slug": "politics"},
        {"id": "5",  "label": "US Election", "slug": "us-election"},
    ],
}

# 体育类 event（不含 politics tag）
SPORTS_EVENT = {
    "id": "2001",
    "title": "Will Lakers win the NBA Finals?",
    "tags": [
        {"id": "10", "label": "Sports", "slug": "sports"},
        {"id": "11", "label": "NBA",    "slug": "nba"},
    ],
}

# events_map 模拟 fetch_events_by_ids 的返回值
EVENTS_MAP = {
    "1001": POLITICS_EVENT,
    "2001": SPORTS_EVENT,
}

# ── 各种仓位 mock ──────────────────────────────────────────────────────────────

def _make_pos(condition_id, event_id, current_value, redeemable=False):
    """快速构造一个仓位字典，避免重复写大量字段"""
    return {
        "conditionId":  condition_id,
        "title":        "Mock Market",
        "outcome":      "Yes",
        "size":         current_value / 0.8,
        "avgPrice":     0.55,
        "curPrice":     0.80,
        "currentValue": current_value,
        "cashPnl":      current_value * 0.1,
        "percentPnl":   10.0,
        "eventId":      event_id,
        "eventSlug":    "mock-slug",
        "redeemable":   redeemable,
    }

# 大政治仓位 $8,000（应被选中）
POS_BIG_POLITICS   = _make_pos("0xbbb", "1001", 8000.0)

# 小政治仓位 $200（低于 $5,000 阈值，应被过滤）
POS_SMALL_POLITICS = _make_pos("0xccc", "1001", 200.0)

# 大体育仓位 $10,000（不是政治类，应被过滤）
POS_BIG_SPORTS     = _make_pos("0xddd", "2001", 10000.0)

# 已结算的政治仓位 $6,000（redeemable=True，应被过滤）
POS_SETTLED        = _make_pos("0xeee", "1001", 6000.0, redeemable=True)

# 更大的政治仓位 $12,000（用于测试"选最大"逻辑）
POS_BIGGEST        = _make_pos("0xfff", "1001", 12000.0)


# ══════════════════════════════════════════════════════════════════════════════
# 测试函数
# ══════════════════════════════════════════════════════════════════════════════

def test_validate_address_valid():
    """正常地址：应返回小写版本"""
    result = validate_wallet_address("0xF8831548531D56Ad6a4331493243C447a827cd1F")
    assert result == "0xf8831548531d56ad6a4331493243c447a827cd1f"
    print("✓ 正常地址验证通过")


def test_validate_address_too_short():
    """地址太短：应抛 ValueError"""
    try:
        validate_wallet_address("0x1234")
        assert False, "没有抛出异常"
    except ValueError:
        print("✓ 过短地址正确拒绝")


def test_validate_address_wrong_prefix():
    """不是 0x 开头：应抛 ValueError"""
    try:
        validate_wallet_address("1xf8831548531d56ad6a4331493243c447a827cd1f")
        assert False, "没有抛出异常"
    except ValueError:
        print("✓ 错误前缀正确拒绝")


def test_validate_address_non_hex():
    """含非十六进制字符（如 G）：应抛 ValueError"""
    try:
        validate_wallet_address("0xGGGG1548531d56ad6a4331493243c447a827cd1f")
        assert False, "没有抛出异常"
    except ValueError:
        print("✓ 非十六进制字符正确拒绝")


def test_normal_case():
    """正常情况：有大政治仓位，应该选出来"""
    positions = [POS_BIG_POLITICS, POS_SMALL_POLITICS, POS_BIG_SPORTS]
    result = filter_top_political_position(positions, EVENTS_MAP)

    assert result is not None, "应该找到一个仓位"
    assert result["conditionId"] == "0xbbb", f"预期 0xbbb，实际 {result['conditionId']}"
    print("✓ 正常情况：正确选出大政治仓位")


def test_no_political_positions():
    """只有体育盘，应返回 None"""
    result = filter_top_political_position([POS_BIG_SPORTS], EVENTS_MAP)
    assert result is None, "没有政治盘时应返回 None"
    print("✓ 无政治盘：正确返回 None")


def test_all_below_threshold():
    """政治盘全低于 $5,000，应返回 None"""
    result = filter_top_political_position([POS_SMALL_POLITICS], EVENTS_MAP)
    assert result is None, "仓位不足 $5000 时应返回 None"
    print("✓ 全部低于阈值：正确返回 None")


def test_settled_excluded():
    """已结算仓位（redeemable=True）不应被选中"""
    result = filter_top_political_position([POS_SETTLED], EVENTS_MAP)
    assert result is None, "已结算仓位应被过滤"
    print("✓ 已结算仓位正确过滤")


def test_picks_largest():
    """多个合格政治仓位时，选价值最大的"""
    positions = [POS_BIG_POLITICS, POS_BIGGEST, POS_SMALL_POLITICS]
    result = filter_top_political_position(positions, EVENTS_MAP)

    assert result is not None
    assert result["conditionId"] == "0xfff", \
        f"应选 $12,000 的仓位(0xfff)，实际选了 {result['conditionId']}"
    print("✓ 多仓位时正确选出最大值")


def test_is_political_event():
    """辅助函数：政治 event 返回 True，体育 event 返回 False"""
    assert _is_political_event(POLITICS_EVENT) is True
    assert _is_political_event(SPORTS_EVENT)   is False
    assert _is_political_event({})             is False  # 空 event 不崩溃
    print("✓ _is_political_event 判断正确")


# ══════════════════════════════════════════════════════════════════════════════
# 运行入口
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    tests = [
        test_validate_address_valid,
        test_validate_address_too_short,
        test_validate_address_wrong_prefix,
        test_validate_address_non_hex,
        test_is_political_event,
        test_normal_case,
        test_no_political_positions,
        test_all_below_threshold,
        test_settled_excluded,
        test_picks_largest,
    ]

    print("=" * 50)
    print("运行 fetcher/polymarket.py 核心逻辑测试")
    print("=" * 50)

    passed = 0
    failed = 0
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
