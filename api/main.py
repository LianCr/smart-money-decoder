"""
api/main.py — smart-money-decoder 的 FastAPI 装配层（T2.3 起只剩装配，业务在 api/routes/）

端点分布：routes/dashboard（/dashboard /demo-wallets）· routes/recommend（/recommendations
/hot-traders）· routes/scorecard · routes/briefing（/briefing /market-context）·
routes/meta（/healthz /backtest）。共享件（_err/限流单例）在 api/shared.py。

错误统一返回 {"error": <reason>, "message": <中文人读>}，HTTP 状态码分层：
  - 钱包无合格仓位（NO_POSITION_REASONS 四种）   → 404
  - 地址格式非法（INVALID_ADDRESS）              → 400
  - 上游 API 失败（Heisenberg / Tavily / 网关）  → 502
  - 限流（P1-15 双闸）                           → 429

🔴 import api.main 零副作用（T2.3）：seed/GitHub 状态恢复在 lifespan、不在 import——
端点测试可直接 TestClient(app)。`api.main:app` 点路径是 render.yaml 部署契约，别动。

启动：
    .venv/bin/uvicorn api.main:app --reload --port 8000
"""

import shutil
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

load_dotenv()           # 🔴 必须先于一切本地 import：8 个模块在 import 时读 env

# 日志外壳先就位（P1-12）：启动期恢复日志也走统一格式（此时 rid="-"）
from core.log import get_logger, new_request_id, unify_uvicorn_logging, REQUEST_ID

LOG = get_logger("api")

from api.routes import briefing, dashboard, meta, recommend, scorecard


def _restore_state_on_startup() -> None:
    """启动期状态恢复（T2.3：从 import 顶层搬进 lifespan——import api.main 从此零副作用，
    端点测试三年做不了的病根就是这段在 import 时复制 seed + 打 GitHub）。

    种子缓存（部署用）：云端磁盘 ephemeral，每次冷启动从 git 跟踪的 seed/ 恢复；
    本地 .cache/.data 已存在 → 不覆盖；只有全新环境（如 Render 冷启动）才复制。
    GitHub 状态恢复（跨部署持久）：seed 之后再叠加远端 bundle，谁新用谁——刷新过的
    推荐榜/看板缓存/记分牌存在 app-state 分支（公开仓库 raw 拉取，恢复端无需 token）。"""
    for _src, _dst in [(Path("seed/cache"), Path(".cache")), (Path("seed/data"), Path(".data"))]:
        if _src.exists() and not _dst.exists():
            try:
                shutil.copytree(_src, _dst)
                LOG.info(f"🌱 种子缓存恢复：{_src} → {_dst}")
            except Exception as e:
                LOG.warning(f"⚠ 种子缓存恢复失败：{e}")
    try:
        from core.persist import fetch_bundle, restore_bundle
        _bundle = fetch_bundle()
        if _bundle:
            _n = restore_bundle(_bundle)
            LOG.info(f"☁️ GitHub 状态恢复：{_n} 个文件（app-state 分支）")
    except Exception as _e:
        LOG.warning(f"⚠ GitHub 状态恢复失败（不阻塞）：{_e}")


@asynccontextmanager
async def _lifespan(_app):
    """启动时把 anyio 工作线程池的隐式上限（40）显式化（AUDIT T1.4 顺带项）。
    全部端点都是同步 def、共享这个池；看板构建一条独占 worker 1-3 分钟——
    上限显式写死后可观测、可调，不再是"藏在 anyio 默认值里的事实"。数值不变=行为不变。
    另：uvicorn 自带 logger 此刻已配置完毕，套上统一日志格式（P1-12）；
    seed/GitHub 状态恢复也在这（T2.3 起不再是 import 副作用）。"""
    from anyio import to_thread
    to_thread.current_default_thread_limiter().total_tokens = 40
    unify_uvicorn_logging()
    _restore_state_on_startup()
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


# ── 每请求 request id（P1-12）：中间件 set contextvar → 同步端点跑在 anyio 线程池、
# contextvars 随任务拷贝进 worker → 整条 pipeline 的日志自动带同一 rid。
# 响应头回传 x-request-id，报障时用户可直接报这个号。
@app.middleware("http")
async def _request_id_middleware(request: Request, call_next):
    rid = request.headers.get("x-request-id") or new_request_id()
    token = REQUEST_ID.set(rid)
    try:
        response = await call_next(request)
        response.headers["x-request-id"] = rid
        return response
    finally:
        REQUEST_ID.reset(token)


app.include_router(meta.router)
app.include_router(dashboard.router)
app.include_router(recommend.router)
app.include_router(scorecard.router)
app.include_router(briefing.router)

# ── 生产托管：前端构建产物同源挂载（放在所有 API 路由之后，未匹配的路径落到 SPA）──
_FRONTEND_DIST = Path("frontend/dist")
if _FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIST), html=True), name="frontend")
