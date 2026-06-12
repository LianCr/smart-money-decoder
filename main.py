"""
main.py — smart-money-decoder 串联入口

用法：
    .venv/bin/python main.py <wallet_address>
    .venv/bin/python main.py            # 不带参数时交互式输入

数据流（与 CLAUDE.md 架构一致）：
    polymarket.get_top_political_position  →  最大政治仓位
    activity.get_entry_time                →  建仓时间（可降级 None）
    news.get_news_for_market               →  时间窗新闻（可降级近 30 天）
    decoder.decode_position                →  AI 解读卡片
    renderer.card.render                   →  终端渲染

错误处理：
  - 三层 fetcher 中 polymarket / news 以 {"error": True, ...} 形式返回，逐层短路。
  - activity 抛 ActivityAPIError，这里捕获后降级为 entry_time=None（不致命，继续往下）。
  - decoder 抛 DecoderError，捕获后打印 reason + message 并退出。
"""

import sys

from dotenv import load_dotenv

load_dotenv()

from fetcher.polymarket import get_top_political_position
from fetcher.activity import get_entry_time, ActivityAPIError
from fetcher.trades import get_entry_time_v2
from fetcher.news import get_news_for_market
from analyzer.decoder import decode_position, DecoderError
from renderer.card import render


def _progress(msg: str) -> None:
    """进度提示打到 stderr，不污染 stdout 的卡片输出（方便重定向）。"""
    print(msg, file=sys.stderr, flush=True)


def _resolve_entry_time(wallet: str, condition_id: str) -> int | None:
    """
    建仓时间三级解析：
      1. trades v2（按市场维度查 /trades，whale 老仓位也能命中）
      2. trades v2 抛错或返回 None → 回退老 activity.py（翻全活动流，150 条上限）
      3. 仍无 → None（合法降级，下游照常运行）

    两条路都复用 ActivityAPIError，单个 except 兜住。任一路网络抖动只降级、不致命。
    """
    # 第一路：trades v2（首选）
    try:
        et = get_entry_time_v2(wallet, condition_id)
        if et is not None:
            _progress(f"   ✓ entry_time={et}（trades v2 命中）")
            return et
    except ActivityAPIError as e:
        _progress(f"   ⚠️  trades v2 失败 [{e.reason}]，回退老 activity")

    # 第二路：老 activity.py（fallback）
    try:
        et = get_entry_time(wallet, condition_id)
        if et is not None:
            _progress(f"   ✓ entry_time={et}（activity fallback 命中）")
            return et
    except ActivityAPIError as e:
        _progress(f"   ⚠️  activity 也失败 [{e.reason}]，降级 entry_time=None")

    # 第三路：降级
    _progress("   ⚠️  entry_time=None（trades 与 activity 均无买入记录，合法降级）")
    return None


def _fail(msg: str) -> None:
    """致命错误统一出口：打到 stderr，退出码 1。"""
    print(f"❌ {msg}", file=sys.stderr, flush=True)
    sys.exit(1)


def run(wallet: str) -> None:
    wallet = wallet.strip()

    # ── 第 1 层：最大政治仓位 ──────────────────────────────────────────────────
    _progress(f"① 拉取最大政治仓位  ({wallet[:12]}…)")
    position = get_top_political_position(wallet)
    if position.get("error"):
        _fail(f"[{position['reason']}] {position['message']}")
    _progress(f"   ✓ {position['market_question'][:50]}  ·  {position['outcome']}")

    # ── 第 2 层：建仓时间（trades v2 → activity fallback → None）───────────────
    _progress("② 查询建仓时间（trades v2 优先，activity 兜底）")
    entry_time = _resolve_entry_time(wallet, position["market_id"])

    # ── 第 3 层：时间窗新闻 ────────────────────────────────────────────────────
    _progress("③ 搜索时间窗新闻")
    news = get_news_for_market(position["market_question"], entry_time)
    if news.get("error"):
        _fail(f"[{news['reason']}] {news['message']}")
    _progress(f"   ✓ {len(news['articles'])} 条  ·  time_anchored={news['time_anchored']}")

    # ── 组装数据契约 dict（字段名严格对齐 CLAUDE.md）──────────────────────────
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
    _progress("④ AI 解读（课堂网关 sonnet-4.5）")
    try:
        card = decode_position(assembled)
    except DecoderError as e:
        _fail(f"[{e.reason}] {e.message}")
    _progress("   ✓ 卡片生成完毕\n")

    # ── 渲染：卡片打到 stdout ─────────────────────────────────────────────────
    print(render(card, position))


def main() -> None:
    if len(sys.argv) >= 2:
        wallet = sys.argv[1]
    else:
        try:
            wallet = input("请输入 Polymarket 钱包地址 (0x…): ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(130)
    if not wallet:
        _fail("未提供钱包地址")
    run(wallet)


if __name__ == "__main__":
    main()
