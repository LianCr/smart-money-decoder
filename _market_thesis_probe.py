"""
_market_thesis_probe.py — 诊断脚本（带 _ 前缀，零产物、一次性）。

验证"市场命题级对抗推理"取代"钱包方向归因"是否成立，并把【老信心矩阵 vs 新信心分项】在同一盘上对比出来。
单盘：US-Iran Final Nuclear Deal by Aug 18。共享文章池来自已缓存的 news_stream（不重抓 Tavily）。
管线：bull(论证 YES) ‖ bear(论证 NO) → reasoner(中立裁决：证据倾向 + 覆盖度质量 + 价格-证据缺口 + 社媒减分 → 市场级信心)。
然后把两个反向钱包贴到这份共享市场观上（顺/逆 edge），与老矩阵的 high/medium 并排。
🔴 烧老师 token：3 次 gateway 调用，预算 ~5-8k。跑：`.venv/bin/python -u _market_thesis_probe.py`
"""
import glob
import json
import re

from analyzer.dual_catalyst import _call_gateway

YES_W = "0xde7be6d489bce070a959e0cb813128ae659b5f4b"   # wan123 · 押 Yes · 入场20¢ → +10%
NO_W = "0xb51b3beffd13cde071ed799e70a7b0b598e8b4d9"     # cambridgeisaac · 押 No · -1.7%
MARKET = "US-Iran Final Nuclear Deal by August 18, 2026?"
YES_IMPLIED = 22       # 市场 Yes 价 ≈22¢ → 隐含 22% 概率达成


def _dash(w):
    return json.load(open(glob.glob(f".cache/dashboard/{w}_*.json")[0]))


def _pool(d):
    """共享文章池（title+date+summary），来自缓存 news_stream，不重抓。"""
    return [{"title": a.get("title"), "date": a.get("date"), "summary": a.get("summary")}
            for a in (d.get("news_stream") or [])]


def _social_line(d):
    s = d.get("social") or {}
    return (f"acceleration={s.get('acceleration')} · 作者多样性={s.get('author_diversity_pct')}% · "
            f"有机={s.get('organic')} · 帖数={s.get('tweet_count')}（🔴情绪非事实、可刷量，只作减分/背离）")


BULL = ("你是多头分析师。请尽全力论证下面这个预测市场会**解决为 YES（协议会在 8/18 前达成）**。\n"
        "铁律：只能用给定的真实文章、不许编造；不做任何日期/概率数学。\n"
        "输出 3-4 句最强多头论点 + 末尾用『引用：』列出你用到的文章标题。客观克制、不用情绪化词。")
BEAR = ("你是空头分析师。请尽全力论证下面这个预测市场会**解决为 NO（协议不会在 8/18 前达成）**。\n"
        "铁律：只能用给定的真实文章、不许编造；不做任何日期/概率数学。\n"
        "输出 3-4 句最强空头论点 + 末尾用『引用：』列出你用到的文章标题。若可用证据稀薄，请如实说明。客观克制。")

REASONER = """你是中立裁决人，不站队。给你：①多头论点 ②空头论点 ③共享文章池 ④市场价隐含概率 ⑤社媒信号。
对抗式权衡后，输出**严格 JSON**（不要多余文字）：
{{
  "market_lean": "YES" | "NO" | "unclear",
  "lean_strength_0_100": <证据有多压倒，别硬凑50>,
  "components": {{
    "evidence_decisiveness": "<high|med|low + 一句>",
    "coverage_quality": "<🔴空头那侧薄，是'真站不住'还是'没人报道'？显式判断，别把'报道少'当'证据弱'>",
    "price_vs_evidence_gap": "<证据倾向 vs 价格隐含{yes_implied}%，差在哪 = edge 还是市场知道新闻没覆盖的东西>",
    "social_signal": "<只作减分/背离用：价格动了但社媒稀薄/疑似刷量→扣信心；不许用热度加信心>"
  }},
  "confidence": "high|med|low",
  "pivotal_unknown": "<决定胜负、当前还没解决的那个问题>",
  "rationale": "<2-3句>"
}}
🔴铁律：confidence 是对【市场判断】的确信，**绝不因为某个钱包在盈利就抬高**；覆盖度薄≠证据弱。"""


def _gw(prompt, payload):
    return _call_gateway(prompt + "\n\n" + payload)


def main():
    dy, dn = _dash(YES_W), _dash(NO_W)
    pool = _pool(dy)            # 两钱包共享同一市场，池子一致；用 Yes 页的（更全 7 条）
    pool_txt = json.dumps(pool, ensure_ascii=False, indent=2)
    market_blob = f"市场：{MARKET}\n市场价：Yes≈{YES_IMPLIED}¢（隐含 {YES_IMPLIED}% 达成）\n\n文章池（只许用这些）：\n{pool_txt}"

    print(f"共享文章池 {len(pool)} 条 · 跑 bull/bear/reasoner（3 次 gateway）…\n")
    bull = _gw(BULL, market_blob)
    print("── BULL（论证 YES）──\n" + bull.strip() + "\n")
    bear = _gw(BEAR, market_blob)
    print("── BEAR（论证 NO）──\n" + bear.strip() + "\n")

    reasoner_payload = (f"市场：{MARKET}\n市场价隐含：Yes {YES_IMPLIED}%（→ 市场倾向 NO {100-YES_IMPLIED}%）\n"
                        f"社媒：{_social_line(dy)}\n\n=== 多头论点 ===\n{bull}\n\n=== 空头论点 ===\n{bear}\n\n"
                        f"=== 共享文章池({len(pool)}条) ===\n{pool_txt}")
    raw = _gw(REASONER.format(yes_implied=YES_IMPLIED), reasoner_payload)
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    try:
        rj = json.loads(m.group(0)) if m else {}
    except Exception:
        rj = {}
        print("⚠ reasoner JSON 解析失败，原文：\n", raw)

    # 老矩阵信心（从缓存读）
    oy = dy.get("reasoning", {}); on = dn.get("reasoning", {})

    print("\n" + "=" * 72)
    print("【新·市场命题级】一个市场 = 一份判断（两钱包共享）")
    print("=" * 72)
    print(f"  市场倾向: {rj.get('market_lean')} · 强度 {rj.get('lean_strength_0_100')}/100")
    print(f"  市场级信心: {str(rj.get('confidence')).upper()}")
    comp = rj.get("components", {})
    for k in ("evidence_decisiveness", "coverage_quality", "price_vs_evidence_gap", "social_signal"):
        print(f"    - {k}: {comp.get(k)}")
    print(f"  胜负手: {rj.get('pivotal_unknown')}")
    print(f"  裁决: {rj.get('rationale')}")

    lean = str(rj.get("market_lean", "")).upper()
    print("\n  → 把两个钱包贴到这份共享市场观上（信心一致，跟单价值各算）:")
    for tag, side, oldr in [("wan123", "Yes", oy), ("cambridgeisaac", "No", on)]:
        align = "顺 edge" if side.upper() == lean else ("逆 edge" if lean in ("YES", "NO") else "未定")
        print(f"    {tag:16s} 押{side:3s} → {align}")

    print("\n" + "=" * 72)
    print("【老·信心矩阵】钱包方向归因 + pnl 驱动（每钱包各一个数）")
    print("=" * 72)
    print(f"  wan123(Yes,+10%)       信心={str(oy.get('confidence')).upper():6s} 依据={oy.get('confidence_reasons')}")
    print(f"  cambridgeisaac(No,-1.7%) 信心={str(on.get('confidence')).upper():6s} 依据={on.get('confidence_reasons')}")
    print("\n  🔴露馅点：wan123 证据其实在反对它(市场倾向", lean, ")，老矩阵却因 +10% pnl 给了高。")


if __name__ == "__main__":
    main()
