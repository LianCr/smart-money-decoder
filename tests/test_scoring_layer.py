"""
tests/test_scoring_layer.py — T2.2 确定性评分层契约

钉死的契约：
  1. 阈值单一正本：scoring/constants.py 是判断阈值唯一定义处——曾经"自首"的三对
     重复常量（board_feed↔price_reaction 的 5.0、credibility↔market_thesis 的
     0.12/0.06 与 85/80/35/30）identity 级同源，原位字面量死透（源码扫描）。
  2. scoring 包零 IO 零网络零 LLM（源码扫描）——"确定性"的操作性定义。
  （commit 2 追加：矩阵直测 / follow_call 边界 / 同 facts JSON 100% 可复现 DoD。）
"""

import sys
from pathlib import Path

sys.path.insert(0, ".")

import scoring.constants as C
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

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
