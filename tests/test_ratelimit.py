"""
tests/test_ratelimit.py — core/ratelimit 入站闸契约（P1-15，零网络，假时钟）

背景：/dashboard 会真烧 token（完全开放的产品决策不变），但"决定开放"和
"没有任何闸"是两件事——一个循环就能把 Anthropic 额度打空。闸 = IP 滑动窗口 +
每日全局总量硬闸，阈值在 core/config.py（环境变量可调）。覆盖：
  1. 窗口内额度内 → 全放行（None）
  2. 超 per-IP 上限 → RATE_LIMITED + 人话 message + retry_after≥1
  3. 窗口滑动：时间推进后旧记录过期 → 恢复放行
  4. IP 隔离：A 打满不影响 B
  5. 被拒的请求不消耗每日全局额度（拒绝是免费的）
  6. 每日全局硬闸：跨 IP 总量打满 → 新 IP 也 DAILY_LIMIT_REACHED
  7. 跨天翻转：全局计数归零、恢复放行
  8. 阈值常量在 core/config.py、正整数
（原"api 层 429 wiring 无法直测"的欠条已于 T2.3 撕掉：import api.main 零副作用后端点
可直测，见 tests/test_api_endpoints.py。本文件继续钉 core/ratelimit 纯逻辑契约。）
"""

import sys

sys.path.insert(0, ".")

from core.ratelimit import RateLimiter

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


class Clock:
    """假时钟：从固定纪元起手动推进（2026-08-03 00:00 UTC = 1785715200）。"""
    def __init__(self, t=1785715200.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, sec):
        self.t += sec


# ── 1/2. 额度内放行；超限 RATE_LIMITED ───────────────────────────────────────
print("per-IP 滑动窗口")
clk = Clock()
rl = RateLimiter(per_ip_max=3, window_seconds=60, daily_max=100, clock=clk)
check("额度内第 1 次放行", rl.check("1.1.1.1"), None)
check("额度内第 3 次放行", (rl.check("1.1.1.1"), rl.check("1.1.1.1")), (None, None))
d = rl.check("1.1.1.1")
check("第 4 次被拒 → RATE_LIMITED", d and d.get("error"), "RATE_LIMITED")
check("拒绝带人话 message", bool(d and d.get("message")), True)
check("拒绝带 retry_after ≥1", isinstance(d.get("retry_after"), int) and d["retry_after"] >= 1, True)
check("retry_after ≤ 窗口长", d["retry_after"] <= 60, True)

# ── 3. 窗口滑动 ─────────────────────────────────────────────────────────────
clk.advance(61)                              # 三条记录全部滑出窗口
check("窗口滑过 → 恢复放行", rl.check("1.1.1.1"), None)
clk.advance(30)
check("半窗口后仍有余量", rl.check("1.1.1.1"), None)
rl.check("1.1.1.1")                          # 第 3 次（窗口内共 3 条）
d = rl.check("1.1.1.1")
check("窗口内再次打满被拒", d and d.get("error"), "RATE_LIMITED")
clk.advance(31)                              # 最早那条（61s 前 advance 后的）滑出
check("部分滑出 → 放行 1 个名额", rl.check("1.1.1.1"), None)

# ── 4. IP 隔离 ──────────────────────────────────────────────────────────────
print("IP 隔离")
clk2 = Clock()
rl2 = RateLimiter(per_ip_max=2, window_seconds=60, daily_max=100, clock=clk2)
rl2.check("2.2.2.2"); rl2.check("2.2.2.2")
check("A 打满被拒", rl2.check("2.2.2.2") is not None, True)
check("B 不受 A 影响", rl2.check("3.3.3.3"), None)

# ── 5/6. 每日全局硬闸 ───────────────────────────────────────────────────────
print("每日全局硬闸")
clk3 = Clock()
rl3 = RateLimiter(per_ip_max=100, window_seconds=60, daily_max=4, clock=clk3)
for i in range(4):
    check(f"全局额度内第 {i+1} 次放行（各异 IP）", rl3.check(f"10.0.0.{i}"), None)
d = rl3.check("10.0.0.99")
check("全局打满 → 新 IP 也被拒 DAILY_LIMIT_REACHED", d and d.get("error"), "DAILY_LIMIT_REACHED")
check("全局拒绝带人话 message", bool(d and d.get("message")), True)
check("全局拒绝 retry_after = 到明天的秒数（≤86400）",
      isinstance(d.get("retry_after"), int) and 1 <= d["retry_after"] <= 86400, True)

# 5. 被拒的请求不消耗全局额度：per-IP 拒绝无数次后，别的 IP 额度不变
clk4 = Clock()
rl4 = RateLimiter(per_ip_max=1, window_seconds=60, daily_max=3, clock=clk4)
rl4.check("5.5.5.5")                         # 消耗全局 1/3
for _ in range(10):
    rl4.check("5.5.5.5")                     # 全部被 per-IP 拒 → 不该碰全局计数
check("被拒请求不消耗全局额度（还剩 2 个名额）",
      (rl4.check("6.6.6.6"), rl4.check("7.7.7.7")), (None, None))
check("全局余额此刻才真打满", rl4.check("8.8.8.8") and rl4.check("8.8.8.8").get("error"),
      "DAILY_LIMIT_REACHED")

# ── 7. 跨天翻转 ─────────────────────────────────────────────────────────────
print("跨天翻转")
clk3.advance(86400)                          # 到第二天（UTC）
check("翻天 → 全局计数归零恢复放行", rl3.check("10.0.0.99"), None)

# ── 8. 阈值在 core/config.py ────────────────────────────────────────────────
print("config 常量")
from core import config
for name in ("RATE_LIMIT_PER_IP", "RATE_LIMIT_WINDOW_SECONDS", "RATE_LIMIT_DAILY_GLOBAL"):
    v = getattr(config, name, None)
    check(f"{name} 是正整数", isinstance(v, int) and v > 0, True)
check("默认阈值对正常浏览宽松（per-IP ≥ 10/窗口）", config.RATE_LIMIT_PER_IP >= 10, True)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
