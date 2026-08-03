"""
tests/test_health.py — core/health 纯函数测试（无网络、tempdir 不碰真 .cache/.data）

背景：`render.yaml` 原来把 `healthCheckPath` 指向 `/backtest`，而那个端点只读两个
git 跟踪的静态 JSON，读失败还被 except 吞掉照样返回 200 —— 数据源全挂、key 全失效、
磁盘只读，它一律报"健康"。等于没有健康检查。

设计取舍（写进测试是为了让它不被随手改掉）：
  · **必填 key 缺失 = 不健康（503）**。没有它们，任何未缓存钱包都出不了板。
    这正是 P0-2 那次事故的形态：部署起来了、首页能开、一点陌生钱包就 502。
    宁可让部署当场失败，也不要静默地半死不活。三个必填 key 与 render.yaml 声明的
    "🔴 必填三项"保持一致 —— 契约只有一份。
  · **可选 key 缺失 = 健康但带警告（200）**。GITHUB_TOKEN / REDIS_URL 不影响出板，
    只影响持久化与跨实例协调，不该让实例被判死。
  · **目录不可写 = 不健康**。缓存写不下去 → 每次请求都重烧 token。

🔴 本测试只测 core/health 的纯函数，绝不 import api.main —— 后者在 import 时就会
复制 seed 目录、打 GitHub 网络请求（api/main.py 顶部），测试碰不得。这也是 health
逻辑要单独成模块、依赖靠参数注入的原因。
"""

import os
import stat
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")

from core.health import health_report

passed = 0
failed = 0


def check(name, got, want):
    global passed, failed
    if got == want:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name}: got={got!r} want={want!r}")


FULL_ENV = {
    "ANTHROPIC_API_KEY": "sk-ant-x",
    "TAVILY_API_KEY": "tvly-x",
    "HEISENBERG_API_KEY": "hz-x",
    "GITHUB_TOKEN": "ghp-x",
    "REDIS_URL": "redis://x",
}


def report(env, paths):
    return health_report(env=env, write_paths=paths)


# ── 1. 全齐 → 健康、无警告 ────────────────────────────────────────────────────
with tempfile.TemporaryDirectory() as td:
    paths = [Path(td) / ".cache", Path(td) / ".data"]
    r = report(FULL_ENV, paths)
    check("全部就绪 → ok=True", r["ok"], True)
    check("全部就绪 → 无 failures", r["failures"], [])
    check("全部就绪 → 无 warnings", r["warnings"], [])
    check("目录不存在会被建出来（不是判失败）", all(p.exists() for p in paths), True)


# ── 2. 必填 key 缺失 → 不健康，且明确说是哪个 ─────────────────────────────────
with tempfile.TemporaryDirectory() as td:
    paths = [Path(td) / ".cache"]

    e = dict(FULL_ENV); e.pop("ANTHROPIC_API_KEY")
    r = report(e, paths)
    check("缺 LLM key → ok=False", r["ok"], False)
    check("缺 LLM key → failures 指名道姓", any("llm" in f for f in r["failures"]), True)

    # CLASSROOM_API_KEY 是合法的另一个 LLM 后端（core/llm.py 二选一），不该判失败
    e2 = dict(e); e2["CLASSROOM_API_KEY"] = "classroom-x"
    check("CLASSROOM_API_KEY 也算 LLM key（二选一）", report(e2, paths)["ok"], True)

    e = dict(FULL_ENV); e.pop("HEISENBERG_API_KEY")
    r = report(e, paths)
    check("缺 Heisenberg key → ok=False", r["ok"], False)
    check("缺 Heisenberg key → failures 指名道姓", any("heisenberg" in f for f in r["failures"]), True)

    e = dict(FULL_ENV); e.pop("TAVILY_API_KEY")
    r = report(e, paths)
    check("缺 Tavily key → ok=False", r["ok"], False)

    r = report({}, paths)
    check("一个 key 都没有 → 三条 failures 全列出", len(r["failures"]), 3)


# ── 3. 可选 key 缺失 → 仍健康，但带警告（不该把实例判死）──────────────────────
with tempfile.TemporaryDirectory() as td:
    paths = [Path(td) / ".cache"]
    e = dict(FULL_ENV); e.pop("GITHUB_TOKEN"); e.pop("REDIS_URL")
    r = report(e, paths)
    check("缺可选 key → 仍 ok=True", r["ok"], True)
    check("缺可选 key → 进 warnings 而非 failures", len(r["warnings"]), 2)
    check("缺可选 key → failures 仍为空", r["failures"], [])


# ── 4. 目录不可写 → 不健康（缓存写不下去 = 每次请求都重烧 token）───────────────
with tempfile.TemporaryDirectory() as td:
    ro = Path(td) / "readonly"
    ro.mkdir()
    os.chmod(ro, stat.S_IRUSR | stat.S_IXUSR)          # r-x：能进不能写
    try:
        r = report(FULL_ENV, [ro / "sub"])
        check("目录不可写 → ok=False", r["ok"], False)
        check("目录不可写 → failures 提到路径", any("readonly" in f for f in r["failures"]), True)
    finally:
        os.chmod(ro, stat.S_IRWXU)                      # 还原，否则 tempdir 清不掉


# ── 5. 返回结构稳定（端点直接把它序列化成 JSON 返回）──────────────────────────
with tempfile.TemporaryDirectory() as td:
    r = report(FULL_ENV, [Path(td) / ".cache"])
    check("返回结构含 ok/failures/warnings/checks",
          sorted(r.keys()), ["checks", "failures", "ok", "warnings"])
    check("checks 是逐项布尔（便于前端/人眼扫）",
          all(isinstance(v, bool) for v in r["checks"].values()), True)
    check("checks 覆盖三个必填 + 两个可选 + 可写",
          len(r["checks"]) >= 6, True)
    check("🔴 checks 里绝不出现 key 的值本身（防泄漏到日志/响应）",
          any("sk-ant-x" in str(v) or "tvly-x" in str(v) for v in r["checks"].values()), False)


# ── 6. 不传参时读真实 os.environ，但不该崩（端点的默认调用路径）────────────────
r = health_report()
check("默认参数调用不炸", isinstance(r.get("ok"), bool), True)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
