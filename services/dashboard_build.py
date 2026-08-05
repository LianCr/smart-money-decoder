"""
services/dashboard_build.py — 统一看板构建的 service 层（P0-3：从 api/main.py 抽出）。

🔴 纯数据错误契约（AUDIT P0-3 的先决条件，8 个出口全部收口在这）：
  本模块只返回 dict，永不返回 JSONResponse、预期失败永不 raise。
  判别式 = "error" key 有无：
    成功/缓存命中/旧板回退 → 看板 dict（回退板带 refresh_error；抢锁失败的旧板带 refresh_in_progress）
    失败                   → {"error": <reason>, "message": <中文人读>}（单飞占用另带 retry_after）
  HTTP 状态码由 api 层从 reason 推导（api/main.py 的 _dashboard_status）——HTTP 知识不进本模块。

🔴 本模块绝不 import api.main —— 分层纪律：service 不许知道 HTTP 装配层的存在（防环）。
  这也是能被测试/recommend 直接 import 的前提。（T2.3 起 import api.main 已零副作用，纪律照旧。）

进程内共用：api 路由和 recommend.ai_verify 都走 get_dashboard() → 共享同一把单飞锁
（模块级 _FLIGHT，coordinator 是 core/redis_coord 的进程单例）——"同钱包不重复烧 AI"
跨调用方成立，扫榜不再 HTTP 打自己（P0-3 的病根）。
"""

import json
import time
from datetime import date
from pathlib import Path

from core.log import get_logger
from core.config import BRIEFING_AS_OF
from core.cachefiles import newest_dated
from core.jsonstore import atomic_write_json
from core.redis_coord import coordinator
from core.dashboard_jobs import DashboardSingleFlight, stale_while_building, resolve_contention
from core.translate import attach_i18n_en
from fetcher.positions import get_top_political_position_hz
from fetcher.trades import get_wallet_profile, get_wallet_pnl_history
from fetcher.heisenberg import call as hz_call, results as hz_results, AGENTS as HZ_AGENTS
from fetcher.social import social_pulse
from briefing.assemble import load_or_build_briefing
from briefing.market_context import load_or_build as build_market_context
from briefing.market_context import get_behavior_flags
from briefing import board_feed
from analyzer.reasoner_v3 import build_facts
from analyzer.market_thesis import build_market_thesis, map_wallet
import scorecard

# ── 失败 reason 分类（api 层据此映射 400/404/502；本模块据此决定要不要走旧板回退）──
NO_POSITION_REASONS = {"NO_POSITIONS", "NO_POLITICAL_POSITIONS", "ALL_BELOW_MIN_VALUE", "NO_OPEN_POSITIONS"}
BAD_REQUEST_REASONS = {"INVALID_ADDRESS"}
# 其余 fetcher 层 reason（API_TIMEOUT / RATE_LIMITED / API_ERROR / …）一律视为上游失败
BUILD_IN_PROGRESS = "DASHBOARD_BUILD_IN_PROGRESS"

LOG = get_logger("dashboard")

BRIEFING_CACHE  = Path(".cache/briefing_api")   # 完整简报响应缓存（/briefing 与刷新清缓存共用）
DASHBOARD_CACHE = Path(".cache/dashboard")      # 统一看板整份响应缓存（①-⑥），命中=零 token 秒回
REASONER_CACHE  = Path(".cache/reasoner_v3")     # ⑥ reasoner 独立缓存：改 ⑤/② 重建看板不重烧 ⑥
BOARD_AI_CACHE  = Path(".cache/board_ai")        # ⑤综述+②what_bet 独立缓存：改新闻流结构/前端不重烧 AI

# 🛡 P1-10 缓存失效注册表：四层「钱包×日期」缓存在此自注册（resolver 运行时读模块常量，
# 测试 monkeypatch 目录常量后依然生效）。新增缓存不注册会被 tests/test_cachepolicy.py 抓红。
from core import cachepolicy

cachepolicy.register("dashboard",    lambda ctx: DASHBOARD_CACHE / f"{ctx['wallet'].lower()}_{ctx['as_of']}.json")
cachepolicy.register("briefing_api", lambda ctx: BRIEFING_CACHE / f"{ctx['wallet'].lower()}_{ctx['as_of']}.json")
cachepolicy.register("reasoner_v3",  lambda ctx: REASONER_CACHE / f"{ctx['wallet'].lower()}_{ctx['as_of']}.json")
cachepolicy.register("board_ai",     lambda ctx: BOARD_AI_CACHE / f"{ctx['wallet'].lower()}_{ctx['as_of']}.json")


def _log(msg: str) -> None:
    """pipeline 进度日志（P1-12：走 core/log，消息原文不变，rid 由请求上下文注入）。"""
    LOG.info(msg)


def _fail(reason: str, message: str) -> dict:
    """统一错误出口（纯数据）：{"error": reason, "message": ...}，不带 HTTP 状态。"""
    LOG.warning(f"   ✗ {reason} — {message}")
    return {"error": reason, "message": message}


# 从市场问题里抠出主体实体（喂给 GDELT 硬过滤）。专有名词小写、去停用词。
_Q_STOP = {"will", "the", "a", "an", "be", "is", "are", "by", "out", "as", "of", "in",
           "on", "to", "for", "and", "or", "next", "win", "wins", "won", "leader",
           "president", "presidential", "election", "democratic", "republican", "world",
           "cup", "fifa", "june", "july", "august", "may", "april", "march", "who", "what",
           "prime", "minister", "united", "kingdom", "states", "government", "party",
           "leadership", "national", "general", "american", "british", "before", "after"}


def entities_from_question(q: str) -> list[str]:
    import re
    toks = re.findall(r"[A-Za-z]{3,}(?:-[A-Za-z]{3,})*", q or "")   # 连字名保留整体（Jae-myung 不拆；US-Iran 仍取 Iran，US 2 字母跳过）
    ents, seen = [], set()
    for t in toks:
        low = t.lower()
        if t[0].isupper() and low not in _Q_STOP and low not in seen:
            ents.append(low)
            seen.add(low)
    return ents[:5] or ["politics"]


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


def _reasoner_cached(briefing: dict, behavior: dict, wallet: str, as_of: str = BRIEFING_AS_OF) -> dict:
    """⑥ 代码层（瘦身后不再调网关）：build_facts(代码矩阵/价格/时长) + 代码 follow_call。
    信心/倾向/理由由 dashboard 用 market_thesis 覆盖。按 钱包,as_of 缓存。"""
    REASONER_CACHE.mkdir(parents=True, exist_ok=True)
    p = REASONER_CACHE / f"{wallet.lower()}_{as_of}.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    try:
        facts = build_facts(briefing, behavior, as_of)
        r = {"follow_call": _code_follow_call(facts), "confidence": facts.get("confidence"),
             "reasoning": None, "confidence_reasons": facts.get("confidence_reasons"), "facts": facts}
    except Exception as e:
        r = {"follow_call": None, "confidence": None, "reasoning": None,
             "guard_tripped": "FACTS_BUILD_FAILED", "guard_message": f"{type(e).__name__}: {e}"}
    try:
        atomic_write_json(p, r)
    except Exception:
        pass
    return r


def _board_ai_cached(wallet, market_q, outcome, behavior, gdelt_events, tavily_cats, gamma_ctx, resolution,
                     as_of: str = BRIEFING_AS_OF):
    """⑤综述 + ②what_bet 独立缓存（按 钱包,as_of）：新闻流结构/前端改动时不重烧这两个网关调用。"""
    BOARD_AI_CACHE.mkdir(parents=True, exist_ok=True)
    p = BOARD_AI_CACHE / f"{wallet.lower()}_{as_of}.json"
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
        atomic_write_json(p, {"world_summary": world_summary, "what_bet": what_bet})
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


def _purge_wallet_caches(wallet: str, cid: str, outcome: str, as_of: str = BRIEFING_AS_OF) -> int:
    """强制刷新：删掉该 (钱包,as_of) 及其所在盘的各层缓存文件 → 后续正常流程全部重建并重新落盘。
    只删文件、不动缓存 key 格式；market_thesis 按 (cid,as_of) 共享，删了会连带其他共持钱包下次重烧（语义正确：刷新=要最新）。
    🔴 只删传入 as_of（=今天）这一天的 key —— 旧日期快照不碰，重建失败时它天然是回退底。
    P1-10 起走 core/cachepolicy 注册表（各缓存拥有者自注册；本模块 import 了全部拥有者
    → purge 时注册必然完成），不再手写清单、不再跨模块 import 私有 _cache_path。"""
    return cachepolicy.purge(wallet, cid, outcome, as_of)


def _stale_dashboard_fallback(wallet: str, reason: str, message: str) -> dict:
    """刷新/保鲜重建失败 → 回退该钱包最新的旧快照 + 带 refresh_error（stale-while-revalidate，
    与 /recommendations 的空榜保护同一哲学：绝不让一次失败的刷新毁掉能用的旧板）。没有旧板才报错。"""
    newest = newest_dated(DASHBOARD_CACHE, wallet.lower())
    if newest:
        try:
            stale = json.loads(newest[0].read_text(encoding="utf-8"))
            stale["refresh_error"] = f"{reason}: {message}"
            _log(f"   ⚠ 重建失败，回退旧快照 as_of={newest[1]}（refresh_error 已标注）")
            return stale
        except Exception:
            pass
    return _fail(reason, message)


def build_dashboard(wallet: str, refresh: int = 0, fresh: int = 0) -> dict:
    """v3 统一看板：①身份 ②这一注 ③实时盘面 ④行为流 ⑤世界催化剂 ⑥Edge/Reasoning。
    复用已封板模块输出（briefing + behavioral_flag + reasoner ⑥ + pnl 曲线），整份按(钱包,as_of)硬缓存。
    refresh=1：强制在**今天**重建（烧 token、用户确认过）——实时刷新的正门。
    fresh=1（扫榜 ai_verify 用）：要"今天"的数据，但今天已有缓存就直接用（不重复烧）。
    默认（都不传）：读该钱包最新日期的缓存快照，零 token 秒回；一份都没有才在钉死的
    BRIEFING_AS_OF 上重建（demo 快照经济学不变）。旧日期快照永不被刷新删除 → 失败可回退。"""
    t0 = time.time()
    wallet = (wallet or "").strip()
    today = date.today().isoformat()
    as_of = today if (refresh or fresh) else BRIEFING_AS_OF
    _log(f"\n=== /dashboard wallet={wallet[:14]}…{' [REFRESH]' if refresh else ''}"
         f"{' [FRESH]' if fresh and not refresh else ''} as_of={as_of} ===")

    if not refresh:
        newest = newest_dated(DASHBOARD_CACHE, wallet.lower())
        if newest and (not fresh or newest[1] >= today):
            try:
                _log(f"   ⚡ CACHE HIT {newest[0].stem} — 零 token 秒回")
                cached = json.loads(newest[0].read_text(encoding="utf-8"))
                # 翻译懒自愈：7-08 起的新快照若缺 i18n_en（挂钩上线前建的）补一次翻译并回写。
                # 6-25 老快照跳过——它们的内容在离线词典 ai_en.js 里，本来就翻得出。
                if "i18n_en" not in cached and cached.get("as_of", "") >= "2026-07-08":
                    if attach_i18n_en(cached):
                        _log("   🌐 i18n_en 懒自愈：补翻译并回写缓存")
                        try:
                            atomic_write_json(newest[0], cached)
                        except Exception:
                            pass
                return cached
            except Exception:
                pass

    cache_key  = f"{wallet.lower()}_{as_of}"
    cache_path = DASHBOARD_CACHE / f"{cache_key}.json"

    # ① 顶仓
    position = get_top_political_position_hz(wallet, as_of=as_of)
    if position.get("error"):
        reason = position["reason"]
        if reason in BAD_REQUEST_REASONS or reason in NO_POSITION_REASONS:
            return _fail(reason, position["message"])   # 调用方/数据事实问题：旧板回退救不了
        if refresh or fresh:
            return _stale_dashboard_fallback(wallet, reason, position["message"])
        return _fail(reason, position["message"])
    cid, outcome = position["market_id"], position["outcome"]

    if refresh:
        n = _purge_wallet_caches(wallet, cid, outcome, as_of)
        _log(f"   ♻ 强制刷新：清掉今日 {n} 个缓存文件，在 as_of={as_of} 全链路重建（旧快照保留可回退）")

    slug = _market_slug(cid)
    market_q = position["market_question"]
    try:
        # ②⑤ 完整简报（who/what/price/catalysts·Tavily）—— 已封板，命中缓存零 token
        b = load_or_build_briefing(wallet, outcome, cid=cid, as_of=as_of, mode="live")
        if isinstance(b, dict) and b.get("error"):
            if refresh or fresh:
                return _stale_dashboard_fallback(wallet, "BRIEFING_BUILD_FAILED", b["error"])
            return _fail("BRIEFING_BUILD_FAILED", b["error"])

        # ④ 巨鲸 48h 行为流（免费 556+算术）
        behavior = get_behavior_flags(wallet, cid, as_of)

        # ⑤ 三源合并：GDELT(market_context·缓存命中零 token) + Tavily(briefing) + gamma context
        try:
            mc = build_market_context(cid, as_of,
                                      entities_from_question(market_q), outcome, wallet=wallet)
            gdelt_events = (mc.get("market_context", {}) or {}).get("timeline_events", [])
        except Exception:
            gdelt_events = []                       # GDELT 挂 → 退化成 Tavily+gamma 两源
        tok = board_feed.held_token(cid, outcome)
        resolution, gamma_ctx = board_feed.gamma_meta(slug)
        tavily_cats = b.get("catalysts", {}) or {}
        news_stream = board_feed.build_news_stream(gdelt_events, tavily_cats, tok, as_of)
        # ⑤综述 + ②what_bet：独立缓存，改新闻流结构/前端时零 token 重建
        world_summary, what_bet = _board_ai_cached(
            wallet, market_q, outcome, behavior, gdelt_events, tavily_cats, gamma_ctx, resolution,
            as_of=as_of)

        # 社媒情绪动量（585，免费，🔴情绪非事实、仅实时——前端与新闻视觉分开 + 刷量标显眼）
        # max_posts=12：社媒供给充足，拉满补齐新闻列长度（两列视觉平衡）
        social = social_pulse(entities_from_question(market_q), max_posts=12)

        # ⑥ Edge/Reasoning：reason_v3 仍供 follow_call + 代码 facts（价格/时长/对冲）；
        # 🔴 信心改由「市场命题级对抗推理」直出（market_thesis，按 cid,as_of 缓存→两个反向钱包共享同一份市场观，
        #    信心一致、差异挪到 顺/逆 edge），替代旧 pnl 锚定矩阵。gateway/Tavily 挂则优雅退回旧矩阵。
        reasoning = _reasoner_cached(b, behavior, wallet, as_of=as_of)
        try:
            pc = b.get("price_context", {}) or {}
            cp = pc.get("current_price")
            cp = (cp / 100.0) if (cp and cp > 1) else cp                       # 归一到 0-1
            yes_price = cp if str(outcome).lower() == "yes" else (None if cp is None else 1 - cp)
            implied_yes = round(yes_price * 100) if yes_price is not None else 50
            thesis = build_market_thesis(market_q, cid, as_of, implied_yes, social=social)
            algn = map_wallet(thesis, outcome)
            # ⑤ 改市场级：从 thesis 共享池重建新闻流 → 两个反向钱包看到同一批新闻（不再按方向切）
            if thesis.get("shared_pool"):
                news_stream = board_feed.build_market_news_stream(
                    gdelt_events, thesis["shared_pool"], tok, as_of)
            reasoning = {
                **reasoning,
                "confidence": thesis["confidence"],                  # 单一信心，市场级
                "confidence_source": "market_thesis",                # 降级可见：信心是哪套系统算的
                "deterministic": False,                              # P1-7：LLM 直出裁决，非确定性（诚实标注）
                "guard_flags": thesis.get("guard_flags", []),        # 🛡 T2.1 守卫留痕（旧缓存 thesis 无此 key→[]）
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
            # 降级不许静默（产品灵魂=诚实）：payload 里标明信心来自旧 pnl 锚定矩阵
            # （v2 矩阵是纯代码 → deterministic 如实标 True）
            reasoning = {**reasoning, "confidence_source": "fallback_v2_matrix", "deterministic": True}

        # ① 画像 + PnL 曲线（best-effort，不阻塞）
        profile = get_wallet_profile(wallet)
        pnl_history = get_wallet_pnl_history(wallet)
    except Exception as e:
        if refresh or fresh:
            return _stale_dashboard_fallback(wallet, "DASHBOARD_PIPELINE_FAILED", f"{type(e).__name__}: {e}")
        return _fail("DASHBOARD_PIPELINE_FAILED", f"{type(e).__name__}: {e}")

    response = {
        "wallet": wallet,
        "as_of": as_of,
        "identity": {                                # ①
            "profile": profile,
            "pnl_history": pnl_history,
            "who_trader_profile": b.get("who_trader_profile", {}),
        },
        "position": {                                # ②
            "near_settled": position.get("near_settled"),   # 入口守卫打的标：整本仓位均无悬念
            "held_price": position.get("held_price"),
            "meta": b.get("meta", {}),
            "what_position_actions": b.get("what_position_actions", {}),
            "price_context": b.get("price_context", {}),
            "what_the_bet": what_bet,                # ②补回：这一注在赌什么
            "resolution_criteria": resolution,       # 官方结算规则原文
        },
        "market": {"slug": slug, "market_id": cid},  # ③
        "price_series": board_feed.price_series(tok, as_of),  # 上帝视角时间轴(568日线,免费)
        "behavior": behavior,                        # ④
        "news_stream": news_stream,                  # ⑤ 三源合并时间线（source 链接 + 反应符号）
        "social": social,                            # ⑤ 社媒情绪动量（585·情绪非事实·仅实时）
        "world_summary": world_summary,              # ⑤ 三源合并综述（巨鲸动态/事态进展）
        "reasoning": reasoning,                      # ⑥
    }
    # 🌐 EN 运行时词典：把 payload 里全部中文显示串翻成英文挂 i18n_en（随缓存持久化，
    # 失败不阻塞——前端回退中文+ZhNote 即旧行为）
    if attach_i18n_en(response):
        _log(f"   🌐 i18n_en 已挂（{len(response['i18n_en'])} 条）")
    _log(f"   ✓ 看板生成完毕（耗时 {time.time() - t0:.1f}s）")

    try:
        DASHBOARD_CACHE.mkdir(parents=True, exist_ok=True)
        atomic_write_json(cache_path, response)
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


_FLIGHT = DashboardSingleFlight(coordinator)


def get_dashboard(wallet: str, refresh: int = 0, fresh: int = 0) -> dict:
    """看板的单飞入口（api 路由和 recommend.ai_verify 共用同一把锁）。

    抢到锁 → 真跑 build_dashboard；抢不到（同钱包正在构建）：
      普通访客 → 最新旧板 + refresh_in_progress（stale-while-revalidate）；
      refresh=1 或没有旧板 → {"error": BUILD_IN_PROGRESS, retry_after: 3}（api 层映射 202，前端轮询）。
    """
    wallet = (wallet or "").strip()
    as_of = date.today().isoformat() if (refresh or fresh) else BRIEFING_AS_OF
    lease = _FLIGHT.enter(wallet, as_of)
    if not lease.acquired:
        served = resolve_contention(stale_while_building(DASHBOARD_CACHE, wallet), refresh)
        if served is not None:
            return served
        return {"error": BUILD_IN_PROGRESS,
                "message": "同一钱包的看板正在生成，请稍候。",
                "retry_after": 3}
    try:
        return build_dashboard(wallet, refresh=refresh, fresh=fresh)
    finally:
        lease.release()
