"""
tests/test_market_thesis.py — market_thesis 纯逻辑测试（无网络、不调网关）

⑥ 的信心现在由 market_thesis 直出（红线4），它对脏 AI 输出的解析韧性直接决定
看板会不会退化。覆盖：
  1. _parse_json：干净 JSON / markdown 围栏 / 炸掉的 JSON 正则捞字段 / lean 归一
  2. map_wallet：顺 edge / 逆 edge / unclear→未定
"""

import sys
sys.path.insert(0, ".")

from analyzer.market_thesis import _parse_json, map_wallet

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


# ── 1. 干净 JSON ──────────────────────────────────────────────────────────────
clean = '{"market_lean": "NO", "lean_strength_0_100": 72, "confidence": "med", "pivotal_unknown": "x", "rationale": "y"}'
out = _parse_json(clean)
check("干净 JSON lean", out["market_lean"], "NO")
check("干净 JSON strength", out["lean_strength_0_100"], 72)
check("干净 JSON confidence", out["confidence"], "med")

# ── 2. markdown 围栏包裹 + 前后废话 ──────────────────────────────────────────
fenced = '好的，以下是裁决：\n```json\n{"market_lean": "YES", "lean_strength_0_100": 85, "confidence": "high", "pivotal_unknown": "p", "rationale": "r"}\n```\n以上。'
out = _parse_json(fenced)
check("围栏 JSON lean", out["market_lean"], "YES")
check("围栏 JSON confidence", out["confidence"], "high")

# ── 3. 内部未转义引号炸掉 loads → 正则逐字段捞 ────────────────────────────────
broken = ('{"market_lean": "NO", "lean_strength_0_100": 60, "confidence": "low", '
          '"pivotal_unknown": "他说"没戏"之后局势变了", "rationale": "证据 "一边倒" 支持 NO"}')
out = _parse_json(broken)
check("炸 JSON 仍捞出 lean", out["market_lean"], "NO")
check("炸 JSON 仍捞出 strength", out["lean_strength_0_100"], 60)
check("炸 JSON 仍捞出 confidence", out["confidence"], "low")

# ── 4. lean 归一：小写/带尾巴/unclear ─────────────────────────────────────────
check("lean 'no' 归一 NO", _parse_json('{"market_lean": "no"}')["market_lean"], "NO")
check("lean 'YES（略倾向）' 归一 YES",
      _parse_json('{"market_lean": "YES（略倾向）"}')["market_lean"], "YES")
check("lean 'unclear' 保留", _parse_json('{"market_lean": "unclear"}')["market_lean"], "unclear")

# ── 5. 完全垃圾输出 → 空 dict 不崩（上游有 med 兜底）────────────────────────────
out = _parse_json("模型今天罢工了，没有 JSON")
check("纯垃圾 → 无 lean", out.get("market_lean"), None)
check("纯垃圾 → 不崩返回 dict", isinstance(out, dict), True)

# ── 6. map_wallet：顺/逆/未定 ─────────────────────────────────────────────────
thesis_no = {"market_lean": "NO"}
check("市场 NO + 押 No = 顺 edge", map_wallet(thesis_no, "No")["alignment"], "顺 edge")
check("市场 NO + 押 Yes = 逆 edge", map_wallet(thesis_no, "Yes")["alignment"], "逆 edge")
check("unclear → 未定", map_wallet({"market_lean": "unclear"}, "Yes")["alignment"], "未定")
check("unclear → with_edge=None", map_wallet({"market_lean": "unclear"}, "Yes")["with_edge"], None)
check("大小写归一：lean 'no' + side 'NO' = 顺", map_wallet({"market_lean": "no"}, "NO")["alignment"], "顺 edge")

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
