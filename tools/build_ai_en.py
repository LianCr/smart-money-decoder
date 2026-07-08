"""
tools/build_ai_en.py — AI 内容翻译层构建器（累积式）。

单一事实源 = tools/ai_en_map.json（zh→en 累积表）。本轮新串的翻译写在 ai_en_T4.py
（键 = 当前 ai_zh_pending.json 下标），构建时并入累积表并回写 → 索引只一次性使用、
下次重提取不再依赖。输出 frontend/src/locales/ai_en.js + 覆盖率审计（漏网即报错）。
"""
import json
import re
import sys

sys.path.insert(0, "tools")

PATTERNS = [
    re.compile(r"^还有约(\d+(?:\.\d+)?)天$"),
    re.compile(r"^距结算 (\d+) 天$"),
    re.compile(r"^(Yes|No) 价格变动 ([+-]\d+(?:\.\d+)?)%（(\d+)% → (\d+)%）$"),
    re.compile(r"^近 48h 仅 (\d+) 买 / (\d+) 卖，无显著动作（沉闷持仓）$"),
    re.compile(r"^过去 3h (\d+) 笔 BUY\(\$([\d,]+)\) / 24h (\d+) 笔 BUY\(\$([\d,]+)\)，长期持仓刚被新一轮加仓激活$"),
    re.compile(r"^市场自身犹豫度=(高\(市场自己没拿定\)|低\(共识已稳\)|中)：近(\d+)日已实现波动 ([\d.]+)，收盘 (\[.*\])$"),
    re.compile(r"^价格可信度=(HIGH|MED|LOW)：流动性 (.+?)\(([\d.]+)百分位\) · 头部集中 top1=([\d.]+)% top10=([\d.]+)% · 近7天 (\d+) 人参与 · 成交量 (.+)$"),
    re.compile(r"^\[入场后\] ", re.S),
    re.compile(r"^\[入场前\] ", re.S),
]
IN_EN_DICT = {"其他背景", "已生效硬事件", "当事人直接表态", "周边压力情绪信号",
              "民调数据", "社交舆情信号", "市场价格信号"}


def main():
    pending = json.load(open("tools/ai_zh_pending.json", encoding="utf-8"))
    acc = json.load(open("tools/ai_en_map.json", encoding="utf-8"))
    # T4 = 锚点→译文：锚点先按"池中精确串"绑定，否则要求"唯一包含"（歧义/零命中即报错）
    try:
        from ai_en_T4 import T4
    except ImportError:
        T4 = {}
    errors = []
    for anchor, en in T4.items():
        if anchor in pending:
            acc[anchor] = en
            continue
        hits = [s for s in pending if anchor in s and not s.startswith("```json")]   # blob 不渲染、不参与绑定
        if len(hits) == 1:
            acc[hits[0]] = en
        else:
            errors.append(f"锚点命中 {len(hits)} 条（须唯一）: {anchor[:50]}")
    if errors:
        print("✗ 锚点错误：")
        for e in errors:
            print("  " + e)
        sys.exit(1)

    uncovered = []
    for zh in pending:
        if zh in acc or zh in IN_EN_DICT or zh.startswith("```json"):
            continue
        if any(p.match(zh) for p in PATTERNS):
            continue
        uncovered.append(zh)

    json.dump(acc, open("tools/ai_en_map.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    lines = ["// 自动生成：tools/build_ai_en.py（源：tools/ai_en_map.json 累积表）。",
             "// AI 产出内容的精确翻译层；模式层见 ai_patterns.js。手改无效，改 tools/ 后重跑生成。",
             "const AI_MAP = new Map(["]
    for zh, en in acc.items():
        lines.append(f"  [{json.dumps(zh, ensure_ascii=False)}, {json.dumps(en, ensure_ascii=False)}],")
    lines += ["]);", "export default AI_MAP;", ""]
    open("frontend/src/locales/ai_en.js", "w", encoding="utf-8").write("\n".join(lines))

    print(f"✓ ai_en.js: {len(acc)} exact pairs")
    if uncovered:
        print(f"✗ 漏网 {len(uncovered)} 条（写 tools/ai_en_T4.py 补翻后重跑）：")
        for zh in uncovered:
            print(f"  [{pending.index(zh)}] {zh[:70]}")
        sys.exit(1)
    print("✓ 覆盖率审计通过")


if __name__ == "__main__":
    main()
