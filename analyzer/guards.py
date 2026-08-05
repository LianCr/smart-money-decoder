"""
analyzer/guards.py — 防幻觉守卫的唯一正本（T2.1：decoder 与 ⑥ 看板共用）。

🔴 契约：纯函数、零 IO、零 LLM、不 import 本包其他模块。每个 check_* 返回
violations 列表（元素 {"code","field","message"}，空列表=干净）——**守卫只负责发现，
拦截/降级/标记的动作由调用方决定**（decoder 沿用 raise、⑥ 换占位符或只记 flag）。
🔴 红线：守卫永远不许回填、修复或抬升 LLM 输出（诚实性是单向的）；
CONFIDENCE_TAMPERED 只供 decoder（红线 4：⑥ 的信心由 market_thesis 直出，代码不兜底）。

词表正本也在这（FEAR_WORDS/DIRECTIVE_WORDS 自 dual_catalyst 移入，那边 re-export
保持旧 import 兼容）——全仓不许出现第二份实现。
"""

import re

# ── 枚举与词表（正本）──────────────────────────────────────────────────────────
FOLLOW_CALL_ENUM = {"ROOM LEFT", "CHASED", "NO BASIS"}

FEAR_WORDS   = ["致命", "扼杀", "毁灭", "黑天鹅", "灾难", "崩塌", "崩盘", "末日",
                "彻底完蛋", "死刑", "覆灭", "万劫不复", "血洗", "屠杀"]
DIRECTIVE_WORDS = ["建议跟单", "建议跟", "该跟", "值得跟", "胜率高", "赢面",
                   "稳赚", "必赢", "推荐跟", "应该跟", "可以跟"]
# 注：用"胜率高"不用裸"胜率"——裸"胜率"是中性事实（简报本就该如实报胜率+标胜率谎言），
# 误伤事实陈述；判断泄漏靠"该跟/值得/胜率高"等措辞照样拦。

# ── DURATION 正则 ─────────────────────────────────────────────────────────────
# 英文版：decoder 原正则逐字搬（升为模块级编译）。
# 不追句式（"within"/"for"/... 这类引导词模型会变着花样绕）
# 改为直接匹配"数字+时间单位"的组合本身——契约里没有任何时长字段，
# 叙述里出现"数字+日/周/月/年"必然是模型自算的。
# 豁免 published_at(YYYY-MM-DD) 和 resolution_date_human("December 31, 2026")
# 的字段原文：它们没有 day/week/month/year 这种英文单位词跟在数字后面，
# 天然不会触发，无需显式排除。
DURATION_RE_EN = re.compile(
    r"\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"\d+(?:\.\d+)?)[\s-]+(more\s+)?(day|week|month|year)s?\b",
    re.IGNORECASE,
)
# 中文版（⑥ 的 rationale 是中文）。日期形式刻意不进匹配面：
#   "6月12日"（用 个月 不用裸 月，日 不收）· "2026年"（四位年号在代码里过滤）
#   "周三"（要求数字在单位**前**，星期几天然不触发）
DURATION_RE_ZH = re.compile(
    r"([0-9]+(?:\.[0-9]+)?|[一两二三四五六七八九十]+)\s*(?:多|余)?\s*(个月|星期|礼拜|小时|天|周|年)"
)
_YEAR_RE = re.compile(r"(?:19|20)\d{2}$")   # "2026年" 是年号不是时长


def _v(code, field, message):
    return {"code": code, "field": field, "message": message}


# ── decoder 六道（原语义逐条保留）────────────────────────────────────────────
def check_follow_call(follow_call):
    """follow_call 必须是三枚举之一。"""
    if follow_call not in FOLLOW_CALL_ENUM:
        return [_v("INVALID_FOLLOW_CALL", "follow_call",
                   f"follow_call 必须是 ROOM LEFT/CHASED/NO BASIS 之一，实际：{follow_call!r}")]
    return []


def check_confidence_tampered(confidence, computed_confidence):
    """confidence 必须等于代码算的 computed_confidence。
    🔴 仅 decoder 用：⑥ 的信心由 market_thesis 直出（红线 4），绝不接这道。"""
    if confidence != computed_confidence:
        return [_v("CONFIDENCE_TAMPERED", "confidence",
                   f"模型擅自改判置信度：computed={computed_confidence}，模型返回 {confidence!r}")]
    return []


def check_fabricated_catalyst(articles, catalyst):
    """articles 为空时 catalyst 必须是空数组（禁止编故事）。None 也算违规（严格 != []）。"""
    if not (articles or []) and catalyst != []:
        return [_v("FABRICATED_CATALYST", "catalyst",
                   f"articles 为空时 catalyst 必须是 []，模型返回：{catalyst!r}")]
    return []


# catalyst 自我否定检测：模型明知不相关还塞进数组的兜底（软门槛被反复绕过，代码端直接抓自供）
SELF_NEGATING_PHRASES = (
    "does not touch",
    "does not relate",
    "unrelated to the resolution",
)


def check_irrelevant_catalyst(catalyst):
    out = []
    for idx, item in enumerate(catalyst or []):
        if not isinstance(item, dict):
            continue
        why = (item.get("why_relevant") or "").lower()
        for phrase in SELF_NEGATING_PHRASES:
            if phrase in why:
                out.append(_v("IRRELEVANT_CATALYST", f"catalyst[{idx}]",
                              f"catalyst[{idx}] 自己承认与结算无关（含 {phrase!r}），"
                              f"按 prompt 规则不应放入数组。原文：{item.get('why_relevant')!r}"))
                break
    return out


def check_duration(text_fields, allowed_durations=frozenset()):
    """模型自产文本里的"数字+时间单位"= 自算时长（EN+ZH 双正则）。

    text_fields：[(字段名, 文本)] —— **字段白名单由调用方定**：只扫模型自产叙述，
    绝不扫新闻标题/摘要（"100 days after" 是正常英语）。
    allowed_durations：{(数字串, 单位)} —— ⑥ 的契约里代码喂过「距结算 N 天」，
    模型如实引用不算自算；除这个豁免值外的任何数字+单位仍拦。
    """
    out = []
    for field_name, text in text_fields:
        if not isinstance(text, str):
            continue
        m = DURATION_RE_EN.search(text)
        if m:
            out.append(_v("DURATION_COMPUTED", field_name,
                          f"{field_name} 含时长推算 {m.group(0)!r}，违反 HARD RULE 2。原文：{text!r}"))
            continue
        for zm in DURATION_RE_ZH.finditer(text):
            num, unit = zm.group(1), zm.group(2)
            if unit == "年" and _YEAR_RE.fullmatch(num):
                continue                        # "2026年" 是年号
            if (num, unit) in allowed_durations:
                continue                        # 如实引用代码喂的时长
            out.append(_v("DURATION_COMPUTED", field_name,
                          f"{field_name} 含时长推算 {zm.group(0)!r}，违反 HARD RULE 2。原文：{text!r}"))
            break
    return out


def check_entry_price_denied(entry_price, edge_analysis):
    """entry_price 已知时，模型不得把它当未知。
    判据（防误伤，实证过 "unknown by date but paid 79.83¢" 案例）：数值本身或美分写法
    任一出现即视为「已使用」，只有「数值不在场」且「出现否认表述」才违规。"""
    if entry_price is None:
        return []
    edge_text = (edge_analysis or "").lower()
    price_unit_str = f"{entry_price:g}".lower()          # 0.7983
    cents_str      = f"{round(entry_price * 100, 2):g}"  # 79.83
    price_used = (price_unit_str in edge_text) or (cents_str in edge_text)

    denial_phrases = (
        "entry price is unknown",
        "entry price unknown",
        "entry_price is unknown",
        "entry_price is null",
        "wallet's entry price is unknown",
        "cost basis is unknown",
    )
    denies = any(p in edge_text for p in denial_phrases)
    if denies and not price_used:
        return [_v("ENTRY_PRICE_DENIED", "edge_analysis",
                   f"输入 entry_price={entry_price} 是已知数值，但模型在 edge_analysis "
                   f"里既未引用该数值、又声称其未知。原文：{edge_analysis!r}")]
    return []


# ── ⑥ 新增：编造引用（T2.1 点名，全仓首个实现）────────────────────────────────
_CITE_MARKERS = ("引用：", "引用:")
_MIN_CITE_LEN = 8       # 归一化后过短的候选跳过（"等"/"同上"这类碎片不判）


def _norm(s):
    """归一化：小写 + 去空白/标点（CJK 字符在 unicode \\w 内，保留）。"""
    return re.sub(r"[\W_]+", "", str(s).lower())


def check_fabricated_citation(texts, pool):
    """「引用：」段里的标题必须在 shared_pool 内（bull/bear prompt 要求列引用）。

    texts：{字段名: 文本}；pool：[{title,...}]（title 可为 None，容忍）。
    无「引用」段 = 无引用 = 不违规。匹配 = 归一化后双向子串（引用常是截断/意译的标题）。
    """
    titles = [_norm(p.get("title")) for p in (pool or [])
              if isinstance(p, dict) and p.get("title")]
    out = []
    for field_name, text in (texts or {}).items():
        if not isinstance(text, str):
            continue
        seg = None
        for marker in _CITE_MARKERS:
            if marker in text:
                seg = text.split(marker, 1)[1]
                break
        if seg is None:
            continue
        # 候选切分：优先书名号；否则按 换行/分号/顿号 切（不按英文逗号——标题自带逗号）
        brackets = re.findall(r"《([^》]+)》", seg)
        candidates = brackets if brackets else re.split(r"[\n;；、]+", seg)
        for cand in candidates:
            nc = _norm(cand)
            if len(nc) < _MIN_CITE_LEN:
                continue
            if not any(nc in t or t in nc for t in titles):
                out.append(_v("FABRICATED_CITATION", field_name,
                              f"{field_name} 引用了文章池外的来源：{cand.strip()[:80]!r}"))
    return out


# ── 词表扫描（report-only：⑥ rationale 是判断性文本，命中只标不删）──────────────
def scan_lexicon(text, words, code, field_name):
    if not isinstance(text, str):
        return []
    hits = [w for w in words if w in text]
    if hits:
        return [_v(code, field_name, f"{field_name} 含守卫词：{'、'.join(hits)}")]
    return []
