"""api/routes/briefing.py — 完整简报 + 市场 Context 路由（T2.3 从 main.py 原样搬出）。"""

import json
import time

from fastapi import APIRouter

from api.shared import _err
from briefing import board_feed
from briefing.assemble import load_or_build_briefing
from briefing.market_context import load_or_build as build_market_context
from briefing.organize import organize_briefing
from core.config import BRIEFING_AS_OF
from core.jsonstore import atomic_write_json
from core.log import get_logger
from core.translate import attach_i18n_en
from fetcher.positions import get_top_political_position_hz
from services.dashboard_build import (
    BAD_REQUEST_REASONS, BRIEFING_CACHE, NO_POSITION_REASONS, entities_from_question,
)

router = APIRouter()
LOG = get_logger("api.briefing")


def _log(msg: str) -> None:
    LOG.info(msg)


@router.get("/market-context")
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


@router.get("/briefing")
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
