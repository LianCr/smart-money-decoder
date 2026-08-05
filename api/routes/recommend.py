"""api/routes/recommend.py — 扫榜推荐 + 热门条路由（T2.3 从 main.py 原样搬出）。

同文件收拢：/recommendations、/hot-traders、后台扫榜线程、GitHub 状态持久化——
_persist_app_state 引用 HOT_TRADERS_FILE 的前向引用陷阱随同文件化消解。
🔴 `_REC_REFRESH` 是状态单例（跨实例单飞协调），全仓只许这一份。
"""

import json
import os
from datetime import date
from pathlib import Path

from fastapi import APIRouter

from core.cachefiles import newest_dated
from core.config import BRIEFING_AS_OF
from core.jsonstore import CORRUPT, OK, atomic_write_text, load_json
from core.log import get_logger, new_request_id, REQUEST_ID
from core.redis_coord import coordinator
from core.refresh_jobs import RecommendationRefresh
from services.dashboard_build import DASHBOARD_CACHE
import scorecard

router = APIRouter()
LOG = get_logger("api.recommend")


def _log(msg: str) -> None:
    LOG.info(msg)


RECOMMEND_FILE = Path(".data/recommendations.json")
HOT_TRADERS_FILE = Path(".data/hot_traders.json")

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
    # 后台线程无 HTTP 请求上下文（Thread 不继承 contextvars）→ 自设扫描 job id，
    # Render 上按 scan-xxxx 即可串起整场扫榜的日志（P1-12）
    REQUEST_ID.set(f"scan-{new_request_id()[:4]}")
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


@router.get("/recommendations")
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


@router.get("/hot-traders")
def hot_traders():
    """入口页滚动条：本周政治盘热门交易者（hot_traders.py 定期写）。空=还没扫过。"""
    status, data = load_json(HOT_TRADERS_FILE, default=None)
    if status == OK and isinstance(data, dict):
        return data
    if status == CORRUPT:
        _log("   ⚠ 热门条文件损坏，已隔离为 .corrupt-* 备份；本次返回空条")
    return {"as_of": BRIEFING_AS_OF, "period": "7d", "traders": []}
