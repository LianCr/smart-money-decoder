"""
tests/test_credibility.py — F4 可信度分契约（纯代码零 LLM 零网络）

钉死的契约（对应 scoring/credibility.py 红线头；T2.2 从 analyzer/ 迁入）：
  1. 扣分制只扣不加：起点 100，每子指标按表扣、各设上限防重复计罪，floor 0。
  2. 缺数据诚实：575 整体缺 → score/tier 双 null（绝不装 100 也不装 0）；
     单子指标缺 → verdict="missing"、不扣分、partial=true。
  3. 🔴 评价信号、永不修理判断：入参 dict 出现 market_lean/confidence/rationale
     任一 key → raise ValueError；模块源码零判断字段访问、零业务模块 import；
     同硬指标在不同判断上下文下输出逐字节一致（不变性）。
  4. self_check 本场 info-only 不计分；guard_cross 样本不足如实标注。
  5. 真样本标定：三份 .cache/market_thesis 实测数据按表得 100/A、85/B、75/B
     ——旧 trust 逻辑对这三盘全给 HIGH，矛盾读数从此摊开。
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, ".")

from scoring.credibility import build_credibility

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


def raw(pct=99.0, top1=10.0, top10=40.0, uniq=1000, trend="Stable", flags=None, **kw):
    d = {"liquidity_percentile": pct, "top1_wallet_pct": top1, "top10_wallet_pct": top10,
         "unique_traders_7d": uniq, "volume_trend": trend, "flags": flags or []}
    d.update(kw)
    return d


def sub(c, key):
    return next(s for s in c["subs"] if s["key"] == key)


# ── 1. 每子指标正负样本 + 边界 ───────────────────────────────────────────────
print("子指标边界")
c = build_credibility(raw(), 0.03)
check("深盘全好 → 100 分 A 档零扣", (c["score"], c["tier"]), (100, "A"))
check("全子指标 verdict=ok（self_check 除外）",
      [s["verdict"] for s in c["subs"] if s["key"] != "self_check"],
      ["ok", "ok", "ok", "ok", "ok"])
check("deterministic 标注", c["deterministic"], True)
check("partial=False", c["partial"], False)

c = build_credibility(raw(pct=49), 0.03)
check("流动性 pct<50 → −25", sub(c, "liquidity")["delta"], -25)
c = build_credibility(raw(pct=84.9), 0.03)
check("流动性 50≤pct<85 → −10", sub(c, "liquidity")["delta"], -10)
c = build_credibility(raw(pct=85), 0.03)
check("流动性 pct=85 边界 → 0", sub(c, "liquidity")["delta"], 0)
c = build_credibility(raw(pct=49, flags=["liquidity_risk_flag"]), 0.03)
check("流动性 cap：pct<50 + risk_flag 合计封 −25", sub(c, "liquidity")["delta"], -25)

c = build_credibility(raw(top1=35), 0.03)
check("集中度 top1=35 边界 → −15", sub(c, "concentration")["delta"], -15)
c = build_credibility(raw(top1=34.9), 0.03)
check("集中度 top1<35 → 0", sub(c, "concentration")["delta"], 0)
c = build_credibility(raw(top10=70), 0.03)
check("集中度 top10=70 边界 → −10", sub(c, "concentration")["delta"], -10)
c = build_credibility(raw(top1=40, top10=80,
                          flags=["whale_control_flag", "trade_concentration_flag", "squeeze_risk_flag"]), 0.03)
check("集中度 cap：五罪并罚封 −30", sub(c, "concentration")["delta"], -30)

c = build_credibility(raw(uniq=29), 0.03)
check("参与 uniq<30 → −20", sub(c, "participants")["delta"], -20)
c = build_credibility(raw(uniq=79), 0.03)
check("参与 30≤uniq<80 → −10", sub(c, "participants")["delta"], -10)
c = build_credibility(raw(uniq=80), 0.03)
check("参与 uniq=80 边界 → 0", sub(c, "participants")["delta"], 0)

c = build_credibility(raw(trend="Significant Decline", flags=["volume_collapse_risk_flag"]), 0.03)
check("量能：collapse flag −10 + Significant Decline −5", sub(c, "volume")["delta"], -15)

c = build_credibility(raw(), 0.12)
check("犹豫度 vol=0.12 边界 → −15", sub(c, "volatility")["delta"], -15)
c = build_credibility(raw(), 0.06)
check("犹豫度 vol=0.06 边界 → −5", sub(c, "volatility")["delta"], -5)
c = build_credibility(raw(), 0.059)
check("犹豫度 vol<0.06 → 0", sub(c, "volatility")["delta"], 0)

# ── 2. 合成边界 + 真样本标定 ─────────────────────────────────────────────────
print("合成 + 真样本标定")
c = build_credibility(raw(pct=10, top1=90, top10=99, uniq=5, trend="Significant Decline",
                          flags=["liquidity_risk_flag", "whale_control_flag",
                                 "trade_concentration_flag", "squeeze_risk_flag",
                                 "volume_collapse_risk_flag"]), 0.3)
check("全坏盘 floor 0 不穿底", c["score"], 0)
check("全坏盘 F 档", c["tier"], "F")

# 档位带边界（构造精确分数：只动犹豫度/量能等小扣分项凑分）
c = build_credibility(raw(pct=84.9), 0.03)           # −10 → 90
check("90 分 = A 档下边界", (c["score"], c["tier"]), (90, "A"))
c = build_credibility(raw(pct=84.9), 0.06)           # −10−5 → 85
check("85 分 = B 档", (c["score"], c["tier"]), (85, "B"))
c = build_credibility(raw(pct=84.9, uniq=79), 0.06)  # −10−10−5 → 75
check("75 分 = B 档下边界", (c["score"], c["tier"]), (75, "B"))
c = build_credibility(raw(pct=84.9, uniq=79), 0.12)  # −10−10−15 → 65
check("65 分 = C 档", (c["score"], c["tier"]), (65, "C"))
c = build_credibility(raw(pct=49, uniq=79, top1=35), 0.03)  # −25−10−15 → 50
check("50 分 = D 档", (c["score"], c["tier"]), (50, "D"))

# 三份 .cache/market_thesis 真样本（字段值照抄缓存实测）
s1 = build_credibility(raw(pct=98.93, top1=14.01, top10=45.94, uniq=3000, trend="Declining"), 0.0256)
check("真样本1（Iran 深盘共识稳）→ 100/A", (s1["score"], s1["tier"]), (100, "A"))
s2 = build_credibility(raw(pct=97.21, top1=13.63, top10=50.0, uniq=1142, trend="Significant Decline",
                           flags=["volume_collapse_risk_flag"]), 0.03)
check("真样本2（量能塌缩）→ 85/B", (s2["score"], s2["tier"]), (85, "B"))
s3 = build_credibility(raw(pct=99.38, top1=20.78, top10=73.33, uniq=977, trend="Declining"), 0.226)
check("真样本3（top10=73%+高犹豫，旧逻辑也给 HIGH）→ 75/B", (s3["score"], s3["tier"]), (75, "B"))

# ── 3. 缺数据诚实 ────────────────────────────────────────────────────────────
print("缺数据")
c = build_credibility(None, 0.03)
check("575 全缺 → score null（非 0 非 100）", c["score"], None)
check("575 全缺 → tier null", c["tier"], None)
check("575 全缺仍出 subs（全 missing 可见）",
      all(s["verdict"] == "missing" for s in c["subs"] if s["key"] != "self_check"), True)

c = build_credibility(raw(), None)
check("568 缺 → volatility 子 missing", sub(c, "volatility")["verdict"], "missing")
check("568 缺 → 不扣分", sub(c, "volatility")["delta"], 0)
check("568 缺 → partial=True", c["partial"], True)
check("568 缺 → 其余照算（score=100）", c["score"], 100)

c = build_credibility({"liquidity_percentile": 99.0, "top1_wallet_pct": 10.0,
                       "unique_traders_7d": 1000, "volume_trend": "Stable", "flags": []}, 0.03)
check("旧缓存无 top10 → 集中度仍按 top1 算（不整体 missing）", sub(c, "concentration")["verdict"], "ok")

# ── 4. 🔴 红线：评价信号、永不修理判断 ──────────────────────────────────────
print("红线：不碰判断")
for bad_key in ("market_lean", "confidence", "rationale"):
    try:
        build_credibility({**raw(), bad_key: "x"}, 0.03)
        check(f"入参含 {bad_key} → raise ValueError", "没抛", "ValueError")
    except ValueError:
        check(f"入参含 {bad_key} → raise ValueError", "ValueError", "ValueError")
try:
    build_credibility(raw(), 0.03, guard_cross={"market_lean": "YES"})
    check("guard_cross 含判断字段 → raise", "没抛", "ValueError")
except ValueError:
    check("guard_cross 含判断字段 → raise", "ValueError", "ValueError")

src = Path("scoring/credibility.py").read_text(encoding="utf-8")
for tok in ("market_lean", "confidence", "rationale"):
    check(f"源码零判断字段访问（.get/[] {tok}）",
          (f'.get("{tok}"' in src) or (f"['{tok}']" in src) or (f'["{tok}"]' in src), False)
check("源码零业务模块 import（market_thesis/reasoner/llm/decoder）",
      any(t in src for t in ("market_thesis", "reasoner", "core.llm", "decoder")), False)
check("源码零 IO import（requests/pathlib 落盘不该出现）",
      any(t in src for t in ("import requests", "atomic_write", "open(")), False)

# 不变性：同硬指标 → 输出逐字节一致（判断上下文根本进不了签名，这里钉住可复现性）
a = json.dumps(build_credibility(raw(), 0.03, guard_flags=["DURATION_COMPUTED"]), sort_keys=True)
b = json.dumps(build_credibility(raw(), 0.03, guard_flags=["DURATION_COMPUTED"]), sort_keys=True)
check("同输入两次调用逐字节一致", a == b, True)

# ── 5. self_check（info-only）+ 透传字段 ────────────────────────────────────
print("self_check + 透传")
c = build_credibility(raw(), 0.03, guard_flags=["DURATION_COMPUTED"],
                      guard_cross={"flagged": {"n": 0, "hits": 0, "insufficient": True, "hit_rate_pct": None},
                                   "clean": {"n": 0, "hits": 0, "insufficient": True, "hit_rate_pct": None}})
sc = sub(c, "self_check")
check("self_check verdict=info（不计分）", sc["verdict"], "info")
check("self_check delta=0", sc["delta"], 0)
check("本次 guard_flags 数在 raw", sc["raw"]["guard_flags_n"], 1)
check("样本不足如实标注", sc["raw"]["insufficient"], True)
check("guard 触发不影响分数", c["score"], 100)

c2 = build_credibility(raw(), 0.03, guard_cross={"flagged": {"n": 6, "hits": 3, "insufficient": False, "hit_rate_pct": 50.0},
                                                 "clean": {"n": 8, "hits": 7, "insufficient": False, "hit_rate_pct": 87.5}})
sc2 = sub(c2, "self_check")
check("样本充足时命中率透传", (sc2["raw"]["flagged"], sc2["raw"]["clean"]), (50.0, 87.5))
check("insufficient=False", sc2["raw"]["insufficient"], False)
check("即便样本充足本场仍不计分（MVP 契约）", sc2["delta"], 0)

c = build_credibility(raw(flags=["squeeze_risk_flag"]), 0.03, days_to_resolution=97)
check("days_to_resolution 透传", c["days_to_resolution"], 97)
check("risk_flags 透传", c["risk_flags"], ["squeeze_risk_flag"])

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
