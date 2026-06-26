"""
analyzer/market_thesis.py — 市场命题级对抗推理（取代"钱包方向归因"的 ⑥ 信心来源）

为什么换：旧信心矩阵锚在钱包 pnl（钱包参照系）→ 出现"证据反对这一注、信心却给高"（_market_thesis_probe 实证：
wan123 押 Yes、证据倾向 No，老矩阵仍因 +10% pnl 给 HIGH）。本模块把参照系从钱包换成**市场**：
同一份文章池 → bull 论证 YES ‖ bear 论证 NO → reasoner 中立裁决，**直出单一最终信心**（不拼分项、不被 pnl/热度奉承）。
按 (cid, as_of) 缓存 → 一个盘算一次、喂所有钱包：两个反向钱包共享同一份市场观，信心一致，差异挪到"顺/逆 edge"。

🔴 守卫与契约：
- bull/bear/reasoner **只许用真实文章**（不编造）；价格/日期数学归代码喂入（reasoner 不算）。
- 信心由 reasoner **直出**（按产品决策撤掉代码兜底守卫）；安全靠：prompt 铁律 + 结构上已去 pnl 锚 + 对抗式平衡输入。
- 不可见兜底也撤了，改为**可观测**：每次把 confidence/lean/rationale 追加进 .data/confidence_log.jsonl，
  等盘真结算由记分牌回验"高信心是否真命中"——不拦输出，只留证据（验证优于假设）。
- 社媒只作减分/背离（情绪非事实、可刷量），不许用热度加信心。
"""
import json
import math
import statistics
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from analyzer.dual_catalyst import _call_gateway, _tavily_search, NEGATIVE_BOOST
from fetcher.heisenberg import call, results
from briefing.board_feed import held_token

CACHE = Path(".cache/market_thesis")
LOG = Path(".data/confidence_log.jsonl")
CONF_VALUES = {"high", "med", "medium", "low"}


# ── prompts ───────────────────────────────────────────────────────────────────
BULL = ("你是多头分析师。请尽全力论证下面这个预测市场会**解决为 YES（{a}）**。\n"
        "铁律：只能用给定的真实文章、不许编造；不做任何日期/概率数学。\n"
        "输出 3-4 句最强多头论点 + 末尾『引用：』列出用到的文章标题。客观克制、不用情绪化词。")
BEAR = ("你是空头分析师。请尽全力论证下面这个预测市场会**解决为 NO（{b}）**。\n"
        "铁律：只能用给定的真实文章、不许编造；不做任何日期/概率数学。\n"
        "输出 3-4 句最强空头论点 + 末尾『引用：』列出用到的文章标题。**若可用证据稀薄，请如实说明**。客观克制。")

REASONER = """你是中立裁决人，不站队。给你：①多头论点 ②空头论点 ③共享文章池 ④市场价隐含概率 ⑤社媒信号 ⑥【输入可信度】（代码算：价格深不深/是否鲸控/市场犹豫度/距结算）。
对抗式权衡后，输出**严格 JSON、不要多余文字**（用中文）：
{{
  "market_lean": "YES" | "NO" | "unclear",
  "lean_strength_0_100": <证据有多压倒；别硬凑 50，一边倒就给高>,
  "confidence": "high" | "med" | "low",
  "pivotal_unknown": "<决定胜负、当前还没解决的那个问题，一句>",
  "rationale": "<2-3 句给用户看的最终理由，平实，可点出关键驱动（证据vs价格、价格可不可信、社媒存疑），但不要罗列分项>"
}}
🔴铁律：
- confidence 是对【市场判断】的确信，**绝不因为某钱包在盈利、或社媒热度高就抬高**。
- **覆盖度薄 ≠ 证据弱**：空头那侧报道少，先分清是"真站不住"还是"没人报道"。
- 🔴**可信度加权**：价格隐含概率是第三个声音，但**先按⑥给它打折**——价格薄/鲸控/高波动 → 价格降权、多靠证据、并**压低总信心**；价格深+广参与+稳 → 价格可当强锚。
- 🔴**最可信锚封顶**：confidence 被你**最可信的那个锚**封顶。若价格不可信、证据也薄，**即便两者方向一致也别给高**（两个弱信号一致 ≠ 可信）。
- **时间可信度**：胜负手若在剩余窗口内难解（距结算还很久 + 硬障碍未动）→ 方向可能对、但信心要压。
- 🔴**多结局别当二元**：若价格行标了"多结局事件"，隐含概率是"此候选 vs 全场"、不是二元 Yes/No；别把 (100-p)% 当"倾向 NO"，要相对基线 1/N 看这候选是领跑还是陪跑。
- 社媒只能**减分/提示背离**（情绪非事实、可刷量），不许用它加信心。"""


def _gw(prompt, payload):
    return _call_gateway(prompt + "\n\n" + payload)


# ── Phase 1 可信度修正信号（不投新票、只决定"价格/证据该信几分"）─────────────────
def _ff(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def price_credibility(cid):
    """575 Market Insights → 价格可信度紧凑结论。薄盘/鲸控/参与稀 → 价格作为锚要降权。
    返回 {trust:high|med|low, line, days_to_resolution, raw} 或 None。"""
    try:
        r = results(call(575, {"condition_id": cid}))
    except Exception:
        return None
    if not r:
        return None
    x = r[0]
    liq_pct = _ff(x.get("liquidity_percentile"))
    top1 = _ff(x.get("top1_wallet_pct"))
    top10 = _ff(x.get("top10_wallet_pct"))
    uniq = x.get("unique_traders_7d")
    vtrend = x.get("volume_trend")
    flags = [k for k in ("liquidity_risk_flag", "whale_control_flag", "trade_concentration_flag",
                         "squeeze_risk_flag", "volume_collapse_risk_flag") if x.get(k)]
    bad = bool(x.get("liquidity_risk_flag") or x.get("whale_control_flag")
               or x.get("trade_concentration_flag") or (uniq is not None and uniq < 30))
    great = bool((liq_pct or 0) >= 85 and not x.get("whale_control_flag")
                 and (uniq or 0) >= 80 and (top1 or 100) < 35)
    trust = "low" if bad else ("high" if great else "med")
    line = (f"价格可信度={trust.upper()}：流动性 {x.get('liquidity_tier')}({liq_pct}百分位) · "
            f"头部集中 top1={top1}% top10={top10}% · 近7天 {uniq} 人参与 · 成交量 {vtrend}"
            + (f" · ⚠{','.join(flags)}" if flags else ""))
    days = None
    ed = str(x.get("end_date", ""))[:10]
    if ed:
        try:
            days = (datetime.strptime(ed, "%Y-%m-%d") - datetime.strptime(_AS_OF_HOLDER[0], "%Y-%m-%d")).days
        except Exception:
            pass
    return {"trust": trust, "line": line, "days_to_resolution": days,
            "raw": {"liquidity_percentile": liq_pct, "top1_wallet_pct": top1,
                    "unique_traders_7d": uniq, "volume_trend": vtrend, "flags": flags}}


def realized_vol(token, as_of, days=14):
    """568 K线 → outcome token 的已实现日波动 = 市场自身犹豫度（与新闻无关）。高波动→压信心。"""
    if not token:
        return None
    end = int(datetime.strptime(as_of, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
    start = end - days * 86400
    try:
        c = results(call(568, {"token_id": token, "interval": "1d",
                               "start_time": str(start), "end_time": str(end)}))
    except Exception:
        return None
    c = sorted(c or [], key=lambda z: str(z.get("candle_time", "")))
    closes = [_ff(z.get("close")) for z in c if z.get("close") is not None]
    closes = [c0 for c0 in closes if c0 is not None]
    if len(closes) < 3:
        return None
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))
            if closes[i - 1] > 0 and closes[i] > 0]
    vol = statistics.pstdev(rets) if len(rets) > 1 else 0.0
    desc = "高(市场自己没拿定)" if vol >= 0.12 else ("低(共识已稳)" if vol < 0.06 else "中")
    line = f"市场自身犹豫度={desc}：近{len(closes)}日已实现波动 {round(vol, 3)}，收盘 {[round(c0, 2) for c0 in closes[-6:]]}"
    return {"vol": vol, "desc": desc, "line": line}


_AS_OF_HOLDER = ["2026-06-25"]   # price_credibility 算 days 用（build 时设）

_EVENT_MAP = {}
EVENT_CACHE = Path(".cache/event_structure.json")


def _event_map():
    """懒建并文件缓存 event_slug→兄弟市场数 / cid→event_slug（一次 574 扫描，免费）。"""
    if _EVENT_MAP:
        return _EVENT_MAP
    data = None
    if EVENT_CACHE.exists():
        try:
            data = json.loads(EVENT_CACHE.read_text(encoding="utf-8"))
        except Exception:
            data = None
    if data is None:
        from collections import Counter
        counts, cid2ev = Counter(), {}
        for off in range(0, 200 * 6, 200):
            try:
                rows = results(call(574, {"closed": "False"}, limit=200, offset=off))
            except Exception:
                break
            if not rows:
                break
            for m in rows:
                ev = m.get("event_slug")
                if ev:
                    counts[ev] += 1
                    cid2ev[m.get("condition_id")] = ev
        data = {"counts": dict(counts), "cid2ev": cid2ev}
        try:
            EVENT_CACHE.parent.mkdir(parents=True, exist_ok=True)
            EVENT_CACHE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
    _EVENT_MAP.update(data)
    return _EVENT_MAP


def event_structure(cid):
    """多结局检测：同 event_slug 的兄弟市场数。≥3=多结局(八选一)，隐含概率不可当二元 Yes/No 读。
    扫描覆盖不到→默认 n=1(当二元，安全降级)。"""
    m = _event_map()
    ev = (m.get("cid2ev") or {}).get(cid)
    n = (m.get("counts") or {}).get(ev, 1) if ev else 1
    return {"multi": n >= 3, "n_candidates": n,
            "baseline_pct": round(100.0 / n, 1) if n else None, "event_slug": ev}


def _social_line(social):
    s = social or {}
    if not s:
        return "无社媒信号"
    return (f"acceleration={s.get('acceleration')} · 作者多样性={s.get('author_diversity_pct')}% · "
            f"有机={s.get('organic')} · 帖数={s.get('tweet_count')}（🔴情绪非事实、可刷量，只作减分/背离）")


def fetch_shared_pool(market_title, as_of, window_days=10, max_each=8):
    """市场级共享文章池（**不按 outcome 条件化**）：base 查 + base+负向词查 的并集，去重。
    时间窗锚 as_of 前 window_days（live 看当前局势）。两个反向钱包拿到的是同一池。"""
    base = market_title.rstrip("?").strip()
    end = as_of
    start = (datetime.strptime(as_of, "%Y-%m-%d") - timedelta(days=window_days)).strftime("%Y-%m-%d")
    arts = (_tavily_search(base, start, end) or []) + (_tavily_search(f"{base} {NEGATIVE_BOOST}", start, end) or [])
    seen, pool = set(), []
    for a in arts:
        key = (a.get("title") or a.get("url") or "").strip().lower()
        if key and key not in seen:
            seen.add(key)
            pool.append({"title": a.get("title"), "url": a.get("url"),
                         "date": a.get("published_at") or a.get("date"),
                         "summary": a.get("snippet") or a.get("summary")})
    return pool[:max_each * 2]


def _cache_path(cid, as_of):
    return CACHE / f"{cid}_{as_of}.json"


def _log_confidence(cid, market_title, as_of, rj):
    """可观测：记一行供记分牌回验高信心是否真命中（不改输出）。"""
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": int(time.time()), "cid": cid, "market": market_title, "as_of": as_of,
                "market_lean": rj.get("market_lean"), "lean_strength": rj.get("lean_strength_0_100"),
                "confidence": rj.get("confidence"), "pivotal_unknown": rj.get("pivotal_unknown"),
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass


def build_market_thesis(market_title, cid, as_of, implied_prob_yes,
                        articles=None, social=None, outcomes=("Yes", "No"), use_cache=True):
    """返回 {market_lean, lean_strength, confidence, pivotal_unknown, rationale, _audit{...}}，按 (cid,as_of) 缓存。
    articles=None → 自己抓市场级共享池；否则用传入的（如复用看板已抓的 news_stream）。"""
    cp = _cache_path(cid, as_of)
    if use_cache and cp.exists():
        try:
            return json.loads(cp.read_text(encoding="utf-8"))
        except Exception:
            pass

    pool = articles if articles is not None else fetch_shared_pool(market_title, as_of)
    a, b = outcomes
    pool_txt = json.dumps(pool, ensure_ascii=False, indent=2)
    es = event_structure(cid)
    if es["multi"]:        # 🔴多结局：隐含概率是"此候选 vs 全场"，不可当二元读
        price_line = (f"🔴多结局事件（{es['n_candidates']} 个候选，基线≈{es['baseline_pct']}%）：此候选 Yes 隐含 {implied_prob_yes}%"
                      f"——**不可当二元读**，别把 {100-implied_prob_yes}% 当'倾向 NO'；要相对 {es['baseline_pct']}% 基线判断偏高/偏低")
    else:
        price_line = f"市场价：Yes 隐含 {implied_prob_yes}%（→ 市场倾向 NO {100-implied_prob_yes}%）"
    market_blob = f"市场：{market_title}\n{price_line}\n\n文章池（只许用这些）：\n{pool_txt}"

    # Phase 1 可信度修正（575 价格可信度 + 568 已实现波动 + 距结算）——代码算、喂 reasoner 给价格/证据打折
    _AS_OF_HOLDER[0] = as_of
    pc = price_credibility(cid)
    rv = realized_vol(held_token(cid, a), as_of)
    cred_lines = [s for s in [pc and pc["line"], rv and rv["line"],
                              pc and pc.get("days_to_resolution") is not None and f"距结算 {pc['days_to_resolution']} 天"] if s]
    cred_block = "\n".join(cred_lines) or "（可信度信号暂缺）"

    bull = _gw(BULL.format(a=a), market_blob)
    bear = _gw(BEAR.format(b=b), market_blob)
    reasoner_payload = (f"市场：{market_title}\n{price_line}\n"
                        f"社媒：{_social_line(social)}\n\n=== ⑥ 输入可信度（代码算，用于给价格/证据打折）===\n{cred_block}\n\n"
                        f"=== 多头论点 ===\n{bull}\n\n=== 空头论点 ===\n{bear}\n\n"
                        f"=== 共享文章池({len(pool)}条) ===\n{pool_txt}")
    raw = _gw(REASONER, reasoner_payload)

    rj = _parse_json(raw)
    conf = str(rj.get("confidence", "")).lower()
    if conf not in CONF_VALUES:            # 解析兜底（不是改信心，是防脏输出）
        rj["confidence"] = "med"
    if conf == "medium":
        rj["confidence"] = "med"

    result = {
        "market_lean": rj.get("market_lean"),
        "lean_strength": rj.get("lean_strength_0_100"),
        "confidence": rj.get("confidence"),
        "pivotal_unknown": rj.get("pivotal_unknown"),
        "rationale": rj.get("rationale"),
        "implied_prob_yes": implied_prob_yes,
        "shared_pool": pool,                          # ⑤ 市场级共享新闻池（两个反向钱包共用同一批）
        "input_trust": {"price": pc, "vol": rv, "lines": cred_lines},   # Phase 1 可信度修正信号
        "event_structure": es,                                          # Phase 2 多结局结构
        "_audit": {"bull": bull, "bear": bear, "n_articles": len(pool), "as_of": as_of,
                   "raw_reasoner": raw[:1200]},
    }
    _log_confidence(cid, market_title, as_of, rj)
    if use_cache:
        cp.parent.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def map_wallet(thesis, wallet_side):
    """把某钱包的押注 side 贴到共享市场观上 → 顺/逆 edge（跟单价值维度，与信心解耦）。"""
    lean = str(thesis.get("market_lean", "")).upper()
    side = str(wallet_side or "").upper()
    if lean not in ("YES", "NO"):
        return {"alignment": "未定", "with_edge": None}
    return {"alignment": "顺 edge" if side == lean else "逆 edge", "with_edge": side == lean}


def _parse_json(text):
    """robust：先 json.loads，再用正则**补齐任何缺失字段**（即便 loads 成功但漏字段、或内部未转义引号/markdown 围栏炸掉），
    最后归一 market_lean。比"成功就直接 return"更稳——漏一个 market_lean 不会让整条 ⑥ 退化。"""
    import re
    t = re.sub(r"```(?:json)?", "", text or "").strip()
    m = re.search(r"\{.*\}", t, re.DOTALL)
    blob = m.group(0) if m else t
    try:
        out = json.loads(blob)
        if not isinstance(out, dict):
            out = {}
    except Exception:
        out = {}
    if not out.get("market_lean"):
        mm = re.search(r'"market_lean"\s*:\s*"?\s*(YES|NO|unclear)', blob, re.I)
        if mm:
            out["market_lean"] = mm.group(1)
    if out.get("lean_strength_0_100") is None:
        ls = re.search(r'"lean_strength_0_100"\s*:\s*(\d+)', blob)
        if ls:
            out["lean_strength_0_100"] = int(ls.group(1))
    if not out.get("confidence"):
        cf = re.search(r'"confidence"\s*:\s*"?(high|med|medium|low)', blob, re.I)
        if cf:
            out["confidence"] = cf.group(1).lower()
    if not out.get("pivotal_unknown"):
        pv = re.search(r'"pivotal_unknown"\s*:\s*"(.*?)"\s*,\s*"rationale"', blob, re.DOTALL)
        if pv:
            out["pivotal_unknown"] = pv.group(1)
    if not out.get("rationale"):
        ra = re.search(r'"rationale"\s*:\s*"(.*?)"\s*\}?\s*$', blob, re.DOTALL)
        if ra:
            out["rationale"] = ra.group(1)
    ml = str(out.get("market_lean") or "").upper().strip()   # 归一：'no'/'NO（倾向）'/带空格 → YES|NO
    if ml.startswith("YES"):
        out["market_lean"] = "YES"
    elif ml.startswith("NO"):
        out["market_lean"] = "NO"
    elif ml.startswith("UNCLEAR"):
        out["market_lean"] = "unclear"
    return out
