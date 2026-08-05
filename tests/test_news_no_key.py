"""
tests/test_news_no_key.py — 缺 API key 时必须"调用才失败"，而不是"import 就崩"（P1-24）

背景（真实事故，用干净检出实测出来的）：
`git archive origin/master` 导出一份没有 .env 的干净树、清空全部 key 后跑测试套件，
`tests/test_news.py` 与 `tests/test_market_thesis.py` **连 import 都过不去** ——
因为 fetcher/news.py 在模块顶层就 `raise RuntimeError("缺少 TAVILY_API_KEY")`。

为什么这必须修：
  1. 它卡死 CI。而"CI 不注入任何 key"正是我们要的 —— 只有这样才能钉死
     `CLAUDE.md` 协作纪律 #1「测试是 mock、不打网络、零 token、谁都能跑」。
  2. 新协作者 clone 下来、key 还没申请到时，应该能立刻跑通全部测试。
  3. 它和 api/main.py 曾在 import 时复制 seed、打 GitHub 是同一类（后者已于 T2.3 治好）
     **import 时副作用**问题 —— 模块被 import 不等于它要开始干活。

契约（本文件钉死）：
  A. 无 .env、无任何 key 时，`import fetcher.news` 与 `import analyzer.dual_catalyst`
     **必须成功**（这两条是当初真正炸掉的 import 链）
  B. 缺 Tavily key 时，`get_news_for_market` **按模块既有错误契约**返回
     {"error": True, "reason": ..., "message": ...} —— 失败发生在真要用 key 的那一刻
  C. key 齐全时行为**完全不变**（用 fake client 验证既有成功路径没被改坏）

🔴 为什么 import 测试要开子进程：本仓库跑测试时 .env 是存在的，而 news.py 顶层的
`load_dotenv()` 会把 key 读回 os.environ —— 只靠 `del os.environ[...]` 根本模拟不出
"干净环境"。所以子进程里先把 `dotenv.load_dotenv` 打成 no-op，**精确等价于"没有 .env
文件"**，再清 key、再 import。
"""

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")

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


REPO = Path(__file__).resolve().parent.parent

# 子进程序幕：模拟"没有 .env 文件 + 环境里一个 key 都没有"的干净机器
_PRELUDE = """
import dotenv
dotenv.load_dotenv = lambda *a, **k: False      # 等价于"仓库里没有 .env"
import os
for _k in ("TAVILY_API_KEY", "ANTHROPIC_API_KEY", "CLASSROOM_API_KEY",
           "HEISENBERG_API_KEY", "GITHUB_TOKEN"):
    os.environ.pop(_k, None)
import sys
sys.path.insert(0, {repo!r})
"""


def run_clean(body: str):
    """在"零 key 干净环境"子进程里跑一段代码，返回 (returncode, stdout+stderr)。"""
    code = _PRELUDE.format(repo=str(REPO)) + body
    r = subprocess.run([sys.executable, "-c", code], cwd=str(REPO),
                       capture_output=True, text=True, timeout=120)
    return r.returncode, (r.stdout + r.stderr)


# ── A. 零 key 环境下 import 必须成功 ──────────────────────────────────────────
rc, out = run_clean("import fetcher.news; print('IMPORT_OK')")
check("🔴 无 key 时 import fetcher.news 成功", rc == 0 and "IMPORT_OK" in out, True)
if rc != 0:
    print(f"      子进程输出：{out[-500:]}")

# dual_catalyst 会 import fetcher.news（analyzer/dual_catalyst.py 的 _build_time_window 复用），
# 正是它让 test_market_thesis.py 一起被拖垮的
rc, out = run_clean("import analyzer.dual_catalyst; print('IMPORT_OK')")
check("🔴 无 key 时 import analyzer.dual_catalyst 成功", rc == 0 and "IMPORT_OK" in out, True)
if rc != 0:
    print(f"      子进程输出：{out[-500:]}")

# ── B. 缺 key 的失败必须发生在调用时，且走模块既有错误契约 ────────────────────
rc, out = run_clean("""
import fetcher.news as news
r = news.get_news_for_market("Will X happen by June 2026?", None)
print("ERROR_FLAG", r.get("error"))
print("REASON", r.get("reason"))
print("HAS_MESSAGE", bool(r.get("message")))
""")
check("无 key 调用不抛异常（返回错误字典而非崩）", rc, 0)
check("无 key 调用 → error=True", "ERROR_FLAG True" in out, True)
check("无 key 调用 → 带机器读 reason", "REASON None" not in out and "REASON" in out, True)
check("无 key 调用 → 带人读 message", "HAS_MESSAGE True" in out, True)
if rc != 0:
    print(f"      子进程输出：{out[-500:]}")

# ── C. key 齐全时既有成功路径不变（fake client，不打网络）────────────────────
import fetcher.news as news

class _FakeTavily:
    def search(self, keywords, topic=None, days=None, max_results=None):
        return {"results": [
            {"title": "Real headline", "url": "https://example.com/a",
             "content": "body text", "published_date": "Mon, 15 Jun 2026 10:00:00 +0000"},
            {"title": "No date, must be dropped", "url": "https://example.com/b",
             "content": "x", "published_date": "not-a-date"},
        ]}

_orig_client, _orig_fake, _orig_cache = news._tavily, news.FAKE_MODE, news.CACHE_DIR
with tempfile.TemporaryDirectory() as td:
    news._tavily = _FakeTavily()
    news.FAKE_MODE = True                     # 跳过 LLM 关键词（本测试不测那条链）
    news.CACHE_DIR = Path(td)                 # 绝不碰真 .cache/news
    try:
        arts = news._fetch_from_tavily("x", "2026-06-01", "2026-06-30")
        check("有 client 时正常返回文章", len(arts), 1)
        check("无法解析日期的文章被丢弃（宁少勿错）", arts[0]["title"], "Real headline")
        check("published_at 归一成 YYYY-MM-DD", arts[0]["published_at"], "2026-06-15")
    finally:
        news._tavily, news.FAKE_MODE, news.CACHE_DIR = _orig_client, _orig_fake, _orig_cache

# client 为 None 时必须报"缺 key"，而不是被 :186 那个宽泛 except 吞成"Tavily 调用失败"。
# 🔴 这条很重要：两者的运维含义完全不同 —— 一个是"你没配 key"（改配置就好），
# 一个是"Tavily 挂了/限流"（等它恢复）。报错原因指错方向比不报还糟。
news._tavily = None
try:
    news._fetch_from_tavily("x", None, None)
    check("client=None 时必须抛错", "没抛", "NewsError")
except news.NewsError as e:
    check("client=None → NewsError（不是 AttributeError）", True, True)
    check("🔴 reason 明确指向缺 key，不是泛泛的 TAVILY_API_ERROR", e.reason, "NO_TAVILY_KEY")
    check("message 提到 TAVILY_API_KEY（人能照着修）", "TAVILY_API_KEY" in e.message, True)
except Exception as e:
    check("client=None → NewsError", type(e).__name__, "NewsError")
finally:
    news._tavily = _orig_client

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
