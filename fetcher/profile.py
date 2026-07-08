"""
fetcher/profile.py — A·主体画像 fetcher（v3 简报数据层 · 批2）

职责：给定钱包地址，组装"这人靠不靠谱"的画像。建在 fetcher/heisenberg.py 地基之上。
数据源（全免费 key、不烧老师 token）：
- 581 Wallet360   → 质量分/风险/回撤/这类盘行家（category specialization）
- 579 Leaderboard → 官方排名/胜率/Sharpe/已实现总盈亏（可按地址直接定位）
- 569 PnL         → 近窗已实现盈亏（realized）
- 584 H-Score     → 🔴 无按地址 lookup，只能"best-effort 看是否在榜页"（定位官方排名以 579 为准）

口径纪律：per-仓位真实盈亏要用 556+574 自重建（见路 B），569/579 是钱包级汇总，画像够用。
581 的 window_days 仅 1/3/7/15（用 15 取最宽）；569 宽窗只返前若干天，故只取近窗汇总。
"""

import json
from datetime import datetime, timedelta

from core.config import BRIEFING_AS_OF
from fetcher.heisenberg import AGENTS, HeisenbergError, call, results

# 581 想要的核心字段（存在才取，缺了不报错）
_W360_FIELDS = [
    "combined_risk_score", "max_drawdown", "drawdown_frequency", "avg_trade_size",
    "markets_traded", "num_markets_traded", "category_diversity_score",
    "market_concentration_ratio", "annualized_return", "gain_to_pain_ratio",
    "equity_curve_pattern", "perfect_timing_flag", "flagged_metrics",
    "losing_trades", "best_market_pnl", "dominant_market_pnl",
]


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _wallet360(wallet, window_days="15"):
    agent, wp = AGENTS["wallet360"]
    rs = results(call(agent, {wp: wallet, "window_days": window_days}))
    if not rs:
        return None, []
    rec = rs[0]
    quality = {k: rec[k] for k in _W360_FIELDS if k in rec}
    quality["window_days"] = window_days
    # performance_by_category 是 JSON 字符串 → 解析成"这类盘行家"清单
    cats = []
    raw = rec.get("performance_by_category")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = []
    if isinstance(raw, list):
        for c in raw:
            cats.append({"category": c.get("category"), "roi": c.get("roi"),
                         "win_rate": c.get("win_rate"), "total_pnl": c.get("total_pnl"),
                         "total_trades": c.get("total_trades")})
    return quality, cats


def _leaderboard(wallet, period="30d"):
    agent, wp = AGENTS["leaderboard"]
    rs = results(call(agent, {wp: wallet, "leaderboard_period": period}))
    if not rs:
        return None
    r = rs[0]
    return {"period": period, "rank": r.get("rank"), "roi": r.get("roi"),
            "win_rate": r.get("win_rate"), "sharpe_ratio": r.get("sharpe_ratio"),
            "total_pnl": r.get("total_pnl"), "total_invested": r.get("total_invested"),
            "total_trades": r.get("total_trades"), "markets_traded": r.get("markets_traded")}


def _realized_pnl(wallet, start_date, end_date):
    """569 近窗已实现盈亏汇总（best-effort：宽窗会被截断，故传窄窗）。"""
    agent, wp = AGENTS["pnl"]
    rs = results(call(agent, {wp: wallet, "granularity": "1d",
                              "start_time": start_date, "end_time": end_date}))
    total = sum(_f(r.get("pnl")) or 0 for r in rs)
    return {"window": [start_date, end_date], "days_returned": len(rs), "realized_pnl_sum": round(total, 2)}


def _hscore_besteffort(wallet):
    """584 无按地址查 → 拉一页按 pnl 排序的榜，看该地址在不在（在=返回其 tier/分）。"""
    agent, _ = AGENTS["hscore"]
    try:
        rs = results(call(agent, {"min_roi_15d": "0", "min_total_trades_15d": "10",
                                  "max_total_trades_15d": "100000", "sort_by": "pnl"}, limit=100))
    except HeisenbergError:
        return {"available": False, "note": "584 拉取失败"}
    w = wallet.lower()
    for r in rs:
        if str(r.get("wallet", "")).lower() == w:
            return {"available": True, "h_score": r.get("h_score"), "tier": r.get("tier"),
                    "leaderboard_rank": r.get("leaderboard_rank")}
    return {"available": False, "note": "不在 H-Score 榜首页（584 无按地址查，官方排名见 official_rank/579）"}


def get_trader_profile(wallet, lb_period="30d", pnl_window=None):
    """
    组装钱包画像。任一子源失败不拖垮整体——失败的位置返回 {"error": reason}，其余照常。
    pnl_window：569 近窗（默认锚 BRIEFING_AS_OF 往前 30 天；569 宽窗只回前几天，须传窄窗避免截断）。
    """
    if pnl_window is None:
        end = datetime.strptime(BRIEFING_AS_OF, "%Y-%m-%d")
        pnl_window = ((end - timedelta(days=30)).strftime("%Y-%m-%d"), BRIEFING_AS_OF)
    profile = {"wallet": wallet}

    try:
        quality, cats = _wallet360(wallet)
        profile["quality"] = quality or {"error": "581 返回空"}
        profile["category_specialization"] = cats
    except HeisenbergError as e:
        profile["quality"] = {"error": f"{e.reason}: {e.message}"}
        profile["category_specialization"] = []

    try:
        profile["official_rank"] = _leaderboard(wallet, lb_period) or {"error": "579 返回空"}
    except HeisenbergError as e:
        profile["official_rank"] = {"error": f"{e.reason}: {e.message}"}

    try:
        profile["realized_pnl_recent"] = _realized_pnl(wallet, pnl_window[0], pnl_window[1])
    except HeisenbergError as e:
        profile["realized_pnl_recent"] = {"error": f"{e.reason}: {e.message}"}

    try:
        profile["h_score"] = _hscore_besteffort(wallet)
    except HeisenbergError as e:
        profile["h_score"] = {"available": False, "note": f"{e.reason}: {e.message}"}

    return profile


# ── 冒烟测（免费 key、不烧老师 token）──────────────────────────────────────────
if __name__ == "__main__":
    KEN = "0x9d84ce0306f8551e02efef1680475fc0f1dc1344"   # ImJustKen
    p = get_trader_profile(KEN)

    print("批2 profile.py 冒烟测 · ImJustKen\n" + "=" * 64)

    q = p["quality"]
    print("【质量分(581)】", "error" in q and q["error"] or "")
    if "error" not in q:
        for k in ("combined_risk_score", "max_drawdown", "markets_traded",
                  "category_diversity_score", "flagged_metrics", "equity_curve_pattern"):
            if k in q:
                print(f"  {k} = {q[k]}")

    print("\n【这类盘行家(581 category)】")
    for c in p["category_specialization"][:6]:
        print(f"  {str(c['category']):16s} roi={c['roi']} win={c['win_rate']} "
              f"pnl={c['total_pnl']} trades={c['total_trades']}")

    print("\n【官方排名(579)】")
    r = p["official_rank"]
    print(" ", json.dumps(r, ensure_ascii=False))

    print("\n【近窗已实现盈亏(569)】")
    print(" ", json.dumps(p["realized_pnl_recent"], ensure_ascii=False))

    print("\n【H-Score(584 best-effort)】")
    print(" ", json.dumps(p["h_score"], ensure_ascii=False))

    print("\n画像 fetcher 就绪。")
