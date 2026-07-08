"""
tools/extract_ai_zh.py — 提取缓存产物里全部"含中文的 AI/动态字符串"，供离线翻译成 locales/ai_en.js。

只读缓存、绝不改缓存（零 re-key 风险）。输出去重后的 zh 串清单 JSON（按长度排序，短的在前）。
覆盖：dashboard 全量 + briefing_api + market_context + recommendations（demo 会打开的所有面）。
UI 骨架串不在此列（那是 locales/en.js 的事）；纯数字/英文串跳过。
"""
import json
import glob
import re

CJK = re.compile(r"[一-鿿]")
# 这些 key 的值不进翻译池（标识符/枚举/UI 已处理的代码串）
SKIP_KEYS = {"wallet", "cid", "condition_id", "market_id", "url", "slug", "date", "as_of",
             "confidence", "follow_call", "market_lean", "alignment", "flag", "source",
             "confidence_reasons",   # 前端 reasonCN 已按模式翻
             "guards", "organize_guards"}


def walk(node, out, key=None):
    if isinstance(node, dict):
        for k, v in node.items():
            walk(v, out, k)
    elif isinstance(node, list):
        for v in node:
            walk(v, out, key)
    elif isinstance(node, str):
        if key in SKIP_KEYS:
            return
        s = node.strip()
        if s and CJK.search(s):
            out.add(s)


def main():
    pool = set()
    files = (glob.glob(".cache/dashboard/*_2026-06-25.json")
             + glob.glob(".cache/briefing_api/*_2026-06-25.json")
             + glob.glob(".cache/market_context/*.json")
             + glob.glob(".cache/analyze/*.json")
             + [".data/recommendations.json", "backtest/cases.json", "backtest/lift_result.json"])
    for p in files:
        try:
            walk(json.load(open(p, encoding="utf-8")), pool)
        except Exception:
            continue
    items = sorted(pool, key=lambda s: (len(s), s))   # 🔴 必须确定性排序（裸 len 的平局次序随 set 哈希漂移，曾导致词典键值错位）
    with open("tools/ai_zh_pending.json", "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=1)
    total_chars = sum(len(s) for s in items)
    print(f"{len(items)} unique zh strings, {total_chars} chars → tools/ai_zh_pending.json")


if __name__ == "__main__":
    main()
