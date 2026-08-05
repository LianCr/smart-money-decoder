"""
tests/test_decoder_guards.py — decoder 走 guards.py 后的行为等价（fake 网关，零网络零 key）

背景（T2.1）：六道守卫实现搬进 analyzer/guards.py，decoder 保持 raise 语义。
本文件用违规卡矩阵钉死"抽取前后 DecoderError reason 一致"：
  每道守卫喂一张违规卡 → 抛对应 reason；干净卡 → 通过且 warnings 仍由代码直填。
（此前 decoder 守卫零测试覆盖——AUDIT P1-8/T2.4 实证——本文件同时补上这个洞。）
"""

import json
import sys

sys.path.insert(0, ".")

import analyzer.decoder as decoder
from analyzer.decoder import decode_position, DecoderError

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


# assembled 契约样例：articles 非空 + anchored + pnl 10% → 矩阵算 high
ASSEMBLED = {
    "market_question": "Will X win?",
    "outcome": "Yes",
    "entry_price": 0.7983,
    "current_price": 0.85,
    "position_value": 10000.0,
    "cash_pnl": 500.0,
    "pnl_pct": 10.0,
    "resolution_criteria": "X must win the vote.",
    "resolution_date": "2026-12-31T00:00:00Z",
    "articles": [{"title": "X leads polls", "url": "u", "published_at": "2026-06-10",
                  "source": "s", "snippet": "..."}],
    "time_anchored": True,
    "search_query": "X win",
}

CLEAN_CARD = {
    "what_bet": "Betting X wins the vote by resolution date December 31, 2026.",
    "catalyst": [{"title": "X leads polls", "url": "u", "date": "2026-06-10",
                  "why_relevant": "Polling directly tracks the resolution question."}],
    "edge_analysis": "Entered at 79.83 cents, now 85; upside remains if X holds the lead.",
    "follow_call": "ROOM LEFT",
    "confidence": "high",
    "reasoning": "Price has not fully converged; evidence supports the position.",
}


def run(card_patch=None, assembled_patch=None):
    """跑一次 decode_position，网关替身返回给定卡片 JSON。返回 (result, error)。"""
    card = {**CLEAN_CARD, **(card_patch or {})}
    assembled = {**ASSEMBLED, **(assembled_patch or {})}
    real = decoder.call_gateway
    decoder.call_gateway = lambda prompt, max_tokens=0, timeout=0: json.dumps(card, ensure_ascii=False)
    try:
        return decode_position(assembled, as_of="2026-06-15"), None
    except DecoderError as e:
        return None, e
    finally:
        decoder.call_gateway = real


print("干净卡")
result, err = run()
check("干净卡通过", err, None)
check("warnings 由代码直填（干净输入=空表）", result["warnings"], [])
check("卡片字段原样返回", result["follow_call"], "ROOM LEFT")

print("违规卡矩阵 → DecoderError reason")
_, err = run({"follow_call": "BUY NOW"})
check("非法 follow_call → INVALID_FOLLOW_CALL", err and err.reason, "INVALID_FOLLOW_CALL")

_, err = run({"confidence": "low"})
check("改判信心 → CONFIDENCE_TAMPERED", err and err.reason, "CONFIDENCE_TAMPERED")

# articles 空：矩阵强制 low，卡片需 echo low 才能测到 FABRICATED（守卫顺序 6.2 在 6.3 前）
_, err = run({"confidence": "low", "catalyst": [{"title": "made up"}]},
             {"articles": []})
check("articles 空 + 编造 catalyst → FABRICATED_CATALYST", err and err.reason, "FABRICATED_CATALYST")

_, err = run({"catalyst": [{"title": "X leads polls", "url": "u", "date": "2026-06-10",
                            "why_relevant": "Interesting but unrelated to the resolution criteria."}]})
check("自供不相关 → IRRELEVANT_CATALYST", err and err.reason, "IRRELEVANT_CATALYST")

_, err = run({"reasoning": "The market resolves in three weeks so momentum matters."})
check("时长推算 → DURATION_COMPUTED", err and err.reason, "DURATION_COMPUTED")
check("DURATION message 含字段与原文", "reasoning" in err.message and "three weeks" in err.message, True)

_, err = run({"edge_analysis": "Entry price is unknown, so upside math is impossible."})
check("否认已知入场价 → ENTRY_PRICE_DENIED", err and err.reason, "ENTRY_PRICE_DENIED")

# 实证过的误伤案例必须放行（数值在场=已使用）
result, err = run({"edge_analysis": "Entry price is unknown by date but the wallet paid 79.83 cents; room remains."})
check("误伤案例放行（79.83 在场）", err, None)

# 日期字面豁免：resolution_date_human 风格的日期不触发 DURATION（T2.4 #1 边界）
result, err = run({"what_bet": "Betting X wins before December 31, 2026 as published 2026-06-10."})
check("日期字面不触发 DURATION", err, None)

print("守卫顺序（与抽取前一致：6.1 先于 6.2）")
_, err = run({"follow_call": "BUY NOW", "confidence": "low"})
check("同时违规时报第一道（INVALID_FOLLOW_CALL）", err and err.reason, "INVALID_FOLLOW_CALL")

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
