"""
tests/test_recommend_quality.py — 推荐质量门的 T1 增强（F-Score join + 反作弊旗标）

契约（红线：质量门**只降不升**）：
  1. _hscore_map：584 榜 sweep → {wallet: {h_score, tier}}（小写归一、短页即停）。
     🔴 584 无按地址过滤（坑表 2026-08-07）——top-N 外的钱包如实缺席，**缺席≠低分、不惩罚**。
  2. _hscore_penalty：h_score < FSCORE_LOW → REC_PENALTY_LOW_FSCORE；≥线 → 0（绝无加分）；
     缺席(None) → 0。
  3. _anomaly_flags：581 quality dict → 为真的旗标名列表（五旗标 + 只认布尔真值）。
  4. _anomaly_penalty：有旗标 → REC_PENALTY_ANOMALY 一次性（不按旗标数叠加——首版保守）；
     无旗标/quality 缺失 → 0。
"""

import sys
sys.path.insert(0, ".")

import recommend
from scoring.constants import (FSCORE_LOW, REC_PENALTY_LOW_FSCORE, REC_PENALTY_ANOMALY)

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


# ── 1. _hscore_map：sweep + 归一 ────────────────────────────────────────────
print("_hscore_map")
WA, WB = "0x" + "A" * 40, "0x" + "b" * 40
PAGES = [
    [{"wallet": WA, "h_score": "74.976", "tier": "Elite"}] * 1 +
    [{"wallet": "not-a-wallet", "h_score": "50", "tier": "Skilled"}] +
    [{"wallet": WB, "h_score": "33.2", "tier": "Novice"}],   # 短页（<200）→ 停止翻页
]
_calls = []


def fake_call(agent_id, params, limit=200, offset=0):
    _calls.append({"agent_id": agent_id, "offset": offset})
    page = PAGES[offset // 200] if offset // 200 < len(PAGES) else []
    return {"data": {"results": page}}


_saved = recommend.call
recommend.call = fake_call
try:
    m = recommend._hscore_map(pages=3)
finally:
    recommend.call = _saved

check("打的是 584", _calls[0]["agent_id"], 584)
check("短页即停（只翻 1 页）", len(_calls), 1)
check("钱包小写归一", WA.lower() in m, True)
check("h_score 数值化", m[WA.lower()]["h_score"], 74.976)
check("tier 透传", m[WA.lower()]["tier"], "Elite")
check("非钱包行剔除", len(m), 2)

# ── 2. _hscore_penalty：只降不升 ────────────────────────────────────────────
print("_hscore_penalty")
check("低于线（39.9）→ 降级", recommend._hscore_penalty(39.9), REC_PENALTY_LOW_FSCORE)
check("线上（40）→ 0", recommend._hscore_penalty(float(FSCORE_LOW)), 0)
check("高分（90）→ 0（🔴绝无加分）", recommend._hscore_penalty(90.0), 0)
check("缺席（None）→ 0（缺席≠低分）", recommend._hscore_penalty(None), 0)

# ── 3/4. 反作弊旗标（commit 4 追加实现后启用）───────────────────────────────
if hasattr(recommend, "_anomaly_flags"):
    print("_anomaly_flags / _anomaly_penalty")
    Q = {"sybil_risk_flag": True, "timing_anomaly_flag": False, "suspicious_win_rate_flag": True,
         "position_size_volatility_flag": False, "perfect_timing_flag": False,
         "combined_risk_score": 55, "max_drawdown": 0.4}
    flags = recommend._anomaly_flags(Q)
    check("只收为真的旗标", flags, ["suspicious_win_rate_flag", "sybil_risk_flag"])
    check("有旗标 → 一次性降级", recommend._anomaly_penalty(flags), REC_PENALTY_ANOMALY)
    check("双旗标不叠加（首版保守）", recommend._anomaly_penalty(flags) == REC_PENALTY_ANOMALY * 2, False)
    check("无旗标 → 0", recommend._anomaly_penalty([]), 0)
    check("quality 缺失 → 空列表", recommend._anomaly_flags(None), [])
    check("非布尔真值不算旗标（字符串 'false' 防呆）",
          recommend._anomaly_flags({"sybil_risk_flag": "false"}), [])

# 常量在正本处（scoring/constants 源码扫描红线由 test_scoring_layer 看守）
check("惩罚常量为负（REC_* 负数惯例）",
      REC_PENALTY_LOW_FSCORE < 0 and REC_PENALTY_ANOMALY < 0, True)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
