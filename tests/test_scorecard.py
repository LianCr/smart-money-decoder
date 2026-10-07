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


# ── 7. 🔴 P0 回归：档案被写坏后，历史判断绝不能被静默清零 ──────────────────────
# 老实现的病：_load() 把解析失败当成"空档案"返回 {}，紧接着 record_judgment 一写，
# 整本历史就被覆盖成一条。档案是产品唯一"我判断得准不准"的证据，且红线是
# 「绝不造假回填」—— 丢了就永远补不回。现在损坏文件必须被隔离保全。
_tmp2 = tempfile.mkdtemp()
scorecard.ARCHIVE = Path(_tmp2) / "scorecard.json"

# 先攒 3 条真实判断（模拟线上累积的历史）
for i, (w, cid) in enumerate([("0xH1", "h1"), ("0xH2", "h2"), ("0xH3", "h3")]):
    scorecard.record_judgment(wallet=w, cid=cid, market_question=f"hist{i}", outcome="Yes",
                              market_price=0.5, follow_call="ROOM LEFT", confidence="high",
                              source="board")
check("历史累积 3 条", scorecard.compute_scorecard()["tested"], 3)
history_bytes = scorecard.ARCHIVE.read_text(encoding="utf-8")

# 模拟进程被冷启动/OOM 打断：档案只写了一半
truncated = history_bytes[: len(history_bytes) // 2]
scorecard.ARCHIVE.write_text(truncated, encoding="utf-8")

# 半截档案存在时又来了一条新判断 —— 老实现在这一步会把 3 条历史全冲掉
scorecard.record_judgment(wallet="0xNEW", cid="new1", market_question="after-crash",
                          outcome="No", market_price=0.4, follow_call="CHASED",
                          confidence="low", source="board")

backups = list(Path(_tmp2).glob("scorecard.json.corrupt-*"))
check("🔴 损坏档案被隔离成备份（不是被覆盖）", len(backups), 1)
check("🔴 备份里是崩溃瞬间的原始字节，一字不差",
      backups[0].read_text(encoding="utf-8"), truncated)
check("三条历史的记录 key 仍能在备份里找到（证据未销毁）",
      all(k in backups[0].read_text(encoding="utf-8") for k in ["0xh1_h1_board", "0xh2_h2_board"]),
      True)
check("服务继续可用：新判断正常落档", scorecard.compute_scorecard()["tested"], 1)
check("新档案是合法 JSON、可正常读回",
      scorecard._load()["0xnew_new1_board"]["follow_call"], "CHASED")

# 顶层结构不对（合法 JSON 但不是对象）同样隔离、不覆盖
scorecard.ARCHIVE.write_text('["not", "an", "archive"]', encoding="utf-8")
scorecard.record_judgment(wallet="0xZ", cid="z1", market_question="q", outcome="Yes",
                          market_price=0.5, follow_call="ROOM LEFT", confidence="med",
                          source="board")
check("结构异常档案也走隔离（备份增至 2 份）",
      len(list(Path(_tmp2).glob("scorecard.json.corrupt-*"))), 2)

# ── 8. 市场价基准：命中率要和"只信市场价"比，否则押热门也能刷出漂亮数字 ──────────
# market_price = 判断那一刻钱包所押那一边的现价 = 市场给的胜率。
# 期望命中数 = Σ 价格（已结算 + 背书 + 有合法价格的条）；NO BASIS / pending 不进。
_tmp3 = tempfile.mkdtemp()
scorecard.ARCHIVE = Path(_tmp3) / "scorecard.json"
check("空档案 price_baseline=None（无样本不出基准）",
      scorecard.compute_scorecard()["price_baseline"], None)

def _rec(w, cid, price, fc="ROOM LEFT", outcome="Yes"):
    scorecard.record_judgment(wallet=w, cid=cid, market_question=cid, outcome=outcome,
                              market_price=price, follow_call=fc, confidence="med",
                              source="board")

_rec("0xP1", "p1", 0.9)                     # 热门，中
_rec("0xP2", "p2", 0.6)                     # 中
_rec("0xP3", "p3", 0.3)                     # 冷门，没中
_rec("0xP4", "p4", None)                    # 没价格，中 → 进命中率但不进基准
_rec("0xP5", "p5", 0.5, fc="NO BASIS")      # NO BASIS 不进基准
_rec("0xP6", "p6", 0.7)                     # 未结算不进基准
_rec("0xP7", "p7", 1.5)                     # 脏价格（>1）→ 当没价格
scorecard.fetch_settlements(lambda cid: {"p1": "Yes", "p2": "Yes", "p3": "No",
                                         "p4": "Yes", "p5": "Yes", "p7": "Yes"}.get(cid))
sc = scorecard.compute_scorecard()
pb = sc["price_baseline"]
check("命中率口径不变：5 条背书已结算中 4", (sc["direction_consistent"], sc["settled_endorsed"]), (4, 5))
check("基准只算有合法价格的 3 条", pb["n"], 3)
check("基准子集实际中 2（p1/p2）", pb["hits"], 2)
check("期望命中 = 0.9+0.6+0.3 = 1.8", pb["expected_hits"], 1.8)
check("市场隐含命中率 = 60.0%", pb["expected_rate_pct"], 60.0)
check("实际命中率（同一子集）= 66.7%", pb["hit_rate_pct"], 66.7)
check("超出市场价 = +0.2 个", pb["excess_hits"], 0.2)
check("没价格的背书条单列计数（p4/p7）", pb["unpriced"], 2)
check("行表带出判断时价格", {r["market_question"]: r["market_price"] for r in sc["rows"]}["p1"], 0.9)

# 全部没价格 → 基准 None（不拿 0 冒充基准）
_tmp4 = tempfile.mkdtemp()
scorecard.ARCHIVE = Path(_tmp4) / "scorecard.json"
_rec("0xQ1", "q1", None)
scorecard.fetch_settlements(lambda cid: "Yes")
check("全无价格 → price_baseline=None", scorecard.compute_scorecard()["price_baseline"], None)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
