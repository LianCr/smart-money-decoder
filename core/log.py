"""
core/log.py — 全仓日志唯一出口（P1-12/T1.5：print → logging + request id）。

设计（对齐 T1.5 的三条约束）：
  1. **消息原文不动**：emoji 前缀、缩进、中文文案全保留——变的只是外壳
     `HH:MM:SS L [rid] <原消息>`，排查习惯不破坏。
  2. **request id 用 contextvar 贯穿**：api 层中间件对每个 HTTP 请求 set 一次，
     同步端点跑在 anyio 线程池里（contextvars 会拷贝进 worker 线程），整条
     pipeline（services/analyzer/fetcher/briefing）的日志自动带同一个 rid ——
     Render 上按 rid grep 即可串起一次请求的完整生命周期。
  3. **stdout 不换**：旧 _log 显式写 stdout（Render 采集 stdout），logging 默认
     stderr 会变行为，这里显式 StreamHandler(sys.stdout)。

背景任务没有 HTTP 请求：扫榜线程自设 `scan-xxxx`、ai_verify 各 worker 自设
`verify-<wallet前8>`（ThreadPoolExecutor 不继承 contextvars，见 AUDIT P1-12）。
LOG_LEVEL 环境变量可调（默认 INFO）；uvicorn 自带 logger 在 app lifespan 里
套上同一 formatter（unify_uvicorn_logging），全部日志一个长相。
"""

import contextvars
import logging
import os
import sys
import uuid

REQUEST_ID = contextvars.ContextVar("request_id", default="-")

_FMT = "%(asctime)s %(levelname).1s [%(rid)s] %(message)s"
_DATEFMT = "%H:%M:%S"
_CONFIGURED = False


class _RidFilter(logging.Filter):
    """把 contextvar 里的 request id 注进每条 record（uvicorn 的 record 也适用）。"""
    def filter(self, record):
        record.rid = REQUEST_ID.get()
        return True


def _make_handler() -> logging.Handler:
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(logging.Formatter(_FMT, datefmt=_DATEFMT))
    h.addFilter(_RidFilter())
    return h


def setup_logging() -> None:
    """幂等：给 smd 根 logger 挂 stdout handler + LOG_LEVEL（默认 INFO）。"""
    global _CONFIGURED
    if _CONFIGURED:
        return
    root = logging.getLogger("smd")
    root.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())
    root.addHandler(_make_handler())
    root.propagate = False          # 不上冒 root，避免双打
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """模块级入口：LOG = get_logger(__name__)。首次调用自动完成配置。"""
    setup_logging()
    return logging.getLogger(f"smd.{name}")


def new_request_id() -> str:
    return uuid.uuid4().hex[:8]


def unify_uvicorn_logging() -> None:
    """把 uvicorn 自带 logger（access/error）的 handler 换成同一 formatter+rid 过滤器。
    必须在 uvicorn 启动后调（app lifespan 里）——uvicorn 在 import 之后才配它的 logger。
    access 行发生在中间件上下文之外，rid 显示 "-" 属预期；串请求靠应用层日志。"""
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        if lg.handlers:
            lg.handlers = [_make_handler()]
            lg.propagate = False
