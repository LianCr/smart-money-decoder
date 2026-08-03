"""
core/health.py — 真正探活的健康检查（纯函数，依赖靠参数注入）

为什么要有它：`render.yaml` 原来把 `healthCheckPath` 指向 `/backtest`，而那个端点
只读两个 git 跟踪的静态 JSON，读失败还被 except 吞掉照样 200。数据源全挂、key 全
失效、磁盘只读 —— 它一律报"健康"。等于没装健康检查。

判定口径（刻意的取舍，不是随手定的）：

  **必填 key 缺失 = 不健康（503）**
      没有它们，任何未缓存钱包都出不了板。这正是 P0-2 那次事故的形态：部署起来了、
      首页能开、一点陌生钱包就 502，而且没有任何地方会告诉你。宁可让部署当场失败。
      三项与 `render.yaml` 里声明的「🔴 必填三项」严格一致 —— 契约只有一份，
      改那边就要改这边。
      （诚实说明取舍的另一面：缺 key 的实例其实仍能靠缓存服务已有钱包。我们仍然选择
       报不健康 —— 因为"半死不活但看着正常"正是这次审计反复在修的那类问题。）

  **可选 key 缺失 = 健康 + 警告（200）**
      GITHUB_TOKEN 只影响跨部署持久化、REDIS_URL 只影响跨实例协调，两者都有明确的
      降级路径（见 core/persist.py、core/redis_coord.py），不该让实例被判死。

  **目录不可写 = 不健康**
      缓存落不了盘 → 每个请求都重烧 token，比慢更糟。

🔴 为什么单独成模块而不是写在 api/main.py 里：`api/main.py` 在 import 时就会复制
seed 目录、打 GitHub 网络请求，测试根本碰不得。健康检查必须能被单测，所以逻辑放这里、
env 和路径全部通过参数注入，端点只做薄薄一层转发。
"""

import os
from pathlib import Path

# 与 render.yaml 的「🔴 必填三项」一一对应
REQUIRED_DATA_KEY = "HEISENBERG_API_KEY"      # 持仓/成交/PnL/K线/榜单，整个数据层
REQUIRED_NEWS_KEY = "TAVILY_API_KEY"          # 新闻检索
# LLM 是二选一：官方 API 优先，课堂网关是回落位（见 core/llm.py）
LLM_KEYS = ("ANTHROPIC_API_KEY", "CLASSROOM_API_KEY")

# 缺了会降级但不致命的（各自有明确降级路径）
OPTIONAL_KEYS = {
    "GITHUB_TOKEN": "跨部署状态持久化关闭（刷新的推荐榜/记分牌冷启动后退回 seed 快照）",
    "REDIS_URL": "跨实例协调关闭（自动回退进程内单飞，单实例部署无影响）",
}

DEFAULT_WRITE_PATHS = (Path(".cache"), Path(".data"))


def _writable(path: Path) -> bool:
    """目录能不能真的写进去 —— 只判 os.access 不够（只读挂载/容器里会骗人），真写一个再删。"""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".healthz-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except Exception:
        return False


def health_report(env=None, write_paths=None) -> dict:
    """返回 {ok, failures[], warnings[], checks{}}。纯函数：env 与路径都可注入，便于单测。

    ok=False → 调用方应返回 503（实例干不了正经活，让部署/负载均衡当场知道）。
    🔴 checks 里只放布尔，**绝不回显 key 的值** —— 健康检查是公开端点，回显等于泄漏。
    """
    env = os.environ if env is None else env
    paths = [Path(p) for p in (write_paths if write_paths is not None else DEFAULT_WRITE_PATHS)]

    has_llm = any(env.get(k) for k in LLM_KEYS)
    has_data = bool(env.get(REQUIRED_DATA_KEY))
    has_news = bool(env.get(REQUIRED_NEWS_KEY))

    checks = {
        "llm_key": has_llm,
        "heisenberg_key": has_data,
        "tavily_key": has_news,
    }
    failures = []
    if not has_llm:
        failures.append(f"llm_key 缺失：需要 {' 或 '.join(LLM_KEYS)}，否则任何未缓存钱包都出不了板")
    if not has_data:
        failures.append(f"heisenberg_key 缺失：需要 {REQUIRED_DATA_KEY}，整个数据层不可用")
    if not has_news:
        failures.append(f"tavily_key 缺失：需要 {REQUIRED_NEWS_KEY}，新闻检索不可用")

    warnings = []
    for key, consequence in OPTIONAL_KEYS.items():
        present = bool(env.get(key))
        checks[f"{key.lower()}_present"] = present
        if not present:
            warnings.append(f"{key} 未配置：{consequence}")

    for p in paths:
        ok = _writable(p)
        checks[f"writable:{p}"] = ok
        if not ok:
            failures.append(f"目录不可写：{p} —— 缓存落不了盘，每个请求都会重烧 token")

    return {"ok": not failures, "failures": failures, "warnings": warnings, "checks": checks}
