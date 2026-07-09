"""
tests/test_translate.py — core/translate.py 服务端翻译层（monkeypatch call_gateway，无网络）

背景：实时世界后 AI 产出每天是新句子，前端离线词典追不上 → EN 模式中英掺杂。
构建时批量翻译挂 payload["i18n_en"]，前端注册运行时词典。覆盖：
  1. collect_cjk_strings：递归收集/去重保序/跳过 SKIP_KEYS/纯英文不收/超长不收
  2. translate_texts：批量映射、LLM 输出带围栏容忍、长度不齐整批丢弃、GatewayError 只丢该批
  3. attach_i18n_en：正常挂载返回 True；无中文/全失败返回 False 且不挂；异常吞掉不炸
  4. 已挂 i18n_en 的 payload 再收集时跳过自身（懒自愈不会把译文再翻一遍）
"""

import sys
sys.path.insert(0, ".")

import json

import core.translate as tr
from core.llm import GatewayError

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


# ── 1. collect_cjk_strings ────────────────────────────────────────────────────
payload = {
    "wallet": "0x中文不该被收",                     # SKIP_KEYS
    "reasoning": {"reasoning": "证据显示分歧", "pivotal_unknown": "能否解决",
                  "confidence": "med", "market_lean": "NO"},
    "news_stream": [{"title": "english only", "summary": "中文摘要一", "url": "http://x/中文"},
                    {"summary": "中文摘要一"}],     # 重复 → 去重
    "behavior": {"fact": "过去 24h 大额 SELL"},
    "nested": [[{"deep": "深层中文"}]],
    "long": "长" * 3000,                            # 超 MAX_STR_CHARS 不收
}
got = tr.collect_cjk_strings(payload)
check("递归收集+去重+跳过 SKIP/纯英文/超长",
      got, ["证据显示分歧", "能否解决", "中文摘要一", "过去 24h 大额 SELL", "深层中文"])

check("空 payload → 空列表", tr.collect_cjk_strings({}), [])
check("纯英文 payload → 空列表", tr.collect_cjk_strings({"a": "hello", "b": [1, 2]}), [])


# ── 2/3. translate_texts / attach_i18n_en（monkeypatch call_gateway）──────────
class _Fake:
    """按调用次序吐响应；元素可为字符串（LLM 输出）或 Exception。"""
    def __init__(self, script):
        self.script = list(script)
        self.prompts = []

    def __call__(self, prompt, max_tokens=2000, timeout=30):
        self.prompts.append(prompt)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


_real = tr.call_gateway
try:
    # 正常翻译（带 markdown 围栏也要能解析）
    tr.call_gateway = _Fake(['```json\n["evidence shows", "can it resolve"]\n```'])
    out = tr.translate_texts(["证据显示分歧", "能否解决"])
    check("正常批量翻译", out, {"证据显示分歧": "evidence shows", "能否解决": "can it resolve"})

    # 长度不齐 → 整批丢弃（宁可不用也不错配）
    tr.call_gateway = _Fake(['["only one"]'])
    check("长度不齐整批丢弃", tr.translate_texts(["甲", "乙"]), {})

    # 纯垃圾输出 → 不炸、空映射
    tr.call_gateway = _Fake(['我不是 JSON'])
    check("垃圾输出 → 空映射不炸", tr.translate_texts(["甲"]), {})

    # GatewayError → 该批丢弃不炸
    tr.call_gateway = _Fake([GatewayError("TIMEOUT", "超时")])
    check("GatewayError → 空映射不炸", tr.translate_texts(["甲"]), {})

    # 分批：两条各 2000 字超 CHUNK_CHARS(3000) → 2 次调用，各自成功
    big_a, big_b = "甲" * 2000, "乙" * 2000
    tr.call_gateway = _Fake([json.dumps(["A" * 5]), json.dumps(["B" * 5])])
    out = tr.translate_texts([big_a, big_b])
    check("超限自动分批（2 次调用）", (len(out), out.get(big_a), out.get(big_b)),
          (2, "A" * 5, "B" * 5))

    # attach：正常挂载
    tr.call_gateway = _Fake(['["evidence"]'])
    p = {"reasoning": {"reasoning": "证据"}}
    ok = tr.attach_i18n_en(p)
    check("attach 挂载成功返回 True", ok, True)
    check("attach 后 payload 带映射", p.get("i18n_en"), {"证据": "evidence"})

    # attach：无中文 → False 不挂
    p = {"a": "english"}
    check("无中文 → False", tr.attach_i18n_en(p), False)
    check("无中文不挂 key", "i18n_en" in p, False)

    # attach：翻译全失败 → False 不挂（前端回退 ZhNote 旧行为）
    tr.call_gateway = _Fake([GatewayError("UNREACHABLE", "x")])
    p = {"reasoning": {"reasoning": "证据"}}
    check("全失败 → False 不挂", tr.attach_i18n_en(p), False)

    # 4. 已挂 i18n_en 再收集 → 跳过自身（懒自愈幂等）
    p = {"reasoning": {"reasoning": "证据"}, "i18n_en": {"证据": "evidence"}}
    check("已挂映射不被再收集", tr.collect_cjk_strings(p), ["证据"])
finally:
    tr.call_gateway = _real

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
