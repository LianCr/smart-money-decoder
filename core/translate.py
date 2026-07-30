"""
core/translate.py — AI 内容的服务端中→英翻译层（构建时翻一次，随缓存持久化）

背景（2026-07-08）：数据世界解冻成实时后，AI 产出每天都是新句子，前端离线词典
ai_en.js（按 6-25 冻结内容生成）永远追不上 → EN 模式大面积回退中文、中英掺杂。
根治：构建看板/简报时把 payload 里所有含中文的显示字符串收集起来，一次 LLM 调用
批量翻译，产出 {中文原文: 英文} 映射挂在 payload["i18n_en"]，随整份响应进缓存
（命中零成本）。前端把它注册进运行时词典，所有既有 t() 渲染点零改动自动翻译。

🔴 契约：
- 失败绝不打断构建（吞错返回空映射 → 前端回退中文+ZhNote，即旧行为）
- 翻译保数字/金额/日期/专有名词原样——数字归代码的红线在翻译层同样成立
- 成本 ~$0.01-0.03/次构建（挂在本来就要烧的构建上，命中缓存零增量）
"""
import json
import re

from core.llm import call_gateway, GatewayError

CJK_RE = re.compile(r"[一-鿿]")
# 这些 key 下的值绝不进翻译（标识符/链接/原始数据，不是显示文案）
SKIP_KEYS = {"wallet", "url", "slug", "market_id", "cid", "source", "asset",
             "token", "raw", "confidence", "market_lean", "follow_call", "i18n_en"}
MAX_STR_CHARS = 2000       # 单条超长（异常数据）不翻
MAX_TOTAL_CHARS = 12000    # 整份 payload 翻译总量上限（防失控）
CHUNK_CHARS = 3000         # 每次 LLM 调用的中文字符上限

_PROMPT = """你是金融/预测市场领域的专业翻译。把下面 JSON 数组里的每条中文翻成自然、专业的英文。

铁律：
1. 所有数字、百分比、$金额、日期、代码、专有名词（Polymarket、YES/NO、edge、IRGC 等）原样保留，一个都不许改
2. 不增删信息、不解释、不评论
3. 只输出**纯 JSON 字符串数组**，长度与输入数组完全一致、顺序一一对应，不要任何其他文字

输入数组：
"""


def collect_cjk_strings(obj, key=None, out=None):
    """递归收集 payload 里所有含中文的显示字符串（去重保序）。返回 list[str]。"""
    if out is None:
        out = []
    if isinstance(obj, str):
        if (key not in SKIP_KEYS and CJK_RE.search(obj)
                and len(obj) <= MAX_STR_CHARS and obj not in out):
            out.append(obj)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if k in SKIP_KEYS:
                continue
            collect_cjk_strings(v, key=k, out=out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            collect_cjk_strings(v, key=key, out=out)
    return out


def _parse_json_array(raw: str):
    """LLM 输出 → list；容忍代码围栏/前后杂讯。失败返回 None（调用方跳过该批）。"""
    s = (raw or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", s).strip()
    try:
        v = json.loads(s)
        return v if isinstance(v, list) else None
    except json.JSONDecodeError:
        pass
    i, j = s.find("["), s.rfind("]")
    if 0 <= i < j:
        try:
            v = json.loads(s[i:j + 1])
            return v if isinstance(v, list) else None
        except json.JSONDecodeError:
            return None
    return None


def translate_texts(texts) -> dict:
    """批量翻译 → {中文: 英文}。分批调用；任一批失败只丢那一批（部分成功也有价值）。"""
    texts = [t for t in texts if t.strip()][: 500]
    # 按 CHUNK_CHARS 分批（单条永远独占不切开）
    batches, cur, cur_len, total = [], [], 0, 0
    for t in texts:
        if total + len(t) > MAX_TOTAL_CHARS:
            break
        if cur and cur_len + len(t) > CHUNK_CHARS:
            batches.append(cur)
            cur, cur_len = [], 0
        cur.append(t)
        cur_len += len(t)
        total += len(t)
    if cur:
        batches.append(cur)

    out = {}
    for batch in batches:
        prompt = _PROMPT + json.dumps(batch, ensure_ascii=False, indent=0)
        try:
            raw = call_gateway(prompt, max_tokens=min(6000, len("".join(batch)) * 2 + 500),
                               timeout=60)
        except GatewayError:
            continue                              # 这批失败 → 前端回退中文+ZhNote（旧行为）
        arr = _parse_json_array(raw)
        if not arr or len(arr) != len(batch):     # 长度不齐 = 对不上号，宁可不用
            continue
        for zh, en in zip(batch, arr):
            if isinstance(en, str) and en.strip():
                out[zh] = en.strip()
    return out


def attach_i18n_en(payload: dict) -> bool:
    """就地给 payload 挂 i18n_en 映射。返回是否真挂上了（供调用方决定要不要回写缓存）。
    任何异常都吞掉——翻译层绝不打断主流程。"""
    try:
        texts = collect_cjk_strings(payload)
        if not texts:
            return False
        m = translate_texts(texts)
        if not m:
            return False
        payload["i18n_en"] = m
        return True
    except Exception:
        return False
