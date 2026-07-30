// Shared label/localization maps extracted from App.jsx (pure move, no logic change).

export const CONF_LABEL = { high: "HIGH", medium: "MED", low: "LOW" };

// ── v3 统一看板用的中文标签 ──
export const FOLLOW_LABEL_CN = { "ROOM LEFT": "还有空间", CHASED: "已追高", "NO BASIS": "没依据" };
export const CONF_CN = { high: "高", medium: "中", med: "中", low: "低" };

// ⑤ 时间线新闻流 · 市场反应符号（统一口径:持有侧价格前后涨跌,非该新闻导致）
export const REACT_SYM = {
  confirm: { sym: "↑", txt: "印证", cls: "rx-good" },
  reject:  { sym: "↓", txt: "不买账", cls: "rx-bad" },
  weak:    { sym: "·", txt: "微弱", cls: "rx-weak" },
};

// 系统风险标记 → 中文（绝不把内部代码字段直接显示给用户）
export const FLAG_CN = {
  suspicious_win_rate: "异常高胜率", position_size_volatility: "仓位波动大",
  sybil_risk: "疑似女巫账户", perfect_timing: "完美择时(可疑)", perfect_timing_flag: "完美择时(可疑)",
  bot_like: "类机器人模式", concentration_risk: "持仓过度集中", high_drawdown: "高回撤",
  wash_trading: "疑似刷量", low_market_diversity: "市场集中度高",
};

export function flagsCN(raw, t = (s) => s) {
  return String(raw || "").replace(/[{}]/g, "").split(",").map((s) => s.trim())
    .filter(Boolean).map((k) => t(FLAG_CN[k] || k.replace(/_/g, " "))).join("、");
}
