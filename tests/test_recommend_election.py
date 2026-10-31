"""
tests/test_recommend_election.py — 扫榜换大选主题（2026-10-30）

契约：
  1. _discovery_markets：发现入口 = 中期选举成交量最大的子盘（theme_markets.election_condition_ids）；
     选举盘拿不到（上游挂）→ 回落旧的 SEEDS 种子扩展，扫榜不至于空转
  2. _election_position：候选展示的仓位必须是**选举盘**——最大政治仓是选举盘就用它；
     否则在前 5 个政治仓里找第一个选举盘；一个都没有 → None（该钱包不进推荐）
  3. scan 端到端（全 mock、ai_top=0）：候选的 market_question 全是选举盘、source_market 来自选举盘、
     method 标 E_election_reverse
  4. hot_traders._political_pool 同样从选举盘持有人扩展
零 key 零网络。
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")

import recommend as rec
import hot_traders as ht

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


class patched:
    def __init__(self, mod, **kw):
        self.mod, self.kw = mod, kw

    def __enter__(self):
        self.old = {k: getattr(self.mod, k) for k in self.kw}
        for k, v in self.kw.items():
            setattr(self.mod, k, v)

    def __exit__(self, *exc):
        for k, v in self.old.items():
            setattr(self.mod, k, v)


ELECTION = [("0xhouse", "Will the Democratic Party control the House after the 2026 Midterm elections?"),
            ("0xtx", "Will the Republican win the Texas Senate race?")]
W1, W2, W3 = "0x" + "1" * 40, "0x" + "2" * 40, "0x" + "3" * 40

print("_discovery_markets")
with patched(rec, election_condition_ids=lambda limit=10: ELECTION):
    check("选举盘为入口", rec._discovery_markets("2026-10-30"), dict(ELECTION))
seed_calls = []
with patched(rec, election_condition_ids=lambda limit=10: [],
             get_top_political_positions_hz=lambda w, **k: seed_calls.append(w) or
             [{"market_id": "0xseed", "market_question": "Seed Q?", "outcome": "Yes"}]):
    got = rec._discovery_markets("2026-10-30")
    check("选举盘为空 → 回落 SEEDS", (got, len(seed_calls)), ({"0xseed": "Seed Q?"}, len(rec.SEEDS)))

print("_election_position")
POS_ELEC = {"market_id": "0xhouse", "outcome": "Yes", "market_question": ELECTION[0][1]}
POS_FED = {"market_id": "0xfed", "outcome": "No", "market_question": "Will the Fed cut rates in December?"}
with patched(rec, get_top_political_position_hz=lambda w, **k: dict(POS_ELEC),
             get_top_political_positions_hz=lambda w, **k: []):
    check("最大仓即选举盘", rec._election_position(W1, "2026-10-30")["market_id"], "0xhouse")
with patched(rec, get_top_political_position_hz=lambda w, **k: dict(POS_FED),
             get_top_political_positions_hz=lambda w, **k: [dict(POS_FED),
                                                            {"market_id": "0xtx", "outcome": "No",
                                                             "market_question": ELECTION[1][1]}]):
    check("最大仓非选举 → 前 5 里找选举盘", rec._election_position(W1, "2026-10-30")["market_id"], "0xtx")
with patched(rec, get_top_political_position_hz=lambda w, **k: dict(POS_FED),
             get_top_political_positions_hz=lambda w, **k: [dict(POS_FED)]):
    check("没有选举盘 → None", rec._election_position(W1, "2026-10-30"), None)
with patched(rec, get_top_political_position_hz=lambda w, **k: {"error": "NO_POSITION"},
             get_top_political_positions_hz=lambda w, **k: []):
    check("出错 → None", rec._election_position(W1, "2026-10-30"), None)

print("scan 端到端（全 mock、ai_top=0）")
positions = {W1: dict(POS_ELEC), W2: dict(POS_FED), W3: {"market_id": "0xtx", "outcome": "No",
                                                         "market_question": ELECTION[1][1]}}
with tempfile.TemporaryDirectory() as td:
    out = Path(td) / "recommendations.json"
    with patched(rec, OUT=out,
                 election_condition_ids=lambda limit=10: ELECTION,
                 call=lambda *a, **k: {"data": []},
                 get_market_holders=lambda cid, **k: [(W1, 900.0), (W2, 800.0)] if cid == "0xhouse" else [(W3, 700.0)],
                 _wallet360=lambda w, *a, **k: ({}, [{"category": "Politics", "total_pnl": 50000.0, "roi": 10.0,
                                                      "win_rate": None, "total_trades": None}]),
                 get_top_political_position_hz=lambda w, **k: dict(positions[w]),
                 get_top_political_positions_hz=lambda w, **k: [dict(positions[w])],
                 get_behavior_flags=lambda *a, **k: {"flag": "STATIC", "fact": "quiet"}):
        rec.time.sleep = lambda s: None
        cands = rec.scan(ai_top=0)
    payload = json.loads(out.read_text())
    check("非选举钱包被剔除", sorted(c["wallet"] for c in cands), sorted([W1, W3]))
    check("候选全是选举盘", all(rec.is_election_question(c["market_question"]) for c in cands), True)
    check("source_market 来自选举盘", {c["source_market"] for c in cands} <= {q for _c, q in ELECTION}, True)
    check("method 标注", payload["method"], "E_election_reverse")

print("hot_traders._political_pool")
with patched(ht, election_condition_ids=lambda limit=6: ELECTION,
             get_market_holders=lambda cid, **k: [(W1, 1.0)] if cid == "0xhouse" else [(W3, 1.0)]):
    ht.time.sleep = lambda s: None
    check("选举盘持有人", ht._political_pool(), {W1, W3})

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
