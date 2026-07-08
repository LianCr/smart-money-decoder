"""
tests/test_heisenberg_guard.py — 第七道守卫纯逻辑测试（无网络）

守卫防的是"参数名写错 → API 200 静默返全局流"（错配比报错危险一个量级）。
覆盖：
  1. 返回钱包 == 请求钱包 → 放行（大小写归一）
  2. 返回钱包 ≠ 请求钱包 → WALLET_MISMATCH 拦截
  3. params 无钱包值（如 proxy_wallet="ALL" 全局）→ 不核对、放行
  4. 端点不回显钱包字段（581）→ 无从核对、放行
  5. results()：data.results / data 为 list / 脏 payload 三态
"""

import sys
sys.path.insert(0, ".")

from fetcher.heisenberg import _verify_wallet_match, results, HeisenbergError

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


W = "0x" + "a1" * 20          # 42 长合法样地址
OTHER = "0x" + "b2" * 20


def _payload(recs):
    return {"data": {"results": recs}}


# 1. 匹配（含大小写归一）→ 放行
try:
    _verify_wallet_match(556, {"proxy_wallet": W.upper().replace("0X", "0x")},
                         _payload([{"proxy_wallet": W}]))
    check("钱包匹配放行（大小写归一）", True, True)
except HeisenbergError:
    check("钱包匹配放行（大小写归一）", "raised", True)

# 2. 不匹配 → 拦截
try:
    _verify_wallet_match(556, {"proxy_wallet": W}, _payload([{"proxy_wallet": OTHER}]))
    check("钱包不匹配必须拦", "passed", "WALLET_MISMATCH")
except HeisenbergError as e:
    check("钱包不匹配必须拦", e.reason, "WALLET_MISMATCH")

# 2b. 混杂：第一条对、第二条串号 → 也要拦（防分页串结果）
try:
    _verify_wallet_match(569, {"wallet": W},
                         _payload([{"proxy_wallet": W}, {"proxy_wallet": OTHER}]))
    check("混入一条串号也要拦", "passed", "WALLET_MISMATCH")
except HeisenbergError as e:
    check("混入一条串号也要拦", e.reason, "WALLET_MISMATCH")

# 3. 参数里没有钱包样值（全局查询合法）→ 放行
try:
    _verify_wallet_match(556, {"proxy_wallet": "ALL"}, _payload([{"proxy_wallet": OTHER}]))
    check("无钱包参数（ALL 全局）不核对", True, True)
except HeisenbergError:
    check("无钱包参数（ALL 全局）不核对", "raised", True)

# 4. 581 不回显钱包字段 → 放行（无从核对）
try:
    _verify_wallet_match(581, {"proxy_wallet": W}, _payload([{"some_metric": 1}]))
    check("581 无回显字段放行", True, True)
except HeisenbergError:
    check("581 无回显字段放行", "raised", True)

# 4b. 记录里钱包字段缺失（None）→ 跳过该条不误拦
try:
    _verify_wallet_match(556, {"proxy_wallet": W}, _payload([{"proxy_wallet": None}, {}]))
    check("记录缺钱包字段不误拦", True, True)
except HeisenbergError:
    check("记录缺钱包字段不误拦", "raised", True)

# 5. results() 三态
check("results: data.results", results({"data": {"results": [1, 2]}}), [1, 2])
check("results: data 为 list", results({"data": [3]}), [3])
check("results: 脏 payload → []", results({"data": None}), [])
check("results: 非 dict payload → []", results("garbage"), [])

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
