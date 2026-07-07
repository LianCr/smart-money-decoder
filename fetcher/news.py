"""
fetcher/news.py

职责：给定市场标题和建仓时间，返回相关新闻列表。
流程：AI 提取关键词 → Tavily 搜新闻 → 本地文件缓存
"""

import hashlib
import json
import os
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

from dotenv import load_dotenv
from tavily import TavilyClient

from core.llm import call_gateway, GatewayError

load_dotenv()

# ── 启动时检查 key，缺失立即报错，不要等到运行时才崩 ─────────────────────────
TAVILY_API_KEY    = os.environ.get("TAVILY_API_KEY")
CLASSROOM_API_KEY = os.environ.get("CLASSROOM_API_KEY")

if not TAVILY_API_KEY:
    raise RuntimeError("缺少 TAVILY_API_KEY，请在 .env 文件里配置")
if not CLASSROOM_API_KEY:
    raise RuntimeError("缺少 CLASSROOM_API_KEY，请在 .env 文件里配置")

# ── 配置项 ────────────────────────────────────────────────────────────────────
# True = 跳过真实网关，用占位关键词；等课堂 key approve 后改回 False
FAKE_MODE = os.environ.get("USE_FAKE_KEYWORDS", "false").lower() == "true"
CACHE_DIR         = Path(".cache/news")
MAX_RESULTS       = 5
MAX_DAYS_BACK     = 180   # Tavily 实测支持的最大天数
REQUEST_TIMEOUT   = 15    # 秒

_tavily = TavilyClient(api_key=TAVILY_API_KEY)


# ── 自定义异常 ────────────────────────────────────────────────────────────────
class NewsError(Exception):
    """新闻获取失败时统一抛这个，携带机器读的 reason 和人读的 message"""
    def __init__(self, reason: str, message: str):
        self.reason  = reason
        self.message = message
        super().__init__(message)


# ── 函数1（内部）：计算时间窗口 ────────────────────────────────────────────────
def _build_time_window(
    entry_time: int | None,
    as_of: int | None = None,
) -> tuple[str | None, str | None, bool]:
    """
    根据建仓时间戳计算新闻搜索的时间窗口。
    返回 (start_date, end_date, time_anchored)，日期格式 "YYYY-MM-DD"。

    as_of（unix 秒，可选）：把窗口上界（"现在"）钉在某历史快照时点，杜绝未来新闻泄漏。
      - 正向流程不传 → 用真实 now，行为完全不变。
      - **回测历史重放必须传快照时点（T-7/T-1）**：end 截到 as_of，下游 _fetch_from_tavily 的
        end_date 过滤会自动丢弃晚于该时点的文章。

    time_anchored=False 的含义：下游 AI 解码层必须降级处理，
    在卡片上注明"建仓时间未知，新闻仅供参考"。
    """
    if entry_time is None:
        return None, None, False

    now      = datetime.now(tz=timezone.utc)
    entry_dt = datetime.fromtimestamp(entry_time, tz=timezone.utc)

    # 未来时间是异常数据，当作未知处理
    if entry_dt > now:
        return None, None, False

    # 超过 Tavily 实测上限，拿不到那么早的新闻，如实返回 False
    if (now - entry_dt).days > MAX_DAYS_BACK:
        return None, None, False

    start_dt = entry_dt - timedelta(days=7)
    if as_of is not None:
        # 回测：窗延伸到快照时点 as_of —— 让 T-7 / T-1 各自看到「至该刻」的全部新闻
        #（T-1 窗是 T-7 的超集），且天然杜绝晚于该刻的未来文章。
        end_dt = min(datetime.fromtimestamp(as_of, tz=timezone.utc), now)
    else:
        # 正向：catalyst 窗 [建仓-7, 建仓+3]，行为完全不变
        end_dt = min(entry_dt + timedelta(days=3), now)

    # 建仓-7 晚于快照时点（极短盘 / 时点远早于建仓）→ 窗退化，news 降级
    if start_dt > end_dt:
        return None, None, False

    return (
        start_dt.strftime("%Y-%m-%d"),
        end_dt.strftime("%Y-%m-%d"),
        True,
    )


# ── 函数2（内部）：生成缓存文件路径 ───────────────────────────────────────────
def _get_cache_path(
    market_question: str,
    start_date: str | None,
    end_date: str | None,
) -> Path:
    """
    用 (market_question + 时间窗) 的 md5 生成缓存文件路径。

    为什么必须把时间窗加进 key（修正旧设计）：
    决定搜索结果的是时间窗本身，而时间窗已被 _build_time_window 量化到「天」
    （start/end 是 YYYY-MM-DD 字符串）。同一天的 entry_time 产生同一个窗、同一个 key，
    缓存照常命中，不会白刷 credit；而 entry_time=None（窗为 None/None，降级近30天）
    与「真锚定窗」会落在不同 key 下。

    旧实现只按 market_question 做 key，导致：先以 entry_time=None 跑出
    time_anchored=False 并缓存，之后 trades v2 拿到真 entry_time 再跑，仍命中旧缓存
    返回过期的 anchored=False —— 正是这个 bug 让 Netanyahu 钱包一度显示未锚定。
    """
    sig = f"{market_question}|{start_date}|{end_date}"
    key = hashlib.md5(sig.encode("utf-8")).hexdigest()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{key}.json"


# ── 函数3（内部）：用课堂网关 AI 提取搜索关键词 ───────────────────────────────
def _extract_keywords_via_ai(market_question: str) -> str:
    """
    用老师课堂网关调 claude-haiku-4.5，从市场标题里提取搜索关键词。
    不降级到规则提取——宁可整个 news 流程失败，也不用低质量关键词搜出噪音。
    """
    if not market_question.strip():
        raise ValueError("market_question 不能为空")

    if FAKE_MODE:
        # 去掉 "Will" 开头和标点，取前 5 个非停用词作为占位关键词
        words = [w for w in market_question.rstrip("?").split()
                 if w.lower() not in {"will", "the", "a", "an", "whether"}]
        return " ".join(words[:5])

    prompt = (
        "下面是一个预测市场的标题。请提取 2-4 个最适合用来搜索相关新闻动态的关键词，"
        "聚焦标题里的核心实体（人名、地名、事件），去掉 will/whether/by/before 这类"
        "对搜索无意义的词，也不要保留具体日期。只回复关键词本身，空格分隔，不要任何解释。\n"
        f"标题：{market_question}"
    )

    try:
        output = call_gateway(prompt, max_tokens=100, timeout=REQUEST_TIMEOUT).strip()
    except GatewayError as e:
        raise NewsError("KEYWORD_EXTRACT_FAILED", f"关键词提取失败：{e.message}")
    if not output:
        raise NewsError("KEYWORD_EXTRACT_FAILED", "关键词提取 API 返回了空结果")

    # 防止 AI 没遵守指令返回了长文，截断保护
    return output[:100]


# ── 函数4（内部）：调 Tavily 搜新闻 ────────────────────────────────────────────
def _fetch_from_tavily(
    keywords: str,
    start_date: str | None,
    end_date: str | None,
) -> list[dict]:
    """
    用 Tavily 搜索新闻，返回清洗后的文章列表。
    没有 published_at 的文章直接丢弃，保证 AI 解码层拿到的每条都有日期。
    """
    if start_date is not None:
        today     = datetime.now(tz=timezone.utc).date()
        start     = datetime.strptime(start_date, "%Y-%m-%d").date()
        days_back = (today - start).days + 1  # +1 确保覆盖 start 当天
    else:
        days_back = 30

    try:
        resp = _tavily.search(
            keywords,
            topic="news",
            days=days_back,
            max_results=MAX_RESULTS,
        )
    except Exception as e:
        msg = str(e).lower()
        if "timeout" in msg:
            raise NewsError("TAVILY_TIMEOUT", "Tavily 搜索超时，请稍后重试")
        if "429" in msg or "rate" in msg:
            raise NewsError("TAVILY_RATE_LIMITED", "Tavily 请求频率超限，请稍后重试")
        raise NewsError("TAVILY_API_ERROR", f"Tavily 搜索失败：{e}")

    articles = []
    for item in resp.get("results", []):
        # RFC 2822 → "YYYY-MM-DD"，解析失败则丢弃（宁少勿错）
        raw_date = item.get("published_date", "")
        try:
            published_at = parsedate_to_datetime(raw_date).strftime("%Y-%m-%d")
        except Exception:
            continue

        # 客户端过滤时间窗口（Tavily days 是"最近 N 天"，可能包含窗口外的文章）
        if end_date   and published_at > end_date:
            continue
        if start_date and published_at < start_date:
            continue

        # snippet 优先用 content，空时用 title 兜底
        snippet = (item.get("content") or "")[:300].strip()
        if not snippet:
            snippet = item.get("title", "")

        articles.append({
            "title":        item.get("title", ""),
            "url":          item.get("url", ""),
            "published_at": published_at,
            "source":       item.get("url", "").split("/")[2] if item.get("url") else "",
            "snippet":      snippet,
        })

    return articles


# ── 对外唯一入口 ───────────────────────────────────────────────────────────────
def get_news_for_market(
    market_question: str, entry_time: int | None, as_of: int | None = None
) -> dict:
    """
    给定市场标题和建仓时间戳，返回相关新闻及时间锚定状态。

    as_of（unix 秒，可选）：回测历史重放时把窗口上界钉在快照时点，杜绝未来新闻泄漏。
    正向流程不传 → 行为不变（见 _build_time_window）。

    成功：{"articles": [...], "search_query": str, "time_anchored": bool}
    失败：{"error": True, "reason": str, "message": str}
    """
    # 第一步：计算时间窗口
    start_date, end_date, time_anchored = _build_time_window(entry_time, as_of)

    # #7：回测（as_of 指定）下，窗口退化（time_anchored=False，如建仓晚于快照时点）时
    # **绝不走"近30天从现在往回"的兜底**——那不锚定、且无 as_of 上界 = 未来新闻泄漏。
    # 该时点这注的催化剂尚未发生，如实返回空新闻，下游 decoder 凭"无新闻"判 NO BASIS（正确）。
    if as_of is not None and not time_anchored:
        return {"articles": [], "search_query": "", "time_anchored": False}

    # 第二步：命中缓存则直接返回，跳过所有 API 调用
    # 注意：缓存 key 必须带时间窗，否则 entry_time 变化后会返回过期结果
    cache_path = _get_cache_path(market_question, start_date, end_date)
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            pass  # 缓存文件损坏则忽略，走正常流程重新拉取

    # 第三步：AI 提取关键词
    try:
        keywords = _extract_keywords_via_ai(market_question)
    except NewsError as e:
        return {"error": True, "reason": e.reason, "message": e.message}

    # 第四步：搜索新闻
    try:
        articles = _fetch_from_tavily(keywords, start_date, end_date)
    except NewsError as e:
        return {"error": True, "reason": e.reason, "message": e.message}

    # 第五步：组装并缓存结果
    result = {
        "articles":      articles,
        "search_query":  keywords,
        "time_anchored": time_anchored,
    }
    try:
        cache_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass  # 写缓存失败不影响主流程，静默跳过

    return result
