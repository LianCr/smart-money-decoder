"""
tests/test_reaction_volume.py — 反应符号薄量加权（T2 ③）+ 中文串互锁保险丝

口径边界（用户拍板的答案，本测试就是机器化的边界声明）：
  1. 薄量加权**只动 Path B**（board_feed._reaction → ⑤ 展示层）：反应窗合计量 <
     VOLUME_THIN 时 "confirm"→"weak"（薄量印证不作数）；**"reject" 绝不降级**、只带
     thin 标注（警报不因薄量打折）——只降不升同向。
  2. **Path A 零触碰**：_market_check 的三个中文串（印证/不一致/微弱）一字不变，
     reasoner_v3._market_reaction 的子串匹配与 R1 矩阵输入不变——互锁契约钉死
     （此前无任何测试覆盖这条线，改一个字=R1 静默断、全套照绿）。
  3. compute_reaction 换 candles_range 单次取数：market_check 判定逐字节不变、
     as_of 防泄漏守卫不变、window_volume 白拿。
"""

import sys

sys.path.insert(0, ".")

import analyzer.price_reaction as pr
import briefing.board_feed as bf
from scoring.reasoner_v3 import _market_reaction
from scoring.constants import VOLUME_THIN

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


def fake_candles(spec):
    """spec: {date: (close, volume)} → candles_range 替身。"""
    def _f(token_id, start, end):
        return [{"date": d, "close": c, "volume": v} for d, (c, v) in sorted(spec.items())]
    return _f


# ── 1. compute_reaction：单次取数 + window_volume，market_check 逐字节不变 ────
print("compute_reaction（Path A 原样）")
_saved = pr.candles_range
pr.candles_range = fake_candles({"2026-08-01": (0.50, 300.0), "2026-08-02": (0.60, 400.0),
                                 "2026-08-03": (0.56, 200.0)})
try:
    r = pr.compute_reaction("tok", "2026-08-02")
    check("move_pct = (0.56-0.50)/0.50 = 12%", r["move_pct"], 12.0)
    check("window_volume = 三日合计 900", r["window_volume"], 900.0)
    check("direction ▲", r["direction"], "▲")
    mc_pos = pr._market_check(r, "positive")
    mc_neg = pr._market_check(r, "negative")
    check("🔴 market_check 印证串逐字节不变", mc_pos, "市场印证该分类")
    check("🔴 market_check 不一致串逐字节不变", mc_neg, "⚠️市场反应与该分类不一致")
    weak = dict(r); weak["move_pct"] = 2.0
    check("🔴 market_check 微弱串逐字节不变", pr._market_check(weak, "positive"),
          "市场反应微弱(<5%)")

    check("as_of 防泄漏守卫不变", pr.compute_reaction("tok", "2026-08-02", as_of="2026-08-02")["available"], False)
    pr.candles_range = fake_candles({})
    check("无价 → no_price 不编造", pr.compute_reaction("tok", "2026-08-02")["reason"], "no_price")
finally:
    pr.candles_range = _saved

# ── 2. 互锁保险丝：market_check 串 ↔ _market_reaction 子串匹配 ───────────────
print("中文串互锁（R1 的保险丝）")
mk = {"available": True, "market_check": "市场印证该分类"}
check("印证 → confirmed（R1 输入）", _market_reaction({"price_reaction": mk}), "confirmed")
mk = {"available": True, "market_check": "⚠️市场反应与该分类不一致"}
check("不一致 → rejected（R1 唯一降级触发器）", _market_reaction({"price_reaction": mk}), "rejected")
mk = {"available": True, "market_check": "市场反应微弱(<5%)"}
check("微弱 → weak", _market_reaction({"price_reaction": mk}), "weak")
check("不可用 → unknown", _market_reaction({"price_reaction": {"available": False}}), "unknown")

# ── 3. Path B 薄量加权（只降不升）────────────────────────────────────────────
print("board_feed._reaction 薄量")
_saved_cr = bf.compute_reaction


def fake_reaction(mv, wv):
    return lambda tok, date, as_of=None: {"available": True, "move_pct": mv,
                                          "window_volume": wv, "window": ["a", "b"]}


try:
    bf.compute_reaction = fake_reaction(12.0, VOLUME_THIN - 1)
    r = bf._reaction("tok", "2026-08-02", None)
    check("🔴 薄量 + 印证 → 降为 weak（印证不作数）", r["kind"], "weak")
    check("thin 标注", r["thin"], True)

    bf.compute_reaction = fake_reaction(-12.0, VOLUME_THIN - 1)
    r = bf._reaction("tok", "2026-08-02", None)
    check("🔴 薄量 + 不买账 → 绝不降级（警报不打折）", r["kind"], "reject")
    check("不买账仍带 thin 标注", r["thin"], True)

    bf.compute_reaction = fake_reaction(12.0, VOLUME_THIN)
    r = bf._reaction("tok", "2026-08-02", None)
    check("量在线上 → 印证不降", r["kind"], "confirm")
    check("量在线上 → thin=False", r["thin"], False)

    bf.compute_reaction = fake_reaction(12.0, None)
    r = bf._reaction("tok", "2026-08-02", None)
    check("量未知（旧路径/无数据）→ 不降不标（缺席≠薄）", (r["kind"], r["thin"]), ("confirm", False))

    bf.compute_reaction = fake_reaction(2.0, VOLUME_THIN - 1)
    r = bf._reaction("tok", "2026-08-02", None)
    check("本就微弱 + 薄量 → weak+thin", (r["kind"], r["thin"]), ("weak", True))
finally:
    bf.compute_reaction = _saved_cr

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
