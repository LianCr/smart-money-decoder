#!/usr/bin/env python3
"""
analyzer/dual_catalyst.py — V3 双向催化剂辩证模块 [MVP · 独立验证]

产品哲学（最高红线）：AI 不替用户揣测聪明钱内心/判水平（假精确=毒药），而在可验证证据处
做更深的辩证组织，把判断权还给用户。正反两个 LLM 都必须**冷静客观**——
负向是"冷静的尽职调查员"，不是"制造恐慌的检察官"。

【刻明砝码材质（红线 #3 的最高级形态）】
系统不替用户"称重"（说哪条更决定性 = 拍板），也不靠纯计数（多≠强，会误导）。
做法：给每条证据打**客观事实类型标签**（当事人直接表态/周边压力/硬事件…），
在每个砝码上刻明真实材质，用户自己就看得出"当事人直接表态"比"外界压力"重——
这个判断是用户做的，不是系统替他做的。

架构（独立模块，不改 decoder / 不碰前端）：
  输入 {market_title, outcome, entry_time}
  进程一·正向：支持向 Tavily 搜（锚 entry_time 窗）→ 真实文章 → LLM① → 支持证据(带类型)
  进程二·负向：威胁向 Tavily 搜（锚 entry_time 窗）→ 真实文章 → LLM② → 威胁证据(带类型)
  代码守卫：① 相关性门（核心实体须在标题，挡边角混入）② 恐吓词 ③ 导向词
            ④ 类型须属固定集、禁混份量词 ⑤ honesty_caveat 代码判定
  ★ 双 LLM 硬隔离：两次独立调用，严禁单次又正又反。

范围纪律（2026-06-20 MVP）：只用 Tavily 一个 source 先验框架；585/Market Context 框架验证后再接。
模型：gateway=sonnet-4.5（现用）；bedrock=sonnet-4-6（4.6 非 3.5，预留分支、未接凭证）。
"""

import json
import os
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests
from dotenv import load_dotenv
from tavily import TavilyClient

from fetcher.news import _build_time_window  # 复用经验证的锚窗逻辑，不改它

load_dotenv()

# ── 配置 ──────────────────────────────────────────────────────────────────────
CLASSROOM_API_URL = "https://4dm65e698a.execute-api.us-west-2.amazonaws.com/prod/invoke"
CLASSROOM_API_KEY = os.environ.get("CLASSROOM_API_KEY")
TAVILY_API_KEY    = os.environ.get("TAVILY_API_KEY")

LLM_BACKEND   = os.environ.get("DUAL_CATALYST_BACKEND", "gateway")  # "gateway" | "bedrock"
GATEWAY_MODEL = "claude-sonnet-4.5"
BEDROCK_MODEL = "claude-sonnet-4-6"   # 🔴 4.6 非 3.5；真实 inference-profile id 等账号开好再填

MAX_TOKENS_OUT  = 1500
REQUEST_TIMEOUT = 30
MAX_RESULTS     = 6
NEGATIVE_BOOST  = "unlikely denied survives remains stays \"will not\" rejects ruled out"

_tavily = TavilyClient(api_key=TAVILY_API_KEY) if TAVILY_API_KEY else None

# ── 固定事实类型标签集（材质，只分类不判强弱）──────────────────────────────────
EVIDENCE_TYPES = ["当事人直接表态", "周边压力情绪信号", "已生效硬事件",
                  "民调数据", "社交舆情信号", "市场价格信号", "其他背景"]
TYPE_FALLBACK  = "其他背景"

# ── 守卫词表 ──────────────────────────────────────────────────────────────────
FEAR_WORDS   = ["致命", "扼杀", "毁灭", "黑天鹅", "灾难", "崩塌", "崩盘", "末日",
                "彻底完蛋", "死刑", "覆灭", "万劫不复", "血洗", "屠杀"]
DIRECTIVE_WORDS = ["建议跟单", "建议跟", "该跟", "值得跟", "胜率高", "赢面",
                   "稳赚", "必赢", "推荐跟", "应该跟", "可以跟"]
# 注：用"胜率高"不用裸"胜率"——裸"胜率"是中性事实（简报本就该如实报胜率+标胜率谎言），
# 误伤事实陈述；判断泄漏靠"该跟/值得/胜率高"等措辞照样拦。
WEIGHT_WORDS = ["决定性", "关键", "致命", "重要", "核心", "压倒性", "主导", "首要", "最强", "最重"]
STOPWORDS = {"out", "by", "the", "a", "an", "will", "whether", "be", "is", "as", "of",
             "in", "on", "to", "for", "and", "or", "us", "uk", "pm"}
MONTHS = {"january", "february", "march", "april", "may", "june", "july", "august",
          "september", "october", "november", "december"}

FIXED_CLOSING = "系统已完成证据陈述，天平由你裁决。"

_TYPE_HINT = ("【固定事实类型标签集】（只能从中选一个，客观分类、**绝不判强弱/重要性**）：\n"
              "  当事人直接表态 / 周边压力情绪信号 / 已生效硬事件 / 民调数据 / 社交舆情信号 / 市场价格信号 / 其他背景\n"
              "  例：'某人明确表态留任或拒绝'→当事人直接表态；'外界要求其辞职的呼声'→周边压力情绪信号；"
              "'法院裁决/投票结果生效'→已生效硬事件；'债券收益率异动'→市场价格信号。\n"
              "  🔴 type 只许是上面集合里的词，不许加'决定性/关键/致命/重要'等份量词。")

POSITIVE_PROMPT = f"""你是一个冷静客观的证据分析员。
下面给你一个预测市场的标题、押注方向 outcome，以及一批锚定在建仓时间窗内的【真实新闻文章】。

任务：只从这批真实文章里，挑出**支持 outcome 成立**方向的证据。

硬规则：
- 只许使用给定文章，**绝不编造**；没有支持证据就返回空数组 []。
- 🔴 **相关性**：文章的主题必须就是该市场的核心实体/事件本身；'别的主题里顺带提一句'的**边角提及不算证据**，不要收。
- 每条输出 {{"title","url","date","reason","type"}}，title/url/date 逐字来自给定文章。
- reason 一句话客观说明它如何支撑 outcome，冷静克制，不用'强烈利好/必然/稳了'等情绪化措辞。
- {_TYPE_HINT}
- 只输出一个 JSON 数组，无解释、无 markdown 围栏。"""

NEGATIVE_PROMPT = f"""你是一个冷静的尽职调查员（**不是制造恐慌的检察官**）。
下面给你一个预测市场的标题、押注方向 outcome，以及一批锚定在建仓时间窗内的【真实新闻文章】。

任务：带对抗性假设——**「假设这注会输」**——做严谨尽调，主动找出**对 outcome 构成实质威胁**的证据。

硬规则：
- 只许使用给定文章，**绝不编造**；没有威胁证据就返回空数组 []。
- 🔴 **相关性**：文章主题必须就是该市场核心实体/事件本身，边角提及不算证据。
- 🔴 **方向铁律**：威胁 = 让 outcome **不成立**的证据。推动 outcome **成立**的新闻不是威胁、是支持证据，**绝不要收进负向栏**。
  例（押注 outcome=Yes「他下台」时）：「外界要求他辞职/辞职呼声增长」= 推动他下台 = 支持 Yes = **不是威胁，丢弃**；
  「他本人拒绝辞职/誓言留任/平息党内叛变」= 阻止他下台 = **才是真威胁，收**。
- 每条输出 {{"title","url","date","reason","type"}}，title/url/date 逐字来自给定文章。
- reason 只陈述「事实 + 对该注的客观影响」，让用户自己判断严重程度，**不要用'决定性/关键/重要'等份量词**。
- 🔴 **严禁情绪化/恐吓修辞**（致命/扼杀/毁灭/黑天鹅/灾难/崩塌等一律不许）。对抗性≠情绪化。
- {_TYPE_HINT}
- 只输出一个 JSON 数组，无解释、无 markdown 围栏。"""


# ── Tavily 双向搜索 ────────────────────────────────────────────────────────────
def _tavily_search(query, start_date, end_date):
    if _tavily is None:
        return []
    if start_date:
        today = datetime.now(tz=timezone.utc).date()
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        days_back = (today - start).days + 1
    else:
        days_back = 30
    try:
        resp = _tavily.search(query, topic="news", days=days_back, max_results=MAX_RESULTS)
    except Exception:
        return []
    out = []
    for item in resp.get("results", []):
        try:
            pub = parsedate_to_datetime(item.get("published_date", "")).strftime("%Y-%m-%d")
        except Exception:
            continue
        if (end_date and pub > end_date) or (start_date and pub < start_date):
            continue
        snippet = (item.get("content") or "")[:300].strip() or item.get("title", "")
        out.append({"title": item.get("title", ""), "url": item.get("url", ""),
                    "date": pub, "snippet": snippet})
    return out


# ── LLM 调用（后端分支）────────────────────────────────────────────────────────
def _approx_tokens(text):
    return int(len(text) / 3.5)


def _call_gateway(combined_input):
    resp = requests.post(
        CLASSROOM_API_URL,
        headers={"Content-Type": "application/json", "x-api-key": CLASSROOM_API_KEY},
        json={"model": GATEWAY_MODEL, "input": combined_input, "maxTokens": MAX_TOKENS_OUT},
        timeout=REQUEST_TIMEOUT)
    if resp.status_code != 200:
        raise RuntimeError(f"gateway {resp.status_code}: {resp.text[:200]}")
    return resp.json().get("output", "")


def _call_bedrock(combined_input):
    raise NotImplementedError(
        "Bedrock 分支预留未接：等账号开好填 inference-profile id（model=claude-sonnet-4-6，非3.5）")


def _call_llm(task_prompt, market_title, outcome, articles):
    combined = (f"{task_prompt}\n\n=== MARKET ===\n标题：{market_title}\n"
                f"押注方向 outcome：{outcome}\n\n=== 真实新闻文章（只许用这些）===\n"
                f"{json.dumps(articles, ensure_ascii=False, indent=2)}")
    if LLM_BACKEND == "gateway":
        output = _call_gateway(combined)
    elif LLM_BACKEND == "bedrock":
        output = _call_bedrock(combined)
    else:
        raise ValueError(f"未知 LLM_BACKEND={LLM_BACKEND}")
    usage = {"in_tokens": _approx_tokens(combined), "out_tokens": _approx_tokens(output)}
    return _parse_json_array(output), usage


def _parse_json_array(output):
    t = re.sub(r"```$", "", re.sub(r"^```(?:json)?", "", output.strip()).strip()).strip()
    m = re.search(r"\[.*\]", t, re.DOTALL)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


# ── 守卫① 相关性门：核心实体须出现在文章标题（挡边角混入）──────────────────────
def _core_entities(market_title):
    toks = re.findall(r"[A-Za-z]+", market_title)
    ents = [t for t in toks if t[0].isupper()
            and t.lower() not in STOPWORDS and t.lower() not in MONTHS]
    distinctive = [e for e in ents if len(e) >= 4]   # 滤掉 US/UK 这类短常见词
    return distinctive or ents


def _relevance_gate(catalysts, entities):
    if not entities:
        return catalysts, []
    kept, dropped = [], []
    for c in catalysts:
        title = str(c.get("title", "")).lower()
        if any(e.lower() in title for e in entities):
            kept.append(c)
        else:
            dropped.append({"title": c.get("title", ""), "reason": "核心实体不在标题=边角混入"})
    return kept, dropped


# ── 守卫④ 类型校验：须属固定集、禁混份量词 ─────────────────────────────────────
def _normalize_type(raw):
    return re.sub(r"[\s/、，,]", "", str(raw))


def _validate_types(catalysts):
    deviations, weight_hits = [], []
    canon = {_normalize_type(t): t for t in EVIDENCE_TYPES}
    for c in catalysts:
        raw = c.get("type", "")
        bad = [w for w in WEIGHT_WORDS if w in str(raw)]
        if bad:
            weight_hits.append({"type": raw, "words": bad})
        norm = _normalize_type(raw)
        if norm in canon and not bad:
            c["type"] = canon[norm]
        else:
            c["type"] = TYPE_FALLBACK
            if norm not in canon:
                deviations.append(raw)
    return deviations, weight_hits


# 内部标记绝不泄露给用户：命中即"静默删掉违规词"，不加任何 [待修] 前缀（违规记录留 _guards 供内部审计）
def _strip_words(reason, words):
    for w in words:
        reason = reason.replace(w, "")
    return re.sub(r"\s{2,}", " ", reason).strip(" ，,、")


# ── 守卫② 恐吓词（负向 reason）──────────────────────────────────────────────────
def _guard_fear(neg_catalysts):
    hits = []
    for c in neg_catalysts:
        reason = str(c.get("reason", ""))
        bad = [w for w in FEAR_WORDS if w in reason]
        if bad:
            hits.append({"reason": reason, "words": bad})
            c["reason"] = _strip_words(reason, bad)   # 删词、不显示标记
    return hits


# ── 去重：一条证据(按 URL/标题)只能进正负其一，禁止同一新闻既支持又威胁 ────────────
def _evi_key(c):
    u = re.sub(r"[?#].*$", "", str(c.get("url", "")).strip().lower()).rstrip("/")
    return u or str(c.get("title", "")).strip().lower()


def _dedup(pos, neg):
    def uniq(items):
        seen, out = set(), []
        for c in items:
            k = _evi_key(c)
            if k and k in seen:
                continue
            seen.add(k)
            out.append(c)
        return out
    pos, neg = uniq(pos), uniq(neg)              # 各自栏内去重
    neg_keys = {_evi_key(c) for c in neg}        # 跨栏冲突：保留在负向(威胁向检索更精准)、从正向删
    pos = [c for c in pos if _evi_key(c) not in neg_keys]
    return pos, neg


# ── 守卫④b 份量词扫 reason（正负都扫，防"决定性/关键"从 reason 漏过）──────────────
def _guard_weight_in_reason(catalysts):
    hits = []
    for c in catalysts:
        reason = str(c.get("reason", ""))
        bad = [w for w in WEIGHT_WORDS if w in reason]
        if bad:
            hits.append({"reason": reason, "words": bad})
            c["reason"] = _strip_words(reason, bad)   # 删词、不显示标记
    return hits


# ── 守卫③ 导向词（天平摘要，理应永不触发）───────────────────────────────────────
def _guard_directive(summary):
    return [w for w in DIRECTIVE_WORDS if w in summary]


# ── 天平摘要：按类型陈列（材质），非按数量 ─────────────────────────────────────
def _build_balance_summary(pos, neg):
    def by_type(xs):
        c = Counter(x.get("type", TYPE_FALLBACK) for x in xs)
        return "、".join(f"{t}×{n}" for t, n in c.items()) if c else "无"
    return (f"正向证据按类型陈列：{by_type(pos)}；负向证据按类型陈列：{by_type(neg)}。"
            f"每条已刻明客观事实类型（材质）——系统不替你称量轻重，不同材质的份量请自行掂量。")


# ── honesty_caveat（代码判定，非 LLM 自称）────────────────────────────────────
def _honesty_caveat(pos, neg, art_neg):
    positive_side = "fully_backed" if pos else "search_vacuum"
    if neg:
        negative_side = "fully_backed"
    elif art_neg:
        negative_side = "true_clearance"   # 搜到文章但没硬伤
    else:
        negative_side = "search_vacuum"    # 没搜到≠没硬伤
    return {"positive_side": positive_side, "negative_side": negative_side}


# ── 对外入口 ──────────────────────────────────────────────────────────────────
def analyze(market_title, outcome, entry_time, as_of_anchor=None):
    """
    as_of_anchor（"YYYY-MM-DD"，可选）= 催化剂时间锚的产品语义开关：
      · 传了（live 实战）→ 锚"现在"，搜截至 as_of 的近 10 天新闻（看**当前**局势为何这个价）。
      · 没传（复盘/回测）→ 锚 entry_time，搜建仓时间窗（看**鲸鱼当初**为何进场）。
    两种场景要的催化剂不同，已结算 case 两者重合所以一直没暴露，live 把它俩分开了。
    """
    if as_of_anchor:
        end_date = as_of_anchor
        start_date = (datetime.strptime(as_of_anchor, "%Y-%m-%d")
                      - timedelta(days=10)).strftime("%Y-%m-%d")
        anchored = True
    else:
        start_date, end_date, anchored = _build_time_window(entry_time)
    base = market_title.rstrip("?").strip()
    entities = _core_entities(market_title)

    art_pos = _tavily_search(base, start_date, end_date)
    art_neg = _tavily_search(f"{base} {NEGATIVE_BOOST}", start_date, end_date)

    pos, usage_p = _call_llm(POSITIVE_PROMPT, market_title, outcome, art_pos)
    neg, usage_n = _call_llm(NEGATIVE_PROMPT, market_title, outcome, art_neg)

    # 守卫① 相关性门
    pos, drop_p = _relevance_gate(pos, entities)
    neg, drop_n = _relevance_gate(neg, entities)
    # 去重：同一条新闻不可既支持又威胁，按 URL/标题正负去重（跨栏保留负向）
    pos, neg = _dedup(pos, neg)
    # 守卫④ 类型校验
    dev_p, wh_p = _validate_types(pos)
    dev_n, wh_n = _validate_types(neg)
    # 守卫④b 份量词扫 reason（正负都扫）
    weight_reason_hits = _guard_weight_in_reason(pos) + _guard_weight_in_reason(neg)
    # 守卫② 恐吓词
    fear_hits = _guard_fear(neg)
    # 天平 + 守卫③ 导向词
    summary = _build_balance_summary(pos, neg)
    directive_hits = _guard_directive(summary)

    return {
        "meta": {"market": market_title, "target_outcome": outcome,
                 "checked_at": end_date or datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")},
        "positive_catalysts": pos,
        "negative_catalysts": neg,
        "evidence_balance_summary": summary + " " + FIXED_CLOSING,
        "honesty_caveat": _honesty_caveat(pos, neg, art_neg),
        "_guards": {"relevance_dropped": drop_p + drop_n,
                    "type_deviations": dev_p + dev_n,
                    "weight_word_hits": wh_p + wh_n,
                    "weight_in_reason_hits": weight_reason_hits,
                    "fear_lexicon_hits": fear_hits,
                    "directive_hits": directive_hits},
        "_audit": {"backend": LLM_BACKEND, "entities": entities,
                   "time_anchored": anchored, "window": [start_date, end_date],
                   "articles_pos": len(art_pos), "articles_neg": len(art_neg),
                   "usage_positive": usage_p, "usage_negative": usage_n,
                   "total_teacher_tokens_approx": (usage_p["in_tokens"] + usage_p["out_tokens"]
                                                   + usage_n["in_tokens"] + usage_n["out_tokens"])}}


# ── 测试基准：Starmer out by May 31, 2026?（outcome=Yes, entry≈2026-05-18）─────
if __name__ == "__main__":
    if not CLASSROOM_API_KEY:
        raise SystemExit("缺 CLASSROOM_API_KEY")
    res = analyze("Starmer out by May 31, 2026?", "Yes", 1779062400)
    a, g = res["_audit"], res["_guards"]

    print("=" * 80)
    print(f"双向催化剂辩证 v2（相关性门+类型标签）· {res['meta']['market']} · 押注 {res['meta']['target_outcome']}")
    print(f"实体={a['entities']} · 窗={a['window']} · 文章 正{a['articles_pos']}/负{a['articles_neg']}")
    print("=" * 80)

    for side, key in [("正向催化剂 · 支持 outcome", "positive_catalysts"),
                      ("负向催化剂 · 实质威胁（冷静尽调）", "negative_catalysts")]:
        print(f"\n【{side}】")
        if not res[key]:
            print("  （空）")
        for c in res[key]:
            print(f"  · [{c.get('type','')}] {c.get('title','')[:64]}  [{c.get('date','')}]")
            print(f"    → {c.get('reason','')}")

    print("\n【天平摘要 · 按材质陈列】")
    print(" ", res["evidence_balance_summary"])
    print("\n【honesty_caveat（代码判定）】", json.dumps(res["honesty_caveat"], ensure_ascii=False))

    print("\n【守卫】")
    print("  ① 相关性挡掉:", g["relevance_dropped"] or "无")
    print("  ② 恐吓词命中:", g["fear_lexicon_hits"] or "无")
    print("  ③ 导向词命中:", g["directive_hits"] or "无")
    print("  ④ 类型越界/份量词(type):", (g["type_deviations"] or "无"), "/", (g["weight_word_hits"] or "无"))
    print("  ④b 份量词(reason):", g["weight_in_reason_hits"] or "无")

    print(f"\n【Token 审计】正 {a['usage_positive']} · 负 {a['usage_negative']} · "
          f"合计≈{a['total_teacher_tokens_approx']}（预估3700/封顶5000）")
