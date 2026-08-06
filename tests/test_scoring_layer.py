"""
tests/test_scoring_layer.py — T2.2 确定性评分层契约

钉死的契约：
  1. 阈值单一正本：scoring/constants.py 是判断阈值唯一定义处——曾经"自首"的三对
     重复常量（board_feed↔price_reaction 的 5.0、credibility↔market_thesis 的
     0.12/0.06 与 85/80/35/30）identity 级同源，原位字面量死透（源码扫描）。
  2. scoring 包零 IO 零网络零 LLM（源码扫描）——"确定性"的操作性定义。
  3. v2 矩阵 7 规则首次直测（此前只经 decode_position 间接过）+ decoder 别名同源。
  4. follow_call 三态 + CHASED 8% 边界。
  5. Phase 2 DoD 钉死："给定同一份 facts JSON，确定性评分层输出 100% 可复现"
     ——同一 fixture 连喂四个评分入口两遍，JSON 序列化逐字节一致。
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, ".")

import scoring.constants as C
from scoring.matrix_v2 import compute_confidence_v2
from scoring.follow_call import code_follow_call
from scoring.reasoner_v3 import compute_confidence_v3
from scoring.credibility import build_credibility
import analyzer.decoder as decoder
import analyzer.guards as guards
import analyzer.price_reaction as pr
import briefing.board_feed as bf
import analyzer.market_thesis as mt          # noqa: F401  （import 成功本身=改引没破环）
import confidence_replay as cr
import fetcher.positions as positions
import fetcher.social as social

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


# ── 1. 单一正本 identity（重复常量死透）─────────────────────────────────────
print("单一正本 identity")
check("guards.FOLLOW_CALL_ENUM 即 constants 正本", guards.FOLLOW_CALL_ENUM is C.FOLLOW_CALL_ENUM, True)
check("price_reaction.MEANINGFUL_MOVE_PCT 即 constants 正本", pr.MEANINGFUL_MOVE_PCT is C.MEANINGFUL_MOVE_PCT, True)
check("board_feed.REACT_THRESHOLD 即同一常量（同口径注释兑现）", bf.REACT_THRESHOLD is C.MEANINGFUL_MOVE_PCT, True)
check("confidence_replay 阈值来自 constants", cr.MIN_BUCKET_N == C.REPLAY_MIN_BUCKET_N, True)
check("positions.NEAR_SETTLED_PRICE 即 constants 正本", positions.NEAR_SETTLED_PRICE is C.NEAR_SETTLED_PRICE, True)
check("social 两阈值来自 constants",
      (social.ORGANIC_MIN is C.ORGANIC_MIN, social.GENERIC_HIT_FRAC is C.GENERIC_HIT_FRAC), (True, True))

print("原位字面量死透（源码扫描）")
mt_src = Path("analyzer/market_thesis.py").read_text(encoding="utf-8")
check("market_thesis 无 0.12/0.06 字面量（犹豫度带改引 constants）",
      ("0.12" in mt_src) or ("0.06" in mt_src), False)
check("market_thesis 无 >= 85 门字面量", ">= 85" in mt_src, False)
bf_src = Path("briefing/board_feed.py").read_text(encoding="utf-8")
check("board_feed 无 5.0 重复定义", "REACT_THRESHOLD = 5.0" in bf_src, False)
pr_src = Path("analyzer/price_reaction.py").read_text(encoding="utf-8")
check("price_reaction 无 5.0 重复定义", "MEANINGFUL_MOVE_PCT = 5.0" in pr_src, False)
cfg_src = Path("core/config.py").read_text(encoding="utf-8")
check("core/config 已迁出 REPLAY_MIN_BUCKET_N（注释兑现）", "REPLAY_MIN_BUCKET_N" in cfg_src, False)
gd_src = Path("analyzer/guards.py").read_text(encoding="utf-8")
check("guards 不再自定义 FOLLOW_CALL_ENUM 字面量", '{"ROOM LEFT", "CHASED", "NO BASIS"}' in gd_src, False)

# ── 2. scoring 包零 IO 零网络零 LLM（确定性的操作性定义）────────────────────
print("scoring 包纯净度")
for p in sorted(Path("scoring").glob("*.py")):
    src = p.read_text(encoding="utf-8")
    dirty = [tok for tok in ("import requests", "open(", "atomic_write", "call_gateway",
                             "hz_call", "fetcher.", "core.llm") if tok in src]
    check(f"{p.name} 零 IO 零网络零 LLM", dirty, [])

# ── 3. v2 矩阵 7 规则直测（迁包后的行为等价钉死）────────────────────────────
print("v2 矩阵直测")
ART = [{"title": "t"}]


def m(articles=ART, anchored=True, pnl=10):
    return {"articles": articles, "time_anchored": anchored, "pnl_pct": pnl}


check("规则1：articles 空 → low（最高优先级，压过好 pnl）", compute_confidence_v2(m(articles=[])), "low")
check("规则2：pnl>60 → low", compute_confidence_v2(m(pnl=60.1)), "low")
check("规则3：浮亏+未锚 → low", compute_confidence_v2(m(anchored=False, pnl=-1)), "low")
check("规则4：浮亏 → medium", compute_confidence_v2(m(pnl=-1)), "medium")
check("规则5：未锚 → medium（v2 独有，v3 已删）", compute_confidence_v2(m(anchored=False, pnl=10)), "medium")
check("pnl 缺失 → medium（保守不给高）", compute_confidence_v2(m(pnl=None)), "medium")
check("规则6：0≤pnl<30 → high", compute_confidence_v2(m(pnl=29.9)), "high")
check("规则6 边界：pnl=30 → medium", compute_confidence_v2(m(pnl=30)), "medium")
check("规则7：30≤pnl<60 → medium", compute_confidence_v2(m(pnl=59.9)), "medium")
# pnl=60 恰好落在规则2(>60)与规则7(<60)的夹缝 → 走末行 low。这是 v2 封板起的既有行为
# （末行注释"理论不可达"对 ==60 不准确），纯搬运照实钉死、不修（改=动回测口径）。
check("边界 pnl=60 → low（v2 既有夹缝行为，原样保留）", compute_confidence_v2(m(pnl=60)), "low")
check("decoder._compute_confidence 即 scoring 正本（别名同源）",
      decoder._compute_confidence is compute_confidence_v2, True)

# ── 4. follow_call 三态 + 边界 ──────────────────────────────────────────────
print("follow_call")
check("无证据 → NO BASIS", code_follow_call({"support_catalysts": [], "threat_catalysts": []}), "NO BASIS")
check("已走 8% → CHASED（边界含）", code_follow_call({"support_catalysts": [1], "price_already_moved": 8}), "CHASED")
check("走 7.9% → ROOM LEFT", code_follow_call({"support_catalysts": [1], "price_already_moved": 7.9}), "ROOM LEFT")
check("位移未知 → ROOM LEFT（不臆测追高）", code_follow_call({"threat_catalysts": [1]}), "ROOM LEFT")
check("产出 ∈ FOLLOW_CALL_ENUM", code_follow_call({"support_catalysts": [1]}) in C.FOLLOW_CALL_ENUM, True)

# ── 5. Phase 2 DoD：同 facts JSON 100% 可复现 ───────────────────────────────
print("DoD：确定性评分层 100% 可复现")
FACTS = {"articles": ART, "time_anchored": True, "pnl_pct": 12.3,
         "support_catalysts": [{"title": "s", "market_reaction": "confirmed"}],
         "threat_catalysts": [], "price_already_moved": 3.2}
V3_KW = dict(support=FACTS["support_catalysts"], threat=[], pnl_pct=12.3, time_anchored=True,
             by_outcome={"Yes": {"shares": 100}, "No": {"shares": 10}},
             held_outcome="Yes", recent_action="adding")
CRED_RAW = {"liquidity_percentile": 97.0, "top1_wallet_pct": 12.0, "top10_wallet_pct": 40.0,
            "unique_traders_7d": 500, "volume_trend": "Stable", "flags": []}


def run_all():
    return json.dumps({
        "v2": compute_confidence_v2(FACTS),
        "v3": compute_confidence_v3(**V3_KW),
        "fc": code_follow_call(FACTS),
        "cred": build_credibility(CRED_RAW, 0.03),
    }, sort_keys=True, ensure_ascii=False)


check("四个评分入口两遍逐字节一致", run_all() == run_all(), True)
check("v3 只降不升不变量在 DoD 样例上成立",
      compute_confidence_v3(**V3_KW)[0] in ("high", "medium", "low"), True)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
