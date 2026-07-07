"""
api/main.py — smart-money-decoder 的 FastAPI 后端

单端点：GET /analyze?wallet=<address>
内部跑完整 pipeline（positions → trades v2 / activity → news → decoder），
返回最终卡片 JSON（含代码直填的 price_info 与 warnings）。

错误统一返回 {"error": <reason>, "message": <中文人读>}，HTTP 状态码分层：
  - 钱包无合格仓位（NO_POSITIONS / NO_POLITICAL_POSITIONS / ALL_BELOW_MIN_VALUE） → 404
  - 地址格式非法（INVALID_ADDRESS）                                              → 400
  - 上游 API 失败（Polymarket / Tavily / 关键词网关）                            → 502
  - decoder 失败（DecoderError 任意 reason）                                     → 500

整条链要跑十几秒，pipeline 全程 print 到 stdout 方便观察进度。

启动：
    .venv/bin/uvicorn api.main:app --reload --port 8000
"""

import json
import os
import sys
import time
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

load_dotenv()

from fetcher.polymarket import get_top_political_position
from fetcher.activity import get_entry_time, ActivityAPIError
from fetcher.trades import get_entry_time_v2, get_wallet_profile, get_wallet_pnl_history
from fetcher.news import get_news_for_market
from analyzer.decoder import decode_position, DecoderError
from briefing.assemble import load_or_build_briefing
from briefing.organize import organize_briefing
from fetcher.positions import get_top_political_position_hz
from briefing.market_context import load_or_build as build_market_context
from briefing.market_context import get_behavior_flags
from analyzer.reasoner_v3 import build_facts
from analyzer.market_thesis import build_market_thesis, map_wallet
from fetcher.heisenberg import call as hz_call, results as hz_results, AGENTS as HZ_AGENTS
from briefing import board_feed
from fetcher.social import social_pulse
import scorecard

app = FastAPI(title="smart-money-decoder API", version="1.0")

# ── CORS：放行本地两个常见前端开发端口 ────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",   # CRA / Next 默认
        "http://localhost:5173",   # Vite 默认
    ],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# ── reason → HTTP 状态码映射 ──────────────────────────────────────────────────
_NO_POSITION_REASONS = {"NO_POSITIONS", "NO_POLITICAL_POSITIONS", "ALL_BELOW_MIN_VALUE", "NO_OPEN_POSITIONS"}
_BAD_REQUEST_REASONS = {"INVALID_ADDRESS"}
# 其余 fetcher 层 reason（API_TIMEOUT / RATE_LIMITED / API_ERROR / KEYWORD_EXTRACT_FAILED /
# TAVILY_*）一律视为上游失败 → 502


def _log(msg: str) -> None:
    """pipeline 进度打到 stdout（uvicorn 控制台可见）。"""
    print(msg, file=sys.stdout, flush=True)


def _err(status: int, reason: str, message: str) -> JSONResponse:
    """统一错误出口，body 形如 {"error": reason, "message": ...}。"""
    _log(f"   ✗ [{status}] {reason} — {message}")
    return JSONResponse(status_code=status, content={"error": reason, "message": message})


def _resolve_entry_time(wallet: str, condition_id: str) -> int | None:
    """trades v2 优先，失败/None 回退老 activity，再不行 None（均不致命）。"""
    try:
        et = get_entry_time_v2(wallet, condition_id)
        if et is not None:
            _log(f"   ✓ entry_time={et}（trades v2）")
            return et
    except ActivityAPIError as e:
        _log(f"   ⚠️  trades v2 失败 [{e.reason}]，回退 activity")
    try:
        et = get_entry_time(wallet, condition_id)
        if et is not None:
            _log(f"   ✓ entry_time={et}（activity fallback）")
            return et
    except ActivityAPIError as e:
        _log(f"   ⚠️  activity 也失败 [{e.reason}]")
    _log("   ⚠️  entry_time=None（合法降级）")
    return None


BACKTEST_RESULT = Path("backtest/lift_result.json")   # 整体 lift 汇总（git 跟踪、手填自 lift_v1.md，不重跑）
CASES_PATH      = Path("backtest/cases.json")          # 6 个案例故事卡（git 跟踪、手填自 final_samples.md）
ANALYZE_CACHE   = Path(".cache/analyze")   # 实时解读结果缓存：key=小写钱包_日期，命中=零 token 秒回
BRIEFING_CACHE  = Path(".cache/briefing_api")   # 完整简报响应缓存（结构化+人话），命中=零 token 秒回
DASHBOARD_CACHE = Path(".cache/dashboard")      # 统一看板整份响应缓存（①-⑥），命中=零 token 秒回
REASONER_CACHE  = Path(".cache/reasoner_v3")     # ⑥ reasoner 独立缓存：改 ⑤/② 重建看板不重烧 ⑥
BOARD_AI_CACHE  = Path(".cache/board_ai")        # ⑤综述+②what_bet 独立缓存：改新闻流结构/前端不重烧 AI
# 🔴 里程碑（2026-06-25）：拔掉 6-20 快照钉子，推进到数据世界"现在"(6-25 固定)。
# 一次性解锁：当前数据 + 社媒动量并排(585 仅实时) + 记分牌从今天起真实积累。
# 暂用固定 6-25（不用 wall-clock date.today()）以免数据世界每天前进、缓存天天过期重烧；
# 真上 Bedrock/有预算时再切 date.today() 走逐日实时。
BRIEFING_AS_OF  = os.environ.get("BRIEFING_AS_OF", "2026-06-25")


def _difficulty(entry_price):
    """
    判断难度系数（距 0.5 越近越难）：1 - |entry_price - 0.5| * 2，∈ [0,1]。
    用**建仓价** entry_price（不是 current_price）：押在 0.5 附近=迷雾博弈，押在 0.97=近明牌。
    entry_price 缺失 → None（前端显示"难度不可得"，不崩）。
    """
    if not isinstance(entry_price, (int, float)):
        return None
    return round(1 - abs(entry_price - 0.5) * 2, 4)


def _enrich_difficulty(data):
    """读取时为每个回测样本注入 difficulty（不改 result.json / pipeline）。"""
    for s in data.get("samples", []):
        try:
            entry = s["t7_card"]["price_info"]["entry_price"]
        except (KeyError, TypeError):
            entry = None
        s["difficulty"] = _difficulty(entry)
    return data


@app.get("/backtest")
def backtest():
    """
    Track Record：6 个案例故事卡（主体）+ 整体 lift 汇总（进阶）。

    两者都是 git 跟踪的静态文件、零 token、不重跑：
      - cases  ← backtest/cases.json（手填自 final_samples.md，含 T-7/T-1 演变）
      - lift   ← backtest/lift_result.json（N=94 汇总，给想深究的人）
    """
    out = {"cases": [], "summary": {}, "lift": None}
    try:
        cj = json.loads(CASES_PATH.read_text(encoding="utf-8"))
        out["cases"] = cj.get("cases", [])
        out["summary"] = cj.get("summary", {})
    except Exception as e:
        _log(f"\n=== /backtest cases 读取失败：{e} ===")
    try:
        out["lift"] = json.loads(BACKTEST_RESULT.read_text(encoding="utf-8"))
    except Exception as e:
        _log(f"\n=== /backtest lift 读取失败：{e} ===")
    _log(f"\n=== /backtest （{len(out['cases'])} 案例 + lift 汇总）===")
    return out


@app.get("/analyze")
def analyze(wallet: str):
    """跑完整 pipeline，返回解读卡片 JSON 或分层错误。"""
    t0 = time.time()
    wallet = (wallet or "").strip()
    _log(f"\n=== /analyze wallet={wallet[:14]}… ===")

    # ── 第 0 层：钱包+日期 外层缓存（命门：花 token 前先短路整条 pipeline）──────
    cache_key  = f"{wallet.lower()}_{date.today().isoformat()}"
    cache_path = ANALYZE_CACHE / f"{cache_key}.json"
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            _log(f"   ⚡ CACHE HIT {cache_key} — 零 token 秒回")
            return cached
        except Exception:
            pass  # 缓存损坏则忽略，照常跑

    # ── 第 1 层：最大政治仓位 ──────────────────────────────────────────────────
    _log("① 拉取最大政治仓位")
    position = get_top_political_position(wallet)
    if position.get("error"):
        reason = position["reason"]
        if reason in _BAD_REQUEST_REASONS:
            return _err(400, reason, position["message"])
        if reason in _NO_POSITION_REASONS:
            return _err(404, reason, position["message"])
        return _err(502, reason, position["message"])  # 上游 API 失败
    _log(f"   ✓ {position['market_question'][:48]} · {position['outcome']}")

    # ── 第 2 层：建仓时间（trades v2 → activity → None）─────────────────────────
    _log("② 查询建仓时间")
    entry_time = _resolve_entry_time(wallet, position["market_id"])

    # ── 第 3 层：时间窗新闻 ────────────────────────────────────────────────────
    _log("③ 搜索时间窗新闻")
    news = get_news_for_market(position["market_question"], entry_time)
    if news.get("error"):
        return _err(502, news["reason"], news["message"])  # Tavily / 关键词网关失败
    _log(f"   ✓ {len(news['articles'])} 条 · time_anchored={news['time_anchored']}")

    # ── 组装数据契约 ──────────────────────────────────────────────────────────
    assembled = {
        "market_question":     position["market_question"],
        "outcome":             position["outcome"],
        "entry_price":         position["entry_price"],
        "current_price":       position["current_price"],
        "position_value":      position["position_value"],
        "pnl_pct":             position["pnl_pct"],
        "cash_pnl":            position["cash_pnl"],
        "resolution_criteria": position["resolution_criteria"],
        "resolution_date":     position["resolution_date"],
        "entry_time":          entry_time,
        "articles":            news["articles"],
        "time_anchored":       news["time_anchored"],
        "search_query":        news["search_query"],
    }

    # ── 第 4 层：AI 解码 ──────────────────────────────────────────────────────
    _log("④ AI 解读（课堂网关 sonnet-4.5）")
    try:
        card = decode_position(assembled)
    except DecoderError as e:
        return _err(500, e.reason, e.message)  # decoder 失败一律 500
    _log(f"   ✓ 卡片生成完毕（耗时 {time.time() - t0:.1f}s）")

    # ── 钱包展示资料（头像/昵称 + 历史 PnL 曲线），均 best-effort，绝不阻塞 ────
    profile = get_wallet_profile(wallet)
    pnl_history = get_wallet_pnl_history(wallet)

    # ── 组装响应：decoder 卡片 + 代码直填的 price_info + 市场元信息 ────────────
    # price_info 不经 AI，直接取 position 真值（防幻觉，与 CLI 渲染同源）
    response = {
        "profile": profile,
        "pnl_history": pnl_history,
        "market_question": position["market_question"],
        "outcome":         position["outcome"],
        "resolution_date": position["resolution_date"],
        "entry_time":      entry_time,
        "time_anchored":   news["time_anchored"],
        "search_query":    news["search_query"],
        "price_info": {
            "entry_price":    position["entry_price"],
            "current_price":  position["current_price"],
            "position_value": position["position_value"],
            "cash_pnl":       position["cash_pnl"],
            "pnl_pct":        position["pnl_pct"],
        },
        "what_bet":      card.get("what_bet"),
        "catalyst":      card.get("catalyst", []),
        "edge_analysis": card.get("edge_analysis"),
        "follow_call":   card.get("follow_call"),
        "confidence":    card.get("confidence"),
        "reasoning":     card.get("reasoning"),
        "warnings":      card.get("warnings", []),
    }
    # 写外层缓存（只缓存成功卡片；错误路径在上方已 return，到不了这里）
    try:
        ANALYZE_CACHE.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")
        _log(f"   💾 已缓存 {cache_key}（同钱包当天再点零 token、秒回）")
    except Exception:
        pass
    # 📒 诚实记分牌钩子（best-effort，绝不阻塞）：v2 decode 判断存档
    scorecard.record_judgment(
        wallet=wallet, cid=position["market_id"], market_question=position["market_question"],
        outcome=position["outcome"], market_price=position["current_price"],
        follow_call=card.get("follow_call"), confidence=card.get("confidence"),
        source="decode", settle_date=position.get("resolution_date"))
    return response


# 从市场问题里抠出主体实体（喂给 GDELT 硬过滤）。专有名词小写、去停用词。
_Q_STOP = {"will", "the", "a", "an", "be", "is", "are", "by", "out", "as", "of", "in",
           "on", "to", "for", "and", "or", "next", "win", "wins", "won", "leader",
           "president", "presidential", "election", "democratic", "republican", "world",
           "cup", "fifa", "june", "july", "august", "may", "april", "march", "who", "what",
           "prime", "minister", "united", "kingdom", "states", "government", "party",
           "leadership", "national", "general", "american", "british", "before", "after"}


def _entities_from_question(q: str) -> list[str]:
    import re
    toks = re.findall(r"[A-Za-z]{3,}(?:-[A-Za-z]{3,})*", q or "")   # 连字名保留整体（Jae-myung 不拆；US-Iran 仍取 Iran，US 2 字母跳过）
    ents, seen = [], set()
    for t in toks:
        low = t.lower()
        if t[0].isupper() and low not in _Q_STOP and low not in seen:
            ents.append(low)
            seen.add(low)
    return ents[:5] or ["politics"]


@app.get("/market-context")
def market_context(wallet: str, cid: str = "", outcome: str = ""):
    """市场 Context 视图：钱包→顶仓→Polymarket 风格上下文（价格异动×as-of 催化剂×巨鲸 48h 行为流）。
    复用 synthesizer 内部缓存：同(盘,as_of,侧,钱包)命中=零 token。
    可选 cid/outcome：直指某盘（钉盘复盘，不走顶仓解析）。"""
    wallet = (wallet or "").strip()
    cid = (cid or "").strip()
    _log(f"\n=== /market-context wallet={wallet[:14]}… cid={cid[:14] or '(auto)'} ===")

    if cid:                                   # 钉指定盘：跳过顶仓解析（含已缓存富节点复盘）
        outcome = outcome or "Yes"
        question = ""
    else:                                     # 默认：钱包 → 最大未结算政治顶仓
        position = get_top_political_position_hz(wallet, as_of=BRIEFING_AS_OF)
        if position.get("error"):
            reason = position["reason"]
            if reason in _BAD_REQUEST_REASONS:
                return _err(400, reason, position["message"])
            if reason in _NO_POSITION_REASONS:
                return _err(404, reason, position["message"])
            return _err(502, reason, position["message"])
        cid = position["market_id"]
        outcome = position.get("outcome") or "Yes"
        question = position.get("market_question", "")

    entities = _entities_from_question(question)
    _log(f"   ✓ {question[:48] or cid[:20]} · {outcome} · 实体={entities}")

    try:
        obj = build_market_context(cid, BRIEFING_AS_OF, entities, outcome, wallet=wallet)
    except Exception as e:
        return _err(502, "MARKET_CONTEXT_FAILED", f"{type(e).__name__}: {e}")
    # 持有侧现价（供 Context「实」面板的原生赔率条，免费 568）
    try:
        ser = board_feed.price_series(board_feed.held_token(cid, outcome), BRIEFING_AS_OF)
        if ser:
            obj["market_context"]["current_price"] = ser[-1]["price"]
    except Exception:
        pass
    return obj


def _code_follow_call(facts: dict) -> str:
    """代码版跟单判定（瘦身：替掉 reason_v3 的网关 prose，省一次调用）。
    判定本质是价格位移数学（应归代码，红线）：无证据→NO BASIS；价已大幅走过(入场后≥8%)→CHASED；否则 ROOM LEFT。
    信心改由 market_thesis 直出，这里只出 follow_call + 透传代码 facts。"""
    if not (facts.get("support_catalysts") or facts.get("threat_catalysts")):
        return "NO BASIS"
    moved = facts.get("price_already_moved")
    if moved is not None and moved >= 8:
        return "CHASED"
    return "ROOM LEFT"


def _reasoner_cached(briefing: dict, behavior: dict, wallet: str) -> dict:
    """⑥ 代码层（瘦身后不再调网关）：build_facts(代码矩阵/价格/时长) + 代码 follow_call。
    信心/倾向/理由由 dashboard 用 market_thesis 覆盖。按 钱包,as_of 缓存。"""
    REASONER_CACHE.mkdir(parents=True, exist_ok=True)
    p = REASONER_CACHE / f"{wallet.lower()}_{BRIEFING_AS_OF}.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    try:
        facts = build_facts(briefing, behavior, BRIEFING_AS_OF)
        r = {"follow_call": _code_follow_call(facts), "confidence": facts.get("confidence"),
             "reasoning": None, "confidence_reasons": facts.get("confidence_reasons"), "facts": facts}
    except Exception as e:
        r = {"follow_call": None, "confidence": None, "reasoning": None,
             "guard_tripped": "FACTS_BUILD_FAILED", "guard_message": f"{type(e).__name__}: {e}"}
    try:
        p.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return r


def _board_ai_cached(wallet, market_q, outcome, behavior, gdelt_events, tavily_cats, gamma_ctx, resolution):
    """⑤综述 + ②what_bet 独立缓存（按 钱包,as_of）：新闻流结构/前端改动时不重烧这两个网关调用。"""
    BOARD_AI_CACHE.mkdir(parents=True, exist_ok=True)
    p = BOARD_AI_CACHE / f"{wallet.lower()}_{BRIEFING_AS_OF}.json"
    if p.exists():
        try:
            c = json.loads(p.read_text(encoding="utf-8"))
            return c.get("world_summary"), c.get("what_bet")
        except Exception:
            pass
    gdelt_facts = [e.get("fact_summary") for e in gdelt_events
                   if e.get("type") == "catalyst" and e.get("fact_summary")]
    tavily_facts = [c.get("reason") for side in ("positive", "negative")
                    for c in (tavily_cats.get(side) or []) if c.get("reason")]
    world_summary = board_feed.merged_summary(market_q, outcome, behavior, gdelt_facts, tavily_facts, gamma_ctx)
    what_bet = board_feed.what_the_bet(market_q, outcome, resolution)
    try:
        p.write_text(json.dumps({"world_summary": world_summary, "what_bet": what_bet},
                                ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return world_summary, what_bet


def _market_slug(cid: str) -> str | None:
    try:
        m = (hz_results(hz_call(HZ_AGENTS["markets"][0], {"condition_id": cid})) or
             hz_results(hz_call(HZ_AGENTS["markets"][0], {"condition_id": cid, "closed": "True"})))
        return m[0].get("slug") if m else None
    except Exception:
        return None


def _relation_to_entry(cat_date: str, entry_time) -> str:
    """催化剂日期 vs 建仓日 → BEFORE/AFTER ENTRY（纯代码日期比较，不经 AI）。"""
    if not entry_time or not cat_date:
        return "UNANCHORED"
    entry_day = str(entry_time)[:10]
    return "BEFORE_ENTRY" if cat_date[:10] < entry_day else "AFTER_ENTRY"


def _tag_catalyst_relations(cats: dict, entry_time):
    for side in ("positive", "negative"):
        for c in cats.get(side, []) or []:
            c.setdefault("relation", _relation_to_entry(c.get("date"), entry_time))
    return cats


@app.get("/dashboard")
def dashboard(wallet: str):
    """v3 统一看板：①身份 ②这一注 ③实时盘面 ④行为流 ⑤世界催化剂 ⑥Edge/Reasoning。
    复用已封板模块输出（briefing + behavioral_flag + reasoner ⑥ + pnl 曲线），整份按(钱包,as_of)硬缓存。"""
    t0 = time.time()
    wallet = (wallet or "").strip()
    _log(f"\n=== /dashboard wallet={wallet[:14]}… ===")

    cache_key  = f"{wallet.lower()}_{BRIEFING_AS_OF}"
    cache_path = DASHBOARD_CACHE / f"{cache_key}.json"
    if cache_path.exists():
        try:
            _log(f"   ⚡ CACHE HIT {cache_key} — 零 token 秒回")
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    # ① 顶仓
    position = get_top_political_position_hz(wallet, as_of=BRIEFING_AS_OF)
    if position.get("error"):
        reason = position["reason"]
        if reason in _BAD_REQUEST_REASONS:
            return _err(400, reason, position["message"])
        if reason in _NO_POSITION_REASONS:
            return _err(404, reason, position["message"])
        return _err(502, reason, position["message"])
    cid, outcome = position["market_id"], position["outcome"]

    slug = _market_slug(cid)
    market_q = position["market_question"]
    try:
        # ②⑤ 完整简报（who/what/price/catalysts·Tavily）—— 已封板，命中缓存零 token
        b = load_or_build_briefing(wallet, outcome, cid=cid, as_of=BRIEFING_AS_OF, mode="live")
        if isinstance(b, dict) and b.get("error"):
            return _err(502, "BRIEFING_BUILD_FAILED", b["error"])

        # ④ 巨鲸 48h 行为流（免费 556+算术）
        behavior = get_behavior_flags(wallet, cid, BRIEFING_AS_OF)

        # ⑤ 三源合并：GDELT(market_context·缓存命中零 token) + Tavily(briefing) + gamma context
        try:
            mc = build_market_context(cid, BRIEFING_AS_OF,
                                      _entities_from_question(market_q), outcome, wallet=wallet)
            gdelt_events = (mc.get("market_context", {}) or {}).get("timeline_events", [])
        except Exception:
            gdelt_events = []                       # GDELT 挂 → 退化成 Tavily+gamma 两源
        tok = board_feed.held_token(cid, outcome)
        resolution, gamma_ctx = board_feed.gamma_meta(slug)
        tavily_cats = b.get("catalysts", {}) or {}
        news_stream = board_feed.build_news_stream(gdelt_events, tavily_cats, tok, BRIEFING_AS_OF)
        # ⑤综述 + ②what_bet：独立缓存，改新闻流结构/前端时零 token 重建
        world_summary, what_bet = _board_ai_cached(
            wallet, market_q, outcome, behavior, gdelt_events, tavily_cats, gamma_ctx, resolution)

        # 社媒情绪动量（585，免费，🔴情绪非事实、仅实时——前端与新闻视觉分开 + 刷量标显眼）
        # max_posts=12：社媒供给充足，拉满补齐新闻列长度（两列视觉平衡）
        social = social_pulse(_entities_from_question(market_q), max_posts=12)

        # ⑥ Edge/Reasoning：reason_v3 仍供 follow_call + 代码 facts（价格/时长/对冲）；
        # 🔴 信心改由「市场命题级对抗推理」直出（market_thesis，按 cid,as_of 缓存→两个反向钱包共享同一份市场观，
        #    信心一致、差异挪到 顺/逆 edge），替代旧 pnl 锚定矩阵。gateway/Tavily 挂则优雅退回旧矩阵。
        reasoning = _reasoner_cached(b, behavior, wallet)
        try:
            pc = b.get("price_context", {}) or {}
            cp = pc.get("current_price")
            cp = (cp / 100.0) if (cp and cp > 1) else cp                       # 归一到 0-1
            yes_price = cp if str(outcome).lower() == "yes" else (None if cp is None else 1 - cp)
            implied_yes = round(yes_price * 100) if yes_price is not None else 50
            thesis = build_market_thesis(market_q, cid, BRIEFING_AS_OF, implied_yes, social=social)
            algn = map_wallet(thesis, outcome)
            # ⑤ 改市场级：从 thesis 共享池重建新闻流 → 两个反向钱包看到同一批新闻（不再按方向切）
            if thesis.get("shared_pool"):
                news_stream = board_feed.build_market_news_stream(
                    gdelt_events, thesis["shared_pool"], tok, BRIEFING_AS_OF)
            reasoning = {
                **reasoning,
                "confidence": thesis["confidence"],                  # 单一信心，市场级
                "market_lean": thesis["market_lean"],
                "lean_strength": thesis["lean_strength"],
                "pivotal_unknown": thesis["pivotal_unknown"],
                "alignment": algn["alignment"],                      # 这一注 顺/逆 edge（与信心解耦）
                "reasoning": f"{thesis.get('rationale') or ''} 这一注押 {outcome}，{algn['alignment']}。".strip(),
                "thesis_audit": thesis.get("_audit"),
                "input_trust": (thesis.get("input_trust") or {}).get("lines"),   # Phase 1 可信度修正（价格深度/犹豫度/距结算）
                "event_structure": thesis.get("event_structure"),                # Phase 2 多结局结构
            }
        except Exception as e:
            _log(f"   ⚠ market_thesis 失败，⑥ 退回旧矩阵：{type(e).__name__}: {e}")

        # ① 画像 + PnL 曲线（best-effort，不阻塞）
        profile = get_wallet_profile(wallet)
        pnl_history = get_wallet_pnl_history(wallet)
    except Exception as e:
        return _err(502, "DASHBOARD_PIPELINE_FAILED", f"{type(e).__name__}: {e}")

    response = {
        "wallet": wallet,
        "as_of": BRIEFING_AS_OF,
        "identity": {                                # ①
            "profile": profile,
            "pnl_history": pnl_history,
            "who_trader_profile": b.get("who_trader_profile", {}),
        },
        "position": {                                # ②
            "meta": b.get("meta", {}),
            "what_position_actions": b.get("what_position_actions", {}),
            "price_context": b.get("price_context", {}),
            "what_the_bet": what_bet,                # ②补回：这一注在赌什么
            "resolution_criteria": resolution,       # 官方结算规则原文
        },
        "market": {"slug": slug, "market_id": cid},  # ③
        "price_series": board_feed.price_series(tok, BRIEFING_AS_OF),  # 上帝视角时间轴(568日线,免费)
        "behavior": behavior,                        # ④
        "news_stream": news_stream,                  # ⑤ 三源合并时间线（source 链接 + 反应符号）
        "social": social,                            # ⑤ 社媒情绪动量（585·情绪非事实·仅实时）
        "world_summary": world_summary,              # ⑤ 三源合并综述（巨鲸动态/事态进展）
        "reasoning": reasoning,                      # ⑥
    }
    _log(f"   ✓ 看板生成完毕（耗时 {time.time() - t0:.1f}s）")

    try:
        DASHBOARD_CACHE.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")
        _log(f"   💾 已缓存 {cache_key}（同钱包零 token 秒回）")
    except Exception:
        pass
    # 📒 诚实记分牌钩子（best-effort）：⑥ board 判断存档（守卫拦截无 follow_call 时不记）
    if reasoning.get("follow_call"):
        scorecard.record_judgment(
            wallet=wallet, cid=cid, market_question=market_q, outcome=outcome,
            market_price=(b.get("price_context", {}) or {}).get("current_price"),
            follow_call=reasoning["follow_call"], confidence=reasoning["confidence"],
            source="board", settle_date=(b.get("meta", {}) or {}).get("settle"))
    return response


RECOMMEND_FILE = Path(".data/recommendations.json")


@app.get("/recommendations")
def recommendations():
    """扫榜推荐：读 recommend.py 定期写的候选清单（免费扫榜层）。空=还没扫过。"""
    if RECOMMEND_FILE.exists():
        try:
            return json.loads(RECOMMEND_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"as_of": BRIEFING_AS_OF, "candidates": []}


HOT_TRADERS_FILE = Path(".data/hot_traders.json")


@app.get("/hot-traders")
def hot_traders():
    """入口页滚动条：本周政治盘热门交易者（hot_traders.py 定期写）。空=还没扫过。"""
    if HOT_TRADERS_FILE.exists():
        try:
            return json.loads(HOT_TRADERS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"as_of": BRIEFING_AS_OF, "period": "7d", "traders": []}


@app.get("/scorecard")
def scorecard_endpoint():
    """诚实记分牌：增量抓结算(574,免费) → 纯代码冷数字 + 行表（不调 AI、不算收益率）。"""
    def _resolve_574(cid):
        m = (hz_results(hz_call(HZ_AGENTS["markets"][0], {"condition_id": cid})) or
             hz_results(hz_call(HZ_AGENTS["markets"][0], {"condition_id": cid, "closed": "True"})))
        if not m:
            return None
        w = str(m[0].get("winning_outcome") or "").strip()
        return w if w in ("Yes", "No") else None
    try:
        filled = scorecard.fetch_settlements(_resolve_574)
        if filled:
            _log(f"   📒 记分牌新结算 {filled} 条")
    except Exception as e:
        _log(f"   ⚠ 记分牌抓结算失败: {e}")
    return scorecard.compute_scorecard()


@app.get("/briefing")
def briefing(wallet: str):
    """完整聪明钱简报：钱包→顶仓→A段编排(结构化)+B段第三个AI(人话)→整份硬缓存。"""
    t0 = time.time()
    wallet = (wallet or "").strip()
    _log(f"\n=== /briefing wallet={wallet[:14]}… ===")

    # ── 第 0 层：(钱包,数据世界日期) 整份缓存（命门：cache miss~5k token、hit=零 token 秒回）──
    cache_key  = f"{wallet.lower()}_{BRIEFING_AS_OF}"
    cache_path = BRIEFING_CACHE / f"{cache_key}.json"
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            _log(f"   ⚡ CACHE HIT {cache_key} — 零 token 秒回")
            return cached
        except Exception:
            pass

    # ── 第 1 层：最大政治仓（走 Heisenberg，不依赖会挂的真实 Polymarket data-api）──
    _log("① 拉取最大政治仓位（Heisenberg）")
    position = get_top_political_position_hz(wallet, as_of=BRIEFING_AS_OF)
    if position.get("error"):
        reason = position["reason"]
        if reason in _BAD_REQUEST_REASONS:
            return _err(400, reason, position["message"])
        if reason in _NO_POSITION_REASONS:
            return _err(404, reason, position["message"])
        return _err(502, reason, position["message"])
    _log(f"   ✓ {position['market_question'][:48]} · {position['outcome']}")

    # ── 第 2 层：A 段编排（结构化简报，烧 dual_catalyst）+ B 段第三个 AI（人话）──────
    try:
        _log("② A段编排器（WHO/WHAT/PRICE + 双向催化剂 + 测谎仪）")
        b = load_or_build_briefing(wallet, position["outcome"],
                                   cid=position["market_id"], as_of=BRIEFING_AS_OF, mode="live")
        if isinstance(b, dict) and b.get("error"):
            return _err(502, "BRIEFING_BUILD_FAILED", b["error"])
        _log("③ B段第三个 AI 诚实整理")
        organized = organize_briefing(b)
    except Exception as e:                    # Heisenberg/网关等上游失败一律 502
        return _err(502, "BRIEFING_PIPELINE_FAILED", f"{type(e).__name__}: {e}")

    response = {**b, "organized_text": organized["text"], "organize_guards": organized["guards"]}
    _log(f"   ✓ 简报生成完毕（耗时 {time.time() - t0:.1f}s）")

    try:
        BRIEFING_CACHE.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")
        _log(f"   💾 已缓存 {cache_key}（同钱包零 token 秒回）")
    except Exception:
        pass
    return response
