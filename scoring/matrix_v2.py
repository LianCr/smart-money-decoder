"""
scoring/matrix_v2.py — v2 置信度矩阵（T2.2 从 analyzer/decoder._compute_confidence 原文迁入）

CLAUDE.md 定稿矩阵，7 条规则优先级从高到低。唯一活调用链 = decoder.decode_position
（backtest 历史重放）。与 scoring/reasoner_v3 的 v3 矩阵独立并存、互不替代——
v3 是"删 rule5 的底座 + R1-R4 只降不升"，v2 是回测封板口径。
行为等价由 tests/test_scoring_layer.py 的 7 规则直测 + tests/test_decoder_guards.py 钉死。
"""
from scoring.constants import PNL_HIGH_MAX, PNL_LOW_MIN


def compute_confidence_v2(assembled: dict) -> str:
    """按 CLAUDE.md 定稿置信度矩阵，优先级从高到低判定 high/medium/low。

    重要：pnl_pct 是百分比数值（0.5813 表示 0.5813%），阈值直接用 30 / 60。
    """
    articles      = assembled.get("articles") or []
    time_anchored = bool(assembled.get("time_anchored", False))
    pnl_pct       = assembled.get("pnl_pct")

    # 规则1：articles 为空 → 低（强制，最高优先级）
    if not articles:
        return "low"

    # 规则2：pnl_pct > 60% → 低（涨幅已被吃透）
    if pnl_pct is not None and pnl_pct > PNL_LOW_MIN:
        return "low"

    # 规则3：浮亏 + 新闻未锚定 → 低
    if pnl_pct is not None and pnl_pct < 0 and not time_anchored:
        return "low"

    # 规则4：浮亏 → 封顶中
    if pnl_pct is not None and pnl_pct < 0:
        return "medium"

    # 规则5：新闻未锚定 → 封顶中
    if not time_anchored:
        return "medium"

    # pnl 缺失 → 保守给中
    if pnl_pct is None:
        return "medium"

    # 规则6：0 ≤ pnl_pct < 30 → 高
    if pnl_pct < PNL_HIGH_MAX:
        return "high"

    # 规则7：30 ≤ pnl_pct < 60 → 中
    if pnl_pct < PNL_LOW_MIN:
        return "medium"

    # > 60 已被规则2截走，理论不可达
    return "low"
