"""
tests/test_guards.py — analyzer/guards.py 纯函数契约（T2.1，零网络零 key）

背景（AUDIT P1-5/T2.4 #1）：六道守卫此前零测试——尤其 DURATION_COMPUTED 的豁免边界
（decoder 注释断言 "2026-06-15"/"December 31, 2026" 天然不触发）三年无人验证过。
本文件按"该拦的拦、不该拦的放"正负样本对钉死每道守卫的契约：
  1. INVALID_FOLLOW_CALL / CONFIDENCE_TAMPERED / FABRICATED_CATALYST / IRRELEVANT_CATALYST
  2. DURATION_COMPUTED：EN 触发集 + 🔴豁免边界（日期字面）+ ZH 触发集 + ZH 日期放行
     （"6月12日"/"2026年"/"周三"）+ 「距结算 N 天」白名单豁免 + 字段白名单语义
  3. ENTRY_PRICE_DENIED：实证过的误伤案例原文必须放行（数值在场即已使用）
  4. FABRICATED_CITATION（T2.1 点名新写）：在池/不在池/无引用段/None 标题/书名号切分
  5. 词表 report-only 扫描
"""

import sys

sys.path.insert(0, ".")

from analyzer import guards

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


def codes(violations):
    return [v["code"] for v in violations]


# ── 1. 枚举/篡改/编造/自供 ───────────────────────────────────────────────────
print("枚举与卡片守卫")
check("follow_call 合法枚举放行", guards.check_follow_call("ROOM LEFT"), [])
check("follow_call 非法枚举拦", codes(guards.check_follow_call("BUY NOW")), ["INVALID_FOLLOW_CALL"])
check("follow_call None 拦", codes(guards.check_follow_call(None)), ["INVALID_FOLLOW_CALL"])

check("confidence 一致放行", guards.check_confidence_tampered("中", "中"), [])
check("confidence 改判拦", codes(guards.check_confidence_tampered("高", "低")), ["CONFIDENCE_TAMPERED"])

check("articles 空 + catalyst 空 放行", guards.check_fabricated_catalyst([], []), [])
check("articles 空 + catalyst 非空 拦",
      codes(guards.check_fabricated_catalyst([], [{"title": "x"}])), ["FABRICATED_CATALYST"])
check("articles 空 + catalyst=None 也拦（严格 != []）",
      codes(guards.check_fabricated_catalyst(None, None)), ["FABRICATED_CATALYST"])
check("articles 非空 + catalyst 任意 放行",
      guards.check_fabricated_catalyst([{"title": "a"}], [{"title": "x"}]), [])

check("why_relevant 自供 'does not touch' 拦",
      codes(guards.check_irrelevant_catalyst([{"why_relevant": "This does NOT touch the vote."}])),
      ["IRRELEVANT_CATALYST"])
check("why_relevant 正常表述放行",
      guards.check_irrelevant_catalyst([{"why_relevant": "Directly affects the resolution date."}]), [])
check("catalyst 含非 dict 项不崩", guards.check_irrelevant_catalyst(["oops"]), [])

# ── 2. DURATION：EN 触发 + 豁免边界（T2.4 #1）────────────────────────────────
print("DURATION_COMPUTED · EN")
for bad in ("resolves in three weeks", "2 days left", "about 1.5 months of runway",
            "a six-month window", "two more weeks to go", "10 YEARS from now"):
    check(f"EN 触发：{bad!r}", codes(guards.check_duration([("f", bad)])), ["DURATION_COMPUTED"])
for ok in ("published 2026-06-15", "resolution date December 31, 2026",
           "entry at 79.83 cents", "the June 2026 vote", "Q3 2026 earnings"):
    check(f"EN 豁免：{ok!r}", guards.check_duration([("f", ok)]), [])

print("DURATION_COMPUTED · ZH")
for bad in ("三周内难解", "还剩 45 天", "拖了六个月", "近 10 年最低", "两星期后结算", "48 小时窗口"):
    check(f"ZH 触发：{bad!r}", codes(guards.check_duration([("f", bad)])), ["DURATION_COMPUTED"])
for ok in ("6月12日的报道", "2026年大选", "周三的听证会", "定于12日表决", "礼拜堂集会"):
    check(f"ZH 放行：{ok!r}", guards.check_duration([("f", ok)]), [])

# 白名单豁免：代码喂过「距结算 45 天」，模型如实引用不算自算；别的数字仍拦
allowed = {("45", "天")}
check("白名单：如实引用『距结算 45 天』放行",
      guards.check_duration([("f", "距结算 45 天，方向可能对但信心要压")], allowed), [])
check("白名单：豁免值之外的『30 天』仍拦",
      codes(guards.check_duration([("f", "距结算 45 天，但 30 天内难有硬事件")], allowed)),
      ["DURATION_COMPUTED"])

# 字段白名单语义：只扫传入字段；violation 标对字段名
vs = guards.check_duration([("rationale", "还要 三周"), ("pivotal_unknown", "clean text")])
check("只报违规字段", [v["field"] for v in vs], ["rationale"])
check("非字符串字段跳过不崩", guards.check_duration([("f", None), ("g", 42)]), [])

# ── 3. ENTRY_PRICE_DENIED ───────────────────────────────────────────────────
print("ENTRY_PRICE_DENIED")
check("否认且数值不在场 拦",
      codes(guards.check_entry_price_denied(0.7983, "Entry price is unknown, so no edge math.")),
      ["ENTRY_PRICE_DENIED"])
check("实证误伤案例放行（unknown by date but paid 79.83¢）",
      guards.check_entry_price_denied(0.7983, "Entry price is unknown by date but the wallet paid 79.83 cents."), [])
check("价格单位写法在场放行",
      guards.check_entry_price_denied(0.7983, "cost basis is unknown? no — entered at 0.7983."), [])
check("entry_price=None 不检查", guards.check_entry_price_denied(None, "entry price is unknown"), [])
check("无否认表述放行", guards.check_entry_price_denied(0.5, "solid edge remains."), [])

# ── 4. FABRICATED_CITATION（新写）────────────────────────────────────────────
print("FABRICATED_CITATION")
POOL = [{"title": "Starmer faces confidence vote after poll collapse", "url": "u1"},
        {"title": None, "url": "u2"},                          # None 标题容忍
        {"title": "UK bond yields spike amid leadership doubts", "url": "u3"}]

check("引用在池内（截断标题）放行",
      guards.check_fabricated_citation(
          {"bull": "论点如上。引用：Starmer faces confidence vote"}, POOL), [])
check("引用池外标题 拦",
      codes(guards.check_fabricated_citation(
          {"bull": "论点。引用：Sunak announces snap election tomorrow"}, POOL)),
      ["FABRICATED_CITATION"])
check("无引用段 = 不违规", guards.check_fabricated_citation({"bear": "纯论述，没有引用列表"}, POOL), [])
check("书名号切分：一真一假只报假的",
      codes(guards.check_fabricated_citation(
          {"bear": "引用：《UK bond yields spike amid leadership doubts》《Totally made up story here》"}, POOL)),
      ["FABRICATED_CITATION"])
check("顿号切分多条均在池 放行",
      guards.check_fabricated_citation(
          {"bull": "引用：Starmer faces confidence vote、UK bond yields spike amid leadership doubts"}, POOL), [])
check("过短碎片跳过（'等' 不判）",
      guards.check_fabricated_citation({"bull": "引用：等"}, POOL), [])
check("文本 None 不崩", guards.check_fabricated_citation({"bull": None}, POOL), [])
check("池为空 + 有引用 → 拦（引用了不存在的池）",
      codes(guards.check_fabricated_citation(
          {"bull": "引用：Some long fabricated headline here"}, [])), ["FABRICATED_CITATION"])

# ── 5. 词表 report-only ──────────────────────────────────────────────────────
print("词表扫描")
vs = guards.scan_lexicon("这对 Starmer 是致命打击，市场崩盘在即", guards.FEAR_WORDS, "FEAR_WORDS", "rationale")
check("恐吓词命中报 code", codes(vs), ["FEAR_WORDS"])
check("命中词进 message", "致命" in vs[0]["message"] and "崩盘" in vs[0]["message"], True)
check("导向词命中", codes(guards.scan_lexicon("这单值得跟", guards.DIRECTIVE_WORDS, "DIRECTIVE_WORDS", "rationale")),
      ["DIRECTIVE_WORDS"])
check("干净文本零命中", guards.scan_lexicon("证据两侧均薄，信心受最弱锚封顶", guards.FEAR_WORDS, "FEAR_WORDS", "r"), [])
check("None 文本不崩", guards.scan_lexicon(None, guards.FEAR_WORDS, "FEAR_WORDS", "r"), [])

# ── 词表单一正本：dual_catalyst re-export 与 guards 同一对象 ────────────────────
from analyzer import dual_catalyst
check("FEAR_WORDS 单一正本（dual_catalyst re-export）", dual_catalyst.FEAR_WORDS is guards.FEAR_WORDS, True)
check("DIRECTIVE_WORDS 单一正本", dual_catalyst.DIRECTIVE_WORDS is guards.DIRECTIVE_WORDS, True)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
