"""
tests/test_reasoner_v3.py — v3 置信度矩阵纯逻辑测试（无网络）

矩阵是 ⑥ facts 的代码底座（只降不升是它的灵魂）。覆盖：
  1. 底座：证据空→low / pnl>60→low / 浮亏→medium / pnl None→medium / <30→high
  2. R1 市场测谎：支持侧全被反向定价→low；部分→medium
  3. R2 对冲：两侧均衡→封 medium
  4. R3 近48h大额退出→封 medium
  5. R4 双空→low
  6. 只降不升不变量：任何规则组合下结果 ≤ 底座
  7. classify_position_type / classify_recent_action 枚举映射
"""

import sys
sys.path.insert(0, ".")

from analyzer.reasoner_v3 import (
    compute_confidence_v3, classify_position_type, classify_recent_action, CONF_ORDER,
)

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


def conf(**kw):
    base = dict(support=[{"title": "s", "market_reaction": "confirmed"}],
                threat=[], pnl_pct=10, time_anchored=True,
                by_outcome=None, held_outcome="Yes", recent_action="flat_no_movement")
    base.update(kw)
    c, reasons = compute_confidence_v3(**base)
    return c


# ── 1. 底座矩阵 ───────────────────────────────────────────────────────────────
check("健康仓：有证据+0≤pnl<30 → high", conf(), "high")
check("pnl>60 涨幅吃透 → low", conf(pnl_pct=75), "low")
check("30≤pnl<60 → medium", conf(pnl_pct=45), "medium")
check("浮亏 → 封 medium", conf(pnl_pct=-5), "medium")
check("浮亏+未锚 → low", conf(pnl_pct=-5, time_anchored=False), "low")
check("pnl None 缺失保守 → medium", conf(pnl_pct=None), "medium")
check("v3 删 rule5：未锚不再降级（pnl 健康仍 high）", conf(time_anchored=False), "high")

# ── 2. R1 市场测谎 ───────────────────────────────────────────────────────────
check("R1 支持侧全被反向定价 → low",
      conf(support=[{"title": "a", "market_reaction": "rejected"}]), "low")
check("R1 部分被反向定价 → 封 medium",
      conf(support=[{"title": "a", "market_reaction": "rejected"},
                    {"title": "b", "market_reaction": "confirmed"}]), "medium")

# ── 3. R2 对冲（主仓 < 另一侧×3 = 均衡）───────────────────────────────────────
by = {"Yes": {"shares": 100}, "No": {"shares": 80}}
check("R2 两侧均衡 → 封 medium", conf(by_outcome=by), "medium")
by_lopsided = {"Yes": {"shares": 1000}, "No": {"shares": 10}}
check("R2 一边倒（≥3×）不触发 → high", conf(by_outcome=by_lopsided), "high")

# ── 4. R3 近48h大额退出 ───────────────────────────────────────────────────────
check("R3 clear_exit → 封 medium", conf(recent_action="clear_exit"), "medium")

# ── 5. R4 证据双空 ────────────────────────────────────────────────────────────
check("R4 支持/威胁双空 → low", conf(support=[], threat=[]), "low")

# ── 6. 只降不升不变量：把所有触发条件叠上，结果必须 ≤ 每个单独结果 ───────────────
worst = conf(support=[{"title": "a", "market_reaction": "rejected"}],
             by_outcome=by, recent_action="clear_exit", pnl_pct=-10, time_anchored=False)
check("规则全叠加 → low（只降不升）", worst, "low")
check("CONF_ORDER 顺序完整", sorted(CONF_ORDER, key=CONF_ORDER.get), ["low", "medium", "high"])

# ── 7. 枚举映射 ───────────────────────────────────────────────────────────────
check("单边仓 → single_side_conviction",
      classify_position_type({"hedged": False, "by_outcome": by}, "Yes"), "single_side_conviction")
check("两边接近 → market_making",
      classify_position_type({"hedged": True, "by_outcome": by}, "Yes"), "market_making")
check("对冲但悬殊 → hedged",
      classify_position_type({"hedged": True, "by_outcome": {"Yes": {"shares": 100}, "No": {"shares": 20}}}, "Yes"),
      "hedged")
check("flag ADD → adding", classify_recent_action({"flag": "ADD"}), "adding")
check("flag EXIT → clear_exit（进 R3）", classify_recent_action({"flag": "EXIT"}), "clear_exit")
check("flag STATIC → flat", classify_recent_action({"flag": "STATIC"}), "flat_no_movement")
check("flag 空 → flat", classify_recent_action(None), "flat_no_movement")

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
