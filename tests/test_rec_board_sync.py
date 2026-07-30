"""
tests/test_rec_board_sync.py — 推荐卡 ⑥ 与看板缓存的 serve-time 对齐（tempdir，无网络）

背景（2026-07-09 用户实测）：推荐卡显示的信心/空间与点进去的看板不一致——卡片是
扫榜时刻的冻结副本，看板是活的（扫后重建/翻天/近结算守卫换盘都会分叉，实测同一
as_of 也分叉）。修复=单一真相源：serve 时用该钱包最新看板缓存回写卡片。覆盖：
  1. 卡片旧值被看板值覆盖（信心/空间/裁决文本/lean/alignment/verified_as_of）
  2. 守卫换盘 → 卡片的 market_question/outcome 跟着换（描述同一注）
  3. 扫榜时验证失败的候选、但看板后来建过 → 升级为 ai_pick
  4. 无看板缓存 → 保留扫榜值不动
  5. 看板守卫拦截（confidence 空）→ 不覆盖
  6. 多快照取最新日期那份
  7. 同盘分歧标按对齐后的市场重算（旧标清掉）
  8. 看板 i18n_en 里的裁决翻译被带出（返回值并入顶层）
"""

import sys
sys.path.insert(0, ".")

import json
import tempfile
from pathlib import Path

import recommend

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


def _board(confidence, call, verdict, mq, outcome, as_of="2026-07-09", i18n=None, lean="NO"):
    return {"as_of": as_of,
            "reasoning": {"confidence": confidence, "follow_call": call, "reasoning": verdict,
                          "market_lean": lean, "alignment": "顺 edge", "pivotal_unknown": "关键未知",
                          "facts": {"market_question": mq, "outcome": outcome,
                                    "position_type": "single_side_conviction"}},
            "i18n_en": i18n or {}}


W1, W2, W3, W4 = ("0x" + c * 40 for c in "abcd")

with tempfile.TemporaryDirectory() as td:
    cache = Path(td)
    # W1：看板已重建，值和盘都变了（守卫换盘）
    (cache / f"{W1}_2026-07-09.json").write_text(json.dumps(_board(
        "low", "ROOM LEFT", "新裁决文本", "新盘B?", "Yes",
        i18n={"新裁决文本": "new verdict EN"})), encoding="utf-8")
    # W1 还有一份旧快照（应取最新）
    (cache / f"{W1}_2026-06-25.json").write_text(json.dumps(_board(
        "high", "CHASED", "旧裁决", "旧盘A?", "No", as_of="2026-06-25")), encoding="utf-8")
    # W3：扫榜时验证失败（无 ai 字段），但看板后来建过 —— 同盘B，制造分歧
    (cache / f"{W3}_2026-07-09.json").write_text(json.dumps(_board(
        "med", "CHASED", "W3裁决", "新盘B?", "No")), encoding="utf-8")
    # W4：看板守卫拦截（confidence 空）
    (cache / f"{W4}_2026-07-09.json").write_text(json.dumps(
        {"as_of": "2026-07-09", "reasoning": {"confidence": None, "guard_tripped": "X"}}),
        encoding="utf-8")

    cands = [
        {"wallet": W1, "market_question": "旧盘A?", "outcome": "No", "ai_pick": True,
         "ai_confidence": "high", "ai_follow_call": "CHASED", "ai_verdict": "旧裁决",
         "disagreement": True},                            # 旧分歧标（对齐后应重算）
        {"wallet": W2, "market_question": "别的盘?", "outcome": "Yes", "ai_pick": True,
         "ai_confidence": "med", "ai_follow_call": "NO BASIS", "ai_verdict": "W2旧裁决"},
        {"wallet": W3, "market_question": "谁知道盘?", "outcome": "Yes", "ai_pick": False},
        {"wallet": W4, "market_question": "守卫盘?", "outcome": "No", "ai_pick": False},
    ]
    extra = recommend.sync_candidates_with_boards(cands, cache)
    c1, c2, c3, c4 = cands

    # 1. 覆盖
    check("W1 信心被看板覆盖", c1["ai_confidence"], "low")
    check("W1 空间被看板覆盖", c1["ai_follow_call"], "ROOM LEFT")
    check("W1 裁决文本被覆盖", c1["ai_verdict"], "新裁决文本")
    check("W1 verified_as_of 更新", c1["verified_as_of"], "2026-07-09")
    # 2. 守卫换盘 → 卡片描述同一注
    check("W1 market_question 跟看板", c1["market_question"], "新盘B?")
    check("W1 outcome 跟看板", c1["outcome"], "Yes")
    # 6. 多快照取最新
    check("W1 取最新快照（非 6-25 旧值）", c1["ai_confidence"] != "high", True)
    # 3. 升级 ai_pick
    check("W3 升级为 ai_pick", c3["ai_pick"], True)
    check("W3 带上看板裁决", c3["ai_confidence"], "med")
    # 4. 无缓存不动
    check("W2 无缓存保留扫榜值", (c2["ai_confidence"], c2["ai_follow_call"]), ("med", "NO BASIS"))
    # 5. 守卫拦截不覆盖
    check("W4 守卫拦截不覆盖", c4["ai_pick"], False)
    # 7. 分歧标重算：W1(新盘B Yes) vs W3(新盘B No) → 分歧；W1 的旧标先清后重打
    check("同盘反向 → 分歧标重算", (c1.get("disagreement"), c3.get("disagreement")), (True, True))
    check("W2 无分歧标", c2.get("disagreement"), None)
    # 8. 翻译带出
    check("看板 i18n_en 翻译带出", extra.get("新裁决文本"), "new verdict EN")

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
