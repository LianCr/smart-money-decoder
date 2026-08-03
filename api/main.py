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
import shutil
import sys
import time
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

# ── 种子缓存（部署用）：云端磁盘 ephemeral，每次冷启动从 git 跟踪的 seed/ 恢复 ──
# 本地 .cache/.data 已存在 → 不覆盖；只有全新环境（如 Render 冷启动）才复制。
for _src, _dst in [(Path("seed/cache"), Path(".cache")), (Path("seed/data"), Path(".data"))]:
    if _src.exists() and not _dst.exists():
        try:
            shutil.copytree(_src, _dst)
            print(f"🌱 种子缓存恢复：{_src} → {_dst}", flush=True)
        except Exception as e:
            print(f"⚠ 种子缓存恢复失败：{e}", flush=True)

# ── GitHub 状态恢复（跨部署持久）：seed 之后再叠加远端 bundle，谁新用谁 ──────
# Render 免费档磁盘 ephemeral：重部署/冷启动清盘只剩 seed(6-25 快照)。刷新过的
# 推荐榜/看板缓存/记分牌存在 app-state 分支，这里拉回来 → 用户重进网站看到的
# 永远是"上一次刷新"的结果（公开仓库 raw 拉取，恢复端无需 token）。
try:
    from core.persist import fetch_bundle, restore_bundle
    _bundle = fetch_bundle()
    if _bundle:
        _n = restore_bundle(_bundle)
        print(f"☁️ GitHub 状态恢复：{_n} 个文件（app-state 分支）", flush=True)
except Exception as _e:
    print(f"⚠ GitHub 状态恢复失败（不阻塞）：{_e}", flush=True)

from core.config import (BRIEFING_AS_OF, RATE_LIMIT_DAILY_GLOBAL, RATE_LIMIT_PER_IP,
                         RATE_LIMIT_WINDOW_SECONDS)
from core.cachefiles import newest_dated
from core.ratelimit import RateLimiter
from core.health import health_report
from core.jsonstore import CORRUPT, OK, atomic_write_json, atomic_write_text, load_json
from core.redis_coord import coordinator
from core.refresh_jobs import RecommendationRefresh
from core.translate import attach_i18n_en
from fetcher.polymarket import get_top_political_position
from fetcher.activity import get_entry_time, ActivityAPIError
from fetcher.trades import get_entry_time_v2, get_wallet_profile, get_wallet_pnl_history
from fetcher.news import get_news_for_market
from analyzer.decoder import decode_position, DecoderError
from briefing.assemble import load_or_build_briefing
from briefing.organize import organize_briefing
from fetcher.positions import get_top_political_position_hz
from briefing.market_context import load_or_build as build_market_context
from fetcher.heisenberg import call as hz_call, results as hz_results, AGENTS as HZ_AGENTS
from briefing import board_feed
# 看板构建已抽 service 层（P0-3）：单飞锁与 8 个错误出口都在 services/dashboard_build，
# 这里只留 HTTP 映射（_dashboard_status）。recommend.ai_verify 走同一个 get_dashboard。
from services.dashboard_build import (
    BAD_REQUEST_REASONS, BRIEFING_CACHE, BUILD_IN_PROGRESS, DASHBOARD_CACHE,
    NO_POSITION_REASONS, entities_from_question, get_dashboard,
)
import scorecard

from contextlib import asynccontextmanager


@asynccontextmanager
async def _lifespan(_app):
    """启动时把 anyio 工作线程池的隐式上限（40）显式化（AUDIT T1.4 顺带项）。
    全部端点都是同步 def、共享这个池；看板构建一条独占 worker 1-3 分钟——
    上限显式写死后可观测、可调，不再是"藏在 anyio 默认值里的事实"。数值不变=行为不变。"""
    from anyio import to_thread
    to_thread.current_default_thread_limiter().total_tokens = 40
    yield


app = FastAPI(title="smart-money-decoder API", version="1.0", lifespan=_lifespan)

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

# ── reason → HTTP 状态码映射：reason 分类集合的正本在 services/dashboard_build ──
# 其余 fetcher 层 reason（API_TIMEOUT / RATE_LIMITED / API_ERROR / KEYWORD_EXTRACT_FAILED /
# TAVILY_*）一律视为上游失败 → 502


def _log(msg: str) -> None:
    """pipeline 进度打到 stdout（uvicorn 控制台可见）。"""
    print(msg, file=sys.stdout, flush=True)


def _err(status: int, reason: str, message: str) -> JSONResponse:
    """统一错误出口，body 形如 {"error": reason, "message": ...}。"""
    _log(f"   ✗ [{status}] {reason} — {message}")
    return JSONResponse(status_code=status, content={"error": reason, "message": message})


# ── 入站限流（P1-15）：只闸真烧 token 的 /dashboard /analyze；阈值在 core/config.py。
# 🔴 闸防"额度被刷空"，不是关门——「完全开放」的产品决策不变。进程内 ai_verify 不经
# 路由、天然不受闸（扫榜是用户主动批准的批量烧）。
_RATE_LIMITER = RateLimiter(RATE_LIMIT_PER_IP, RATE_LIMIT_WINDOW_SECONDS, RATE_LIMIT_DAILY_GLOBAL)


def _client_ip(request: Request) -> str:
    """Render 代理层设 X-Forwarded-For（首项=真实客户端）；本地直连退回 socket 对端。
    直连时该头可伪造——所以每日全局硬闸不认 IP，是刷不开的兜底。"""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _rate_limited(request: Request) -> JSONResponse | None:
    """过闸：放行返回 None；超限返回 429（人话 message + retry_after 已在闸里备好）。"""
    denied = _RATE_LIMITER.check(_client_ip(request))
    if denied is None:
        return None
    _log(f"   ✗ [429] {denied['error']} ip={_client_ip(request)[:24]}")
    return JSONResponse(status_code=429, content=denied)


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
# BRIEFING_CACHE / DASHBOARD_CACHE 等看板系缓存路径的正本在 services/dashboard_build（顶部已导入）。
# 🔴 BRIEFING_AS_OF 已收口到 core/config.py（单一出口，改那边）。


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


@app.get("/healthz")
def healthz():
    """真探活：必填 key 齐不齐 + 缓存目录写不写得动。判定口径见 core/health.py。

    不健康返回 **503**，让部署/负载均衡当场知道 —— 这正是 P0-2 那次事故缺的东西：
    实例起来了、首页能开、一点陌生钱包就 502，而没有任何地方会告诉你。
    本端点只做转发，逻辑全在 core/health（纯函数、可单测，不受本模块 import 副作用拖累）。"""
    r = health_report()
    return JSONResponse(status_code=200 if r["ok"] else 503, content=r)


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
def analyze(wallet: str, request: Request):
    """跑完整 pipeline，返回解读卡片 JSON 或分层错误。"""
    denied = _rate_limited(request)
    if denied is not None:
        return denied
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
        if reason in BAD_REQUEST_REASONS:
            return _err(400, reason, position["message"])
        if reason in NO_POSITION_REASONS:
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
        atomic_write_json(cache_path, response)
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
            if reason in BAD_REQUEST_REASONS:
                return _err(400, reason, position["message"])
            if reason in NO_POSITION_REASONS:
                return _err(404, reason, position["message"])
            return _err(502, reason, position["message"])
        cid = position["market_id"]
        outcome = position.get("outcome") or "Yes"
        question = position.get("market_question", "")

    entities = entities_from_question(question)
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


def _dashboard_status(reason: str) -> int:
    """service 纯数据错误 → HTTP 状态码（唯一的 HTTP 映射知识，留在 api 层）。"""
    if reason in BAD_REQUEST_REASONS:
        return 400
    if reason in NO_POSITION_REASONS:
        return 404
    if reason == BUILD_IN_PROGRESS:
        return 202                        # 同钱包正在构建，前端轮询
    return 502                            # 其余一律上游失败


@app.get("/dashboard")
def dashboard(wallet: str, request: Request, refresh: int = 0, fresh: int = 0):
    """v3 统一看板：构建/单飞/缓存/旧板回退全在 services/dashboard_build.get_dashboard
    （纯数据契约，recommend.ai_verify 进程内走同一入口）；这里只把错误 dict 映射成 HTTP 状态码。
    refresh=1=强制今天重建（烧 token）；fresh=1=要今天的数据但已有今天缓存不重烧。"""
    denied = _rate_limited(request)
    if denied is not None:
        return denied
    out = get_dashboard(wallet, refresh=refresh, fresh=fresh)
    if isinstance(out, dict) and out.get("error"):
        return JSONResponse(status_code=_dashboard_status(out["error"]), content=out)
    return out


RECOMMEND_FILE = Path(".data/recommendations.json")

# 推荐榜后台刷新状态：Redis 跨实例单飞；未配置/故障时自动退回进程内协调。
_REC_REFRESH = RecommendationRefresh(coordinator)


def _persist_app_state():
    """扫榜成功后把状态存回 GitHub app-state 分支（跨部署持久）：推荐榜 + 热门条 +
    记分牌档案 + 每个 AI 精选钱包的最新看板缓存（点进去秒开且与卡片一致）。
    未配 GITHUB_TOKEN 自动跳过（core/persist 打一行提示）。"""
    try:
        from core.persist import build_bundle, save_bundle
        data_files = {
            ".data/recommendations.json": RECOMMEND_FILE,
            ".data/hot_traders.json": HOT_TRADERS_FILE,
            ".data/scorecard.json": scorecard.ARCHIVE,
        }
        cache_files = {}
        try:
            recs = json.loads(RECOMMEND_FILE.read_text(encoding="utf-8"))
            for c in recs.get("candidates", []):
                if not c.get("ai_pick"):
                    continue
                newest = newest_dated(DASHBOARD_CACHE, str(c.get("wallet", "")).lower())
                if newest:
                    cache_files[f".cache/dashboard/{newest[0].name}"] = newest[0]
        except Exception:
            pass
        save_bundle(build_bundle(data_files, cache_files))
    except Exception as e:
        _log(f"   ⚠ 状态持久化失败（不阻塞）：{type(e).__name__}: {e}")


def _run_rec_scan():
    """后台线程：真跑 recommend.scan（几分钟、ai_top>0 烧 token——用户已批准）。
    🛡 空榜保护：上游失败返回空候选时恢复旧榜，绝不用空覆盖好数据。"""
    backup = None
    try:
        if RECOMMEND_FILE.exists():
            backup = RECOMMEND_FILE.read_text(encoding="utf-8")
        import recommend
        # 🔴 用户点刷新=要最新 → 扫榜锚今天（免费数据层）；ai_verify 用 fresh=1 保证 ⑥ 也在今天（烧 token 已确认）
        cands = recommend.scan(ai_top=int(os.environ.get("AI_TOP", "5")),
                               as_of=date.today().isoformat())
        if not cands and backup and json.loads(backup).get("candidates"):
            atomic_write_text(RECOMMEND_FILE, backup)
            raise RuntimeError("扫榜返回空（上游数据源失败？）——已保留旧榜")
        else:
            _persist_app_state()          # ☁️ 刷新成功 → 存回 GitHub，跨部署/冷启动持久
    except Exception:
        if backup:
            try:
                atomic_write_text(RECOMMEND_FILE, backup)
            except Exception:
                pass
        raise


@app.get("/recommendations")
def recommendations(refresh: int = 0):
    """扫榜推荐：读 recommend.py 写的候选清单。refresh=1 → 后台重扫（几分钟+烧 token），
    期间照常返回旧榜（stale-while-revalidate），前端轮询 refreshing 直到出新榜。"""
    if refresh:
        if _REC_REFRESH.start(_run_rec_scan):
            _log("\n=== /recommendations REFRESH：后台扫榜启动 ===")
    out = {"as_of": BRIEFING_AS_OF, "candidates": []}
    # 🔴 用 load_json 而不是裸 json.loads：榜文件损坏时原件被隔离成 .corrupt-* 备份
    # （证据留着，可人工抢救），而不是被后续写入无声盖掉。用户仍看到空榜（与旧行为一致），
    # 但日志里会明说"损坏已隔离"，不再是一个查不出原因的空白首页。
    status, data = load_json(RECOMMEND_FILE, default=None)
    if status == OK and isinstance(data, dict):
        out = data
    elif status == CORRUPT:
        _log("   ⚠ 推荐榜文件损坏，已隔离为 .corrupt-* 备份；本次返回空榜（下次扫榜会重建）")
    # 🔴 serve-time 对齐：卡片 ⑥ 以该钱包最新看板缓存为准（单一真相源，纯文件读零 token）——
    # 否则扫榜后的重建/翻天/守卫换盘会造成"卡上一套、点进去另一套"
    try:
        import recommend as _rec
        extra = _rec.sync_candidates_with_boards(out.get("candidates"), DASHBOARD_CACHE)
        if extra:
            out.setdefault("i18n_en", {}).update(extra)
    except Exception as e:
        _log(f"   ⚠ 推荐卡对齐失败（不阻塞）：{type(e).__name__}: {e}")
    refresh_state = _REC_REFRESH.status()
    out["refreshing"] = refresh_state["running"]
    if refresh_state["error"]:
        out["refresh_error"] = refresh_state["error"]
    return out


HOT_TRADERS_FILE = Path(".data/hot_traders.json")


@app.get("/hot-traders")
def hot_traders():
    """入口页滚动条：本周政治盘热门交易者（hot_traders.py 定期写）。空=还没扫过。"""
    status, data = load_json(HOT_TRADERS_FILE, default=None)
    if status == OK and isinstance(data, dict):
        return data
    if status == CORRUPT:
        _log("   ⚠ 热门条文件损坏，已隔离为 .corrupt-* 备份；本次返回空条")
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
        if reason in BAD_REQUEST_REASONS:
            return _err(400, reason, position["message"])
        if reason in NO_POSITION_REASONS:
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
    if attach_i18n_en(response):
        _log(f"   🌐 i18n_en 已挂（{len(response['i18n_en'])} 条）")
    _log(f"   ✓ 简报生成完毕（耗时 {time.time() - t0:.1f}s）")

    try:
        BRIEFING_CACHE.mkdir(parents=True, exist_ok=True)
        atomic_write_json(cache_path, response)
        _log(f"   💾 已缓存 {cache_key}（同钱包零 token 秒回）")
    except Exception:
        pass
    return response


@app.get("/demo-wallets")
def demo_wallets():
    """已缓存看板的钱包清单（入口页"秒开"列表用）：这些钱包点开零 token 秒回。"""
    out, seen = [], set()
    try:
        for p in sorted(DASHBOARD_CACHE.glob(f"*_{BRIEFING_AS_OF}.json")):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            w = d.get("wallet")
            if not w or w.lower() in seen:
                continue
            seen.add(w.lower())
            prof = (d.get("identity") or {}).get("profile") or {}
            out.append({
                "wallet": w,
                "name": prof.get("name") or prof.get("pseudonym"),
                "market_question": ((d.get("position") or {}).get("meta") or {}).get("market"),
            })
    except Exception:
        pass
    return {"as_of": BRIEFING_AS_OF, "wallets": out}


# ── 生产托管：前端构建产物同源挂载（放在所有 API 路由之后，未匹配的路径落到 SPA）──
_FRONTEND_DIST = Path("frontend/dist")
if _FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIST), html=True), name="frontend")
