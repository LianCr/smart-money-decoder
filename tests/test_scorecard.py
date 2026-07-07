"""
tests/test_scorecard.py — scorecard.py 纯逻辑 mock 测试（无网络、写临时档案不碰 .data/）

记分牌是"诚实"的对外证明，数学错了比没有更糟。覆盖三条灵魂红线对应的数学：
  1. 命中率 = hits / settled_endorsed，NO BASIS 不进分子分母（红线2）
  2. pending 不进命中率
  3. nobasis_clear_in_hindsight（事后看有清晰方向）单列
  4. record_judgment 同 key 更新不灌水；final_result 已结算不覆盖
  5. fetch_settlements 增量：已结算跳过、resolver 抛错不炸、只认 Yes/No
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")

import scorecard

# 档案指到临时目录，绝不碰真 .data/scorecard.json（真档案是累积的历史，红线：不造假不污染）
_tmp = tempfile.mkdtemp()
scorecard.ARCHIVE = Path(_tmp) / "scorecard_test.json"

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


# ── 1. 空档案 → 全零、命中率 None（第一天空=正常，绝不回填）─────────────────────
sc = scorecard.compute_scorecard()
check("空档案 tested=0", sc["tested"], 0)
check("空档案 hit_rate=None（不是 0，无样本≠0%）", sc["hit_rate_pct"], None)

# ── 2. 记录 + 分类 + 命中率数学 ────────────────────────────────────────────────
# hit：背书 Yes、结算 Yes
scorecard.record_judgment(wallet="0xA", cid="c1", market_question="q1", outcome="Yes",
                          market_price=0.6, follow_call="ROOM LEFT", confidence="high", source="board")
# miss：背书 Yes、结算 No
scorecard.record_judgment(wallet="0xB", cid="c2", market_question="q2", outcome="Yes",
                          market_price=0.5, follow_call="CHASED", confidence="med", source="board")
# nobasis + 事后有清晰方向（钱包赢了）
scorecard.record_judgment(wallet="0xC", cid="c3", market_question="q3", outcome="No",
                          market_price=0.3, follow_call="NO BASIS", confidence="low", source="decode")
# pending：背书但未结算
scorecard.record_judgment(wallet="0xD", cid="c4", market_question="q4", outcome="Yes",
                          market_price=0.4, follow_call="ROOM LEFT", confidence="med", source="board")

_results = {"c1": "Yes", "c2": "No", "c3": "No"}   # c4 未结算
n = scorecard.fetch_settlements(lambda cid: _results.get(cid))
check("fetch_settlements 新结算 3 条", n, 3)

sc = scorecard.compute_scorecard()
check("tested=4", sc["tested"], 4)
check("settled=3", sc["settled"], 3)
check("settled_endorsed=2（NO BASIS 不进分母·红线2）", sc["settled_endorsed"], 2)
check("direction_consistent=1（只有 c1 命中）", sc["direction_consistent"], 1)
check("hit_rate=50.0（1/2，与 NO BASIS 无关）", sc["hit_rate_pct"], 50.0)
check("nobasis_total=1", sc["nobasis_total"], 1)
check("nobasis_clear_in_hindsight=1（c3 钱包押 No 且结算 No）", sc["nobasis_clear_in_hindsight"], 1)

status_by_cid = {}
for r in sc["rows"]:
    status_by_cid[r["market_question"]] = r["status"]
check("c1 → hit", status_by_cid["q1"], "hit")
check("c2 → miss", status_by_cid["q2"], "miss")
check("c3 → nobasis（不是 hit）", status_by_cid["q3"], "nobasis")
check("c4 → pending", status_by_cid["q4"], "pending")

# ── 3. 同 key 重复 decode 更新同一条、不灌水 ──────────────────────────────────
scorecard.record_judgment(wallet="0xD", cid="c4", market_question="q4", outcome="Yes",
                          market_price=0.45, follow_call="CHASED", confidence="low", source="board")
sc = scorecard.compute_scorecard()
check("同(钱包,仓,来源)重复记录不灌水 tested 仍=4", sc["tested"], 4)

# 同仓不同 source 是两条（decode 和 board 是两个大脑，分开记）
scorecard.record_judgment(wallet="0xD", cid="c4", market_question="q4", outcome="Yes",
                          market_price=0.45, follow_call="CHASED", confidence="low", source="decode")
check("同仓不同 source 单独成条 tested=5", scorecard.compute_scorecard()["tested"], 5)

# ── 4. 已结算条 final_result 不被覆盖（结果是历史事实）──────────────────────────
scorecard.record_judgment(wallet="0xA", cid="c1", market_question="q1", outcome="Yes",
                          market_price=0.99, follow_call="CHASED", confidence="low", source="board")
d = scorecard._load()
check("重复记录后 final_result 保留 Yes", d["0xa_c1_board"]["final_result"], "Yes")

# ── 5. fetch_settlements 边界：已结算跳过 / resolver 抛错不炸 / 非 Yes-No 不填 ────
def _bad_resolver(cid):
    raise RuntimeError("574 挂了")
check("resolver 抛错 → 0 条且不炸", scorecard.fetch_settlements(_bad_resolver), 0)
check("resolver 返回脏值不填", scorecard.fetch_settlements(lambda cid: "MAYBE"), 0)

# ── 6. 空 follow_call / 空钱包不记（守卫）────────────────────────────────────
before = scorecard.compute_scorecard()["tested"]
scorecard.record_judgment(wallet="", cid="c9", market_question="q9", outcome="Yes",
                          market_price=0.5, follow_call="ROOM LEFT", confidence="med", source="board")
scorecard.record_judgment(wallet="0xE", cid="c9", market_question="q9", outcome="Yes",
                          market_price=0.5, follow_call=None, confidence="med", source="board")
check("空钱包/空 follow_call 不记", scorecard.compute_scorecard()["tested"], before)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
