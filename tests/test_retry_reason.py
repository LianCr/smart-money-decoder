"""
tests/test_retry_reason.py — 扫层 _retry 按 reason 匹配（P2-28 的第三刀）

老病：recommend/hot_traders 的 _retry 用 `"429" in str(e)` 判限流——402 额度尽被
当成普通失败静默吞成 None（连日志都没有）、而任何 message 里碰巧带 "429" 字样的
错误又会被误当限流白睡 12 秒。改为按 `e.reason == "RATE_LIMITED"` 匹配。
"""

import sys
sys.path.insert(0, ".")

import recommend
import hot_traders
from fetcher.heisenberg import HeisenbergError

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


def scenario(mod, label):
    saved_sleep = mod.time.sleep
    sleeps = []
    mod.time.sleep = lambda s: sleeps.append(s)
    try:
        # 限流 → 重试后成功
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise HeisenbergError("RATE_LIMITED", "429 限流 —— 放慢/重试")
            return "ok"

        check(f"{label}: RATE_LIMITED 重试后成功", mod._retry(flaky), "ok")
        check(f"{label}: 真的重试了（3 次调用）", calls["n"], 3)
        check(f"{label}: 重试有退避", len(sleeps) >= 2, True)

        # 额度尽 → 立即放弃、不白睡（重试烧不出额度）
        sleeps.clear()
        calls = {"n": 0}

        def broke():
            calls["n"] += 1
            raise HeisenbergError("INSUFFICIENT_CREDIT", "402 —— key 额度耗尽")

        check(f"{label}: INSUFFICIENT_CREDIT → 立即 None", mod._retry(broke), None)
        check(f"{label}: 只调 1 次不重试", calls["n"], 1)
        check(f"{label}: 不白睡", sleeps, [])

        # message 碰巧含 "429" 字样但 reason 不是限流 → 不该被误当限流重试
        calls = {"n": 0}

        def tricky():
            calls["n"] += 1
            raise HeisenbergError("SERVER", "500 —— upstream said: pool 429x exhausted")

        check(f"{label}: message 含 429 字样不误判", mod._retry(tricky), None)
        check(f"{label}: 非限流只调 1 次", calls["n"], 1)
    finally:
        mod.time.sleep = saved_sleep


print("recommend._retry")
scenario(recommend, "recommend")
print("hot_traders._retry")
scenario(hot_traders, "hot_traders")

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
