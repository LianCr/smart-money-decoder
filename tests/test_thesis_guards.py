"""
tests/test_thesis_guards.py — ⑥ 看板路径的守卫接入（T2.1，零网络零 token）

背景（AUDIT P1-5）：⑥ 的 rationale/对抗审计此前"只有 prompt、没有代码兜底"。
本文件钉死接入契约（monkeypatch market_thesis 的网关与数据层替身，articles= 注入跳过抓取）：
  1. 脏 rationale（日期推算）→ DURATION flag + 叙事换占位符 + **confidence/lean 原样**（红线4）
  2. bull 假引用 → FABRICATED_CITATION flag + 该侧审计文本换占位符
  3. 恐吓/导向词 → 仅标记（rationale 文本不动——判断性文本，删词=修改输出）
  4. 干净输出 → guard_flags == []
  5. 「距结算 N 天」如实引用不误伤（白名单豁免）
  6. confidence_log 记 rationale + guard_flags（修掉 docstring 撒谎）；缓存回读 flags 保留
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")

import analyzer.market_thesis as mt

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


POOL = [{"title": "Starmer faces confidence vote after poll collapse", "url": "u1",
         "date": "2026-06-10", "summary": "..."}]

CLEAN_REASONER = {"market_lean": "NO", "lean_strength_0_100": 62, "confidence": "med",
                  "pivotal_unknown": "党内是否有人正式发起挑战", "rationale": "证据两侧均薄，价格深度不足，信心受最弱锚封顶。"}


class _FakeGw:
    """按调用顺序吐 bull → bear → reasoner。"""
    def __init__(self, bull, bear, reasoner_json):
        self.script = [bull, bear, json.dumps(reasoner_json, ensure_ascii=False)]

    def __call__(self, prompt, payload):
        return self.script.pop(0)


def build(bull="多头论点。引用：Starmer faces confidence vote", bear="空头论点，无引用。",
          reasoner=None, days_to_resolution=45, tmp=None, cid="0xcid"):
    """跑一次 build_market_thesis，全部外部依赖替身化（articles= 注入跳过真实抓取；
    cid 各场景取不同值——(cid,as_of) 是缓存 key，复用会命中上一场景的快照）。"""
    saved = {k: getattr(mt, k) for k in
             ("_gw", "price_credibility", "realized_vol", "held_token", "event_structure", "CACHE", "LOG")}
    try:
        mt._gw = _FakeGw(bull, bear, reasoner or dict(CLEAN_REASONER))
        mt.price_credibility = lambda cid, as_of: {"line": "价格可信度：中", "days_to_resolution": days_to_resolution}
        mt.realized_vol = lambda token, as_of, days=14: None
        mt.held_token = lambda cid, a: "tok"
        mt.event_structure = lambda cid: {"multi": False}
        mt.CACHE = Path(tmp) / "thesis"
        mt.LOG = Path(tmp) / "confidence_log.jsonl"
        return mt.build_market_thesis("Will Starmer stay?", cid, "2026-08-04", 40,
                                      articles=list(POOL), use_cache=True)
    finally:
        for k, v in saved.items():
            setattr(mt, k, v)


with tempfile.TemporaryDirectory() as tmp:
    print("干净输出")
    t = build(tmp=tmp, cid="0xclean")
    check("guard_flags 恒在且为空", t["guard_flags"], [])
    check("rationale 原样", t["rationale"], CLEAN_REASONER["rationale"])
    check("confidence 原样", t["confidence"], "med")

    print("脏 rationale（日期推算）")
    dirty = dict(CLEAN_REASONER, rationale="局势三周内难解，方向可能对但要等。")
    t = build(reasoner=dirty, tmp=tmp, cid="0xdirty")
    mt2 = t["guard_flags"]
    check("DURATION flag 记录", [v["code"] for v in mt2], ["DURATION_COMPUTED"])
    check("叙事换占位符（拦截降级）", t["rationale"], "（叙述含日期推算，被守卫拦下）")
    check("🔴 confidence 不被守卫触碰", t["confidence"], "med")
    check("🔴 market_lean 不被守卫触碰", t["market_lean"], "NO")

    print("白名单：如实引用代码喂的「距结算 45 天」")
    honest = dict(CLEAN_REASONER, rationale="距结算 45 天，硬障碍未动，信心要压。")
    t = build(reasoner=honest, days_to_resolution=45, tmp=tmp, cid="0xhonest")
    check("如实引用不误伤", t["guard_flags"], [])
    check("rationale 保留", "距结算 45 天" in t["rationale"], True)

    print("bull 假引用")
    t = build(bull="多头论点。引用：Totally fabricated headline nobody wrote", tmp=tmp, cid="0xfake")
    check("FABRICATED_CITATION flag（field=bull）",
          [(v["code"], v["field"]) for v in t["guard_flags"]], [("FABRICATED_CITATION", "bull")])
    check("bull 审计文本换占位符", t["_audit"]["bull"], "（该侧论证引用了文章池外的来源，被守卫拦下）")
    check("bear 审计文本不受牵连", t["_audit"]["bear"], "空头论点，无引用。")
    check("rationale 不受牵连", t["rationale"], CLEAN_REASONER["rationale"])

    print("词表：仅标记不删词")
    feary = dict(CLEAN_REASONER, rationale="这对市场是灾难级信号，但证据仍薄。")
    t = build(reasoner=feary, tmp=tmp, cid="0xfear")
    check("FEAR flag 记录", [v["code"] for v in t["guard_flags"]], ["FEAR_WORDS"])
    check("文本不动（report-only）", t["rationale"], "这对市场是灾难级信号，但证据仍薄。")

    print("留痕与缓存")
    log_lines = [json.loads(l) for l in (Path(tmp) / "confidence_log.jsonl").read_text(encoding="utf-8").splitlines()]
    check("confidence_log 每次构建各一行", len(log_lines), 5)
    check("log 含 rationale（修掉 docstring 撒谎）", "rationale" in log_lines[0], True)
    check("log 含 guard_flags", log_lines[1]["guard_flags"][0]["code"], "DURATION_COMPUTED")
    # 缓存回读：flags 随 (cid,as_of) 快照持久（同盘钱包共享同一份守卫结论）
    cached = json.loads((Path(tmp) / "thesis" / "0xdirty_2026-08-04.json").read_text(encoding="utf-8"))
    check("缓存含 guard_flags", "guard_flags" in cached, True)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
