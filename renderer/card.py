"""
renderer/card.py

职责：把 decoder 产出的解读卡片 + 原始 position 数据，渲染成终端可读的卡片。

设计原则：
  - 价格 / 盈亏区块（price_info）直接从 position 取数渲染，**不读 AI 字段**，
    与 CLAUDE.md「price_info 代码直接填，不经 AI（防幻觉）」一致。
  - AI 字段（what_bet / catalyst / edge_analysis / follow_call / confidence /
    reasoning）原样展示，渲染层不二次加工内容，只负责排版与配色。
  - 颜色受 NO_COLOR 环境变量和 isatty 双重控制：管道重定向或显式关闭时退化为纯文本。
"""

import os
import sys
import unicodedata

# ── 配色：仅在 tty 且未设 NO_COLOR 时启用 ─────────────────────────────────────
_COLOR_ON = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _disp_width(text: str) -> int:
    """终端显示宽度：CJK / 全角字符算 2 列，其余算 1 列。"""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def _pad_to(text: str, width: int) -> str:
    """按显示宽度右侧补空格到 width（CJK 安全的 ljust）。"""
    return text + " " * max(0, width - _disp_width(text))


def _c(text: str, code: str) -> str:
    """给文本套 ANSI 颜色；关闭配色时原样返回。"""
    if not _COLOR_ON:
        return text
    return f"\033[{code}m{text}\033[0m"


def _bold(t: str) -> str:  return _c(t, "1")
def _dim(t: str) -> str:   return _c(t, "2")
def _green(t: str) -> str: return _c(t, "32")
def _yellow(t: str) -> str: return _c(t, "33")
def _red(t: str) -> str:   return _c(t, "31")
def _cyan(t: str) -> str:  return _c(t, "36")


# follow_call / confidence 的配色映射
_FOLLOW_COLOR = {"ROOM LEFT": _green, "CHASED": _yellow, "NO BASIS": _red}
_CONF_COLOR   = {"high": _green, "medium": _yellow, "low": _red}
_CONF_LABEL   = {"high": "高", "medium": "中", "low": "低"}
_RELATION_LABEL = {
    "BEFORE_ENTRY": "建仓前 · 疑似触发",
    "AFTER_ENTRY":  "建仓后 · 走势验证",
    "UNANCHORED":   "未锚定 · 仅作背景",
}


def _wrap(text: str, width: int = 64, indent: str = "   ") -> str:
    """
    按词折行（中英混排时按字符也能用），每行前加缩进。
    避免引入 textwrap 对 CJK 宽度的误判——这里按显示宽度粗略折行即可。
    """
    if not text:
        return f"{indent}{_dim('（无内容）')}"
    words = text.split()
    lines, cur = [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width and cur:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return "\n".join(f"{indent}{ln}" for ln in lines)


def _fmt_price(p) -> str:
    """价格（0~1）保留 3 位；None 显示『未知』。"""
    return f"{p:.3f}" if isinstance(p, (int, float)) else _dim("未知")


def _fmt_money(v) -> str:
    """USDC 金额带千分位、带符号（盈亏用）。"""
    if not isinstance(v, (int, float)):
        return _dim("未知")
    return f"${v:,.2f}"


def render(card: dict, position: dict) -> str:
    """
    组装完整卡片字符串。

    参数：
      card     —— decode_position() 返回的解读卡片
      position —— get_top_political_position() 返回的原始仓位 dict
                  （price_info 区块从这里直接取数，不信任 AI）

    返回：可直接 print 的多行字符串。
    """
    W = 68
    out = []

    # ── 顶部标题 ──────────────────────────────────────────────────────────────
    out.append(_cyan("╔" + "═" * W + "╗"))
    title = "SMART MONEY DECODER · 聪明钱解读卡"
    out.append(_cyan("║") + _bold(_pad_to(f"  {title}", W)) + _cyan("║"))
    out.append(_cyan("╚" + "═" * W + "╝"))

    # ── 市场 ──────────────────────────────────────────────────────────────────
    out.append("")
    out.append(_bold("📊 市场"))
    out.append(_wrap(position.get("market_question", ""), width=64))
    res_date = position.get("resolution_date") or ""
    res_date_short = res_date[:10] if res_date else "未知"
    out.append(f"   方向: {_bold(position.get('outcome', '?'))}"
               f"   ·   结算: {res_date_short}")

    # ── 这是在赌什么 ───────────────────────────────────────────────────────────
    out.append("")
    out.append(_bold("🎯 这是在赌什么"))
    out.append(_wrap(card.get("what_bet", "")))

    # ── 催化剂 ─────────────────────────────────────────────────────────────────
    out.append("")
    out.append(_bold("📰 催化剂"))
    catalyst = card.get("catalyst") or []
    if not catalyst:
        out.append(f"   {_dim('未发现可归因的催化剂新闻（如实留空，未编造故事）')}")
    else:
        for i, item in enumerate(catalyst, 1):
            relation = item.get("relation", "")
            rel_label = _RELATION_LABEL.get(relation, relation)
            head = f"   [{i}] {_bold(item.get('title', '').strip())}"
            out.append(head)
            out.append(f"       {_dim(rel_label)} · {item.get('published_at', '')}")
            out.append(_wrap(item.get("why_relevant", ""), width=60, indent="       "))
            out.append(f"       {_cyan(item.get('url', ''))}")

    # ── 价格 / 盈亏（代码直填，不经 AI）────────────────────────────────────────
    out.append("")
    out.append(_bold("💰 价格 / 盈亏") + _dim("  （代码直填，不经 AI）"))
    entry_p = position.get("entry_price")
    curr_p  = position.get("current_price")
    out.append(f"   买入均价: {_fmt_price(entry_p)}       当前市价: {_fmt_price(curr_p)}")
    pos_val = position.get("position_value")
    out.append(f"   持仓价值: {_fmt_money(pos_val)}")
    cash_pnl = position.get("cash_pnl")
    pnl_pct  = position.get("pnl_pct")
    if isinstance(cash_pnl, (int, float)):
        pnl_color = _green if cash_pnl >= 0 else _red
        pct_str = f"{pnl_pct:+.2f}%" if isinstance(pnl_pct, (int, float)) else ""
        sign = "+" if cash_pnl >= 0 else "-"
        out.append(f"   浮动盈亏: {pnl_color(f'{sign}${abs(cash_pnl):,.2f}  {pct_str}')}")

    # ── 边际空间 ───────────────────────────────────────────────────────────────
    out.append("")
    out.append(_bold("⚖️  边际空间"))
    out.append(_wrap(card.get("edge_analysis", "")))

    # ── 跟单建议 + 置信度 ──────────────────────────────────────────────────────
    out.append("")
    follow = card.get("follow_call", "?")
    conf   = card.get("confidence", "?")
    follow_disp = _FOLLOW_COLOR.get(follow, lambda t: t)(_bold(follow))
    conf_disp   = _CONF_COLOR.get(conf, lambda t: t)(_CONF_LABEL.get(conf, conf))
    out.append(_bold("🔮 跟单建议: ") + follow_disp + _dim("   置信度: ") + conf_disp)
    out.append(_wrap(card.get("reasoning", "")))

    # ── 降级提示 ───────────────────────────────────────────────────────────────
    warnings = card.get("warnings") or []
    if warnings:
        out.append("")
        out.append(_yellow("⚠️  降级提示"))
        for w in warnings:
            out.append(_wrap(f"- {w}", width=62))

    out.append("")
    out.append(_dim("─" * (W + 2)))
    out.append(_dim("  仅为公开数据 AI 解读，非投资建议。"))

    return "\n".join(out)
