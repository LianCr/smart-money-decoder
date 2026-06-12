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
import sys
import time
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
from api.backtest_mock import MOCK_BACKTEST

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
_NO_POSITION_REASONS = {"NO_POSITIONS", "NO_POLITICAL_POSITIONS", "ALL_BELOW_MIN_VALUE"}
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


BACKTEST_RESULT = Path(".cache/backtest/result.json")


@app.get("/backtest")
def backtest():
    """
    Track Record 回测数据。

    有真实回测产物（.cache/backtest/result.json，由 backtest.pipeline 离线生成）→ 读它
    （_mock=false）；否则回退 MOCK 占位（_mock=true）。契约一致，前端无需区分。
    """
    if BACKTEST_RESULT.exists():
        try:
            data = json.loads(BACKTEST_RESULT.read_text(encoding="utf-8"))
            _log(f"\n=== /backtest （真实回测 · {len(data.get('samples', []))} 样本）===")
            return data
        except Exception as e:
            _log(f"\n=== /backtest （真实结果读取失败 {e}，回退 MOCK）===")
    _log("\n=== /backtest （MOCK 占位）===")
    return MOCK_BACKTEST


@app.get("/analyze")
def analyze(wallet: str):
    """跑完整 pipeline，返回解读卡片 JSON 或分层错误。"""
    t0 = time.time()
    wallet = (wallet or "").strip()
    _log(f"\n=== /analyze wallet={wallet[:14]}… ===")

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
    return response
