"""
tests/test_position.py — fetcher/polymarket._is_political_event 政治判定（零网络）

（2026-08-03 瘦身：v2 /analyze 链路下架后，本文件原来测的持仓过滤专属集
（validate_wallet_address / filter_top_political_position）已随链路删除，见 git 历史。
保留 _is_political_event 的测试——backtest/pipeline.py 和多个诊断脚本仍靠它做
政治盘判定，tags 结构一变这里要先红。）

运行方法（在项目根目录）：
    python tests/test_position.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fetcher.polymarket import _is_political_event


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


def test_is_political_event():
    """政治 event 返回 True，体育 event 返回 False，畸形输入不崩溃"""
    assert _is_political_event(POLITICS_EVENT) is True
    assert _is_political_event(SPORTS_EVENT)   is False
    assert _is_political_event({})             is False   # 空 event 不崩溃
    assert _is_political_event({"tags": None}) is False   # tags=None 不崩溃
    assert _is_political_event({"tags": ["politics"]}) is False  # tag 非 dict 不崩溃（按 slug 判，不认裸串）
    print("✓ _is_political_event 判断正确")


if __name__ == "__main__":
    print("=" * 50)
    print("运行 fetcher/polymarket.py 政治判定测试")
    print("=" * 50)

    passed = 0
    failed = 0
    for t in [test_is_political_event]:
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
    sys.exit(1 if failed else 0)
