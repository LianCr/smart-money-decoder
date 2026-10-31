"""
tests/test_news.py — fetcher/news.py 的 #7 时间窗逻辑单测（无网络）

锁住 #7（回测各时点重搜 + as_of 硬截断）的行为，防回归：
  - _build_time_window：正向（as_of=None）不变；回测（as_of）end 延到快照时点、
    T-1 是 T-7 超集；窗退化/异常 → (None,None,False)。
  - get_news_for_market：回测下窗退化时**不走 30 天兜底**（返回空、不触网），杜绝泄漏。
"""

import sys
from datetime import datetime, timedelta, timezone
sys.path.insert(0, ".")

import fetcher.news as news
from fetcher.news import _build_time_window, get_news_for_market

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


UTC = timezone.utc
NOW = datetime.now(tz=UTC)


def u(dt):
    return int(dt.timestamp())


def d(dt):
    return dt.strftime("%Y-%m-%d")


# 用 now 相对量，保证测试不随运行时间漂移（entry 近期、未来、过老分别覆盖）
entry_dt = NOW - timedelta(days=30)
entry = u(entry_dt)

# 1. 正向（as_of=None）：窗 = [entry-7, entry+3]，行为不变
check("正向窗 = [entry-7, entry+3]",
      _build_time_window(entry),
      (d(entry_dt - timedelta(days=7)), d(entry_dt + timedelta(days=3)), True))

# 2. 回测 as_of 晚于 entry+3：end 延到 as_of（不是停在 entry+3）
as_of_late = u(entry_dt + timedelta(days=12))
check("回测 end 延到 as_of",
      _build_time_window(entry, as_of=as_of_late),
      (d(entry_dt - timedelta(days=7)), d(entry_dt + timedelta(days=12)), True))

# 3. T-7 vs T-1：end 不同，T-1 是 T-7 超集
t7 = _build_time_window(entry, as_of=u(entry_dt + timedelta(days=2)))
t1 = _build_time_window(entry, as_of=u(entry_dt + timedelta(days=9)))
check("T-7/T-1 起点相同", t7[0] == t1[0], True)
check("T-1 end 晚于 T-7 end（超集）", t1[1] > t7[1], True)

# 4. 窗退化：as_of 早于 entry-7 → start>end → (None,None,False)
check("窗退化 → 全 None",
      _build_time_window(entry, as_of=u(entry_dt - timedelta(days=10))),
      (None, None, False))

# 5. entry_time=None → (None,None,False)
check("entry=None → 全 None", _build_time_window(None), (None, None, False))

# 6. entry 在未来 → (None,None,False)
check("entry 未来 → 全 None",
      _build_time_window(u(NOW + timedelta(days=2))), (None, None, False))

# 7. entry 超过 MAX_DAYS_BACK（180 天）→ (None,None,False)
check("entry 过老 → 全 None",
      _build_time_window(u(NOW - timedelta(days=news.MAX_DAYS_BACK + 5))),
      (None, None, False))


# ── get_news_for_market：回测窗退化时不触网、返回空 ──────────────────────────
# monkeypatch：窗退化 + 若触网就炸，证明走了"返回空"的早退路径
_orig_build, _orig_fetch, _orig_kw = news._build_time_window, news._fetch_from_tavily, news._extract_keywords_via_ai
def _degraded(*a, **k):
    return (None, None, False)

def _boom_tavily(*a, **k):
    raise AssertionError("不应触网：回测窗退化时应直接返回空")

def _boom_kw(*a, **k):
    raise AssertionError("不应提关键词：回测窗退化时应直接返回空")

news._build_time_window = _degraded
news._fetch_from_tavily = _boom_tavily
news._extract_keywords_via_ai = _boom_kw
try:
    r = get_news_for_market("any market", 1700000000, as_of=1700000000)
    check("回测窗退化 → 空 articles", r.get("articles"), [])
    check("回测窗退化 → time_anchored False", r.get("time_anchored"), False)
finally:
    # 还原，别影响其它测试
    news._build_time_window, news._fetch_from_tavily, news._extract_keywords_via_ai = _orig_build, _orig_fetch, _orig_kw


# ── 检索按窗搜，不是"搜最近再过滤"（edge_lift_v1 发现：63% 样本被滤成零新闻）────
# 旧行为：days=从窗起点到今天，取 top-5 → 几乎全是窗口之后的新文章，客户端过滤后剩 0。
# 新行为：窗两端都在时，把 start_date/end_date 交给 Tavily，days 必须显式 None
#（SDK 0.5.0 默认会带 days=3，和 start_date 同发 → API 400，实测）。
import hashlib
import tempfile
from pathlib import Path

class _RecordingTavily:
    def __init__(self):
        self.calls = []
    def search(self, keywords, **kw):
        self.calls.append(kw)
        return {"results": [
            {"title": "in window", "url": "https://e.com/a", "content": "x",
             "published_date": "Tue, 21 Jul 2026 10:00:00 +0000"},
            {"title": "after window", "url": "https://e.com/b", "content": "x",
             "published_date": "Thu, 10 Sep 2026 10:00:00 +0000"},
        ]}

_orig_client = news._tavily
rec = _RecordingTavily()
news._tavily = rec
try:
    arts = news._fetch_from_tavily("hormuz", "2026-07-20", "2026-07-28")
    kw = rec.calls[-1]
    check("窗两端都在 → 传 start_date", kw.get("start_date"), "2026-07-20")
    check("窗两端都在 → 传 end_date", kw.get("end_date"), "2026-07-28")
    check("🔴 窗两端都在 → days 显式 None（否则 API 400）", "days" in kw and kw["days"] is None, True)
    check("仍是 news topic、条数不变", (kw.get("topic"), kw.get("max_results")), ("news", news.MAX_RESULTS))
    check("客户端窗过滤仍在（防御：API 回了窗外的也丢）", [a["title"] for a in arts], ["in window"])

    news._fetch_from_tavily("hormuz", None, None)
    kw = rec.calls[-1]
    check("无窗 → 老路径 days=30、不带 start_date", (kw.get("days"), "start_date" in kw), (30, False))
finally:
    news._tavily = _orig_client

# 缓存 key 带检索版本：旧检索方式缓存下的空结果不许被新代码命中（否则修了等于没修）
_orig_cache = news.CACHE_DIR
with tempfile.TemporaryDirectory() as td:
    news.CACHE_DIR = Path(td)
    try:
        p_new = news._get_cache_path("q", "2026-07-20", "2026-07-28")
        old_key = hashlib.md5("q|2026-07-20|2026-07-28".encode("utf-8")).hexdigest()
        check("新缓存 key ≠ 旧检索方式的 key", p_new.name != f"{old_key}.json", True)
        check("同输入 key 稳定（照常命中、不白刷 credit）",
              p_new == news._get_cache_path("q", "2026-07-20", "2026-07-28"), True)
    finally:
        news.CACHE_DIR = _orig_cache


print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
