"""
api/backtest_mock.py — Track Record 回测页的占位 MOCK 数据

⚠️ 这是 mock：回测 pipeline（在历史时点重放 decoder，与真实结算对照）尚未实现。
先用 3 条手工样本把前端搭起来调样式。真实回测产出后，按同一结构替换 MOCK_BACKTEST
即可，前端不用改。

数据契约（GET /backtest 返回）：
{
  "_mock": bool,                      # true 时前端显示 MOCK 角标
  "wallet": str,
  "overview": {                       # 整页唯一大数字区，全部由样本聚合而来
    "directional": {"hits", "total"}, # 方向命中率
    "high_conf":   {"hits", "total"}, # 高信心命中率（信心校准证据）
    "low_conf":    {"hits", "total"}, # 低信心命中率
    "composition": {"profitable", "loss"},
  },
  "samples": [ {
    "market_question", "resolved_outcome" ("YES"/"NO"), "resolved_date",
    "t7_date", "t1_date",
    "t7_card", "t1_card",             # 与 /analyze 返回同形，前端复用 Card 组件
    "hit": bool,                      # 系统最终判断方向 vs 真实结算是否一致
  } ]
}
"""


def _card(question, outcome, res_date, anchored, entry, curr, pos_val, cash, pct,
          what_bet, catalyst, edge, follow, conf, reasoning, warnings):
    """紧凑构造一张与 /analyze 同形的卡片 dict。"""
    return {
        "market_question": question,
        "outcome": outcome,
        "resolution_date": res_date,
        "time_anchored": anchored,
        "price_info": {
            "entry_price": entry, "current_price": curr,
            "position_value": pos_val, "cash_pnl": cash, "pnl_pct": pct,
        },
        "what_bet": what_bet,
        "catalyst": catalyst,
        "edge_analysis": edge,
        "follow_call": follow,
        "confidence": conf,
        "reasoning": reasoning,
        "warnings": warnings,
    }


# ── 样本 1：命中 · 高信心 · 判断演变 ROOM LEFT → CHASED ────────────────────────
_S1_Q = "Will a US federal government shutdown occur before March 2026?"
_S1 = {
    "market_question": _S1_Q,
    "resolved_outcome": "NO",
    "resolved_date": "2026-02-28",
    "t7_date": "2026-02-14",
    "t1_date": "2026-02-20",
    "hit": True,
    "t7_card": _card(
        _S1_Q, "No", "2026-02-28T00:00:00Z", True, 0.62, 0.71, 31000, 4500, 14.5,
        "The wallet is betting No on a federal shutdown before the March deadline. "
        "Resolution requires a lapse in appropriations, not merely budget brinkmanship.",
        [{"title": "Congress advances bipartisan stopgap funding bill", "url": "https://example.com/cr",
          "published_at": "2026-02-11", "relation": "BEFORE_ENTRY",
          "why_relevant": "A stopgap clearing committee directly lowers the probability of a lapse in funding."}],
        "Entry 0.62, now 0.71 — the No side has firmed but roughly a third of the move to "
        "certainty remains. A follower today still captures meaningful upside if funding holds.",
        "ROOM LEFT", "high",
        "A sourced procedural catalyst anchors the thesis, news is time-anchored before entry, "
        "and the price has not fully absorbed the funding progress.",
        []),
    "t1_card": _card(
        _S1_Q, "No", "2026-02-28T00:00:00Z", True, 0.62, 0.88, 31000, 13000, 41.9,
        "The wallet is betting No on a federal shutdown before the March deadline. "
        "Resolution requires a lapse in appropriations, not merely budget brinkmanship.",
        [{"title": "Congress advances bipartisan stopgap funding bill", "url": "https://example.com/cr",
          "published_at": "2026-02-11", "relation": "BEFORE_ENTRY",
          "why_relevant": "A stopgap clearing committee directly lowers the probability of a lapse in funding."}],
        "Entry 0.62, now 0.88 — the favorable repricing has largely happened. A follower buying "
        "today pays near-certainty pricing for only 0.12 of remaining upside.",
        "CHASED", "high",
        "Thesis is intact and confirmed by the funding vote, but the price has absorbed nearly all "
        "of the signal; little edge remains for a new follower.",
        []),
}

# ── 样本 2：失手 · 诚实亮出 · ROOM LEFT → ROOM LEFT ───────────────────────────
_S2_Q = "Will Nicolas Maduro leave power in Venezuela by April 2026?"
_S2 = {
    "market_question": _S2_Q,
    "resolved_outcome": "NO",
    "resolved_date": "2026-04-15",
    "t7_date": "2026-03-19",
    "t1_date": "2026-03-25",
    "hit": False,
    "t7_card": _card(
        _S2_Q, "Yes", "2026-04-15T00:00:00Z", True, 0.40, 0.48, 22000, 4400, 20.0,
        "The wallet is betting Yes that Maduro exits power before the April deadline, via "
        "resignation, removal, or loss of effective control.",
        [{"title": "Opposition stages largest protests in years across Caracas", "url": "https://example.com/vz",
          "published_at": "2026-03-16", "relation": "BEFORE_ENTRY",
          "why_relevant": "Mass mobilization raises the visible pressure on the regime ahead of entry."}],
        "Entry 0.40, now 0.48 — the market has moved toward the wallet's thesis. A follower still "
        "has room if the pressure converts into an actual transfer of power.",
        "ROOM LEFT", "medium",
        "A sourced catalyst exists and is time-anchored, but the path from protests to an actual "
        "power transfer is uncertain, capping confidence at medium.",
        []),
    "t1_card": _card(
        _S2_Q, "Yes", "2026-04-15T00:00:00Z", True, 0.40, 0.44, 22000, 2200, 10.0,
        "The wallet is betting Yes that Maduro exits power before the April deadline, via "
        "resignation, removal, or loss of effective control.",
        [{"title": "Opposition stages largest protests in years across Caracas", "url": "https://example.com/vz",
          "published_at": "2026-03-16", "relation": "BEFORE_ENTRY",
          "why_relevant": "Mass mobilization raises the visible pressure on the regime ahead of entry."}],
        "Entry 0.40, now 0.44 — the move has stalled. Momentum from the protests is fading without "
        "a concrete institutional crack.",
        "ROOM LEFT", "low",
        "The catalyst has not advanced the thesis materially and the price has drifted back; "
        "low confidence reflects a stalling signal.",
        []),
}

# ── 样本 3：命中 · 判断演变 NO BASIS → ROOM LEFT（AFTER_ENTRY 催化） ──────────
_S3_Q = "Will the UK call a snap general election before May 2026?"
_S3 = {
    "market_question": _S3_Q,
    "resolved_outcome": "NO",
    "resolved_date": "2026-04-30",
    "t7_date": "2026-04-09",
    "t1_date": "2026-04-15",
    "hit": True,
    "t7_card": _card(
        _S3_Q, "No", "2026-04-30T00:00:00Z", False, 0.78, 0.80, 18000, 460, 2.6,
        "The wallet is betting No on a snap UK general election before May. Resolution requires a "
        "formal dissolution of Parliament, not speculation.",
        [],
        "Entry 0.78, now 0.80 — barely moved. With no sourced trigger the entry rationale is opaque.",
        "NO BASIS", "low",
        "No relevant news was retrieved and the move is negligible; without a catalyst there is no "
        "evidentiary basis to follow.",
        ["No relevant news found in the search window; the trade's catalyst is unknown."]),
    "t1_card": _card(
        _S3_Q, "No", "2026-04-30T00:00:00Z", True, 0.78, 0.86, 18000, 1840, 10.3,
        "The wallet is betting No on a snap UK general election before May. Resolution requires a "
        "formal dissolution of Parliament, not speculation.",
        [{"title": "Prime Minister rules out early election in Commons statement", "url": "https://example.com/uk",
          "published_at": "2026-04-13", "relation": "AFTER_ENTRY",
          "why_relevant": "An explicit on-record refusal to call an early election directly supports the No side."}],
        "Entry 0.78, now 0.86 — a sourced statement has firmed the No side. A follower retains a "
        "modest edge as the deadline approaches with no dissolution.",
        "ROOM LEFT", "medium",
        "A post-entry statement directly confirms the thesis and is sourced; the price has only "
        "partly absorbed it, leaving a moderate edge.",
        []),
}


MOCK_BACKTEST = {
    "_mock": True,
    "wallet": "0x7c3db723f1d4d8cb9c550095203b686cb11e5c6b",
    "overview": {
        "directional": {"hits": 11, "total": 15},
        "high_conf":   {"hits": 8,  "total": 9},
        "low_conf":    {"hits": 3,  "total": 6},
        "composition": {"profitable": 10, "loss": 5},
    },
    "samples": [_S1, _S2, _S3],
}
