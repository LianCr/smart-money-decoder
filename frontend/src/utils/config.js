// Shared config + constants extracted from App.jsx (pure move, no logic change).

// 生产构建走同源（后端托管 dist），本地开发默认打 localhost:8000
export const API = import.meta.env.VITE_API_BASE ?? (import.meta.env.DEV ? "http://localhost:8000" : "");

// 各 tab 的流水线阶段文案（喂给 LoadingStages）
export const STAGES = ["定位最大政治仓位", "追溯链上建仓时间", "检索时间窗新闻", "AI 解读 / 置信度矩阵"];
export const STAGES_BRIEFING = ["画像 · 这人靠不靠谱", "动作 · 建仓/对冲/盈亏", "价格 · 空间/赔率", "双向催化剂 + 市场测谎", "第三个 AI 诚实整理"];
export const STAGES_CONTEXT = ["定位顶仓盘面", "扫描价格异动(≤as-of)", "GDELT 三层洗催化剂", "巨鲸 48h 进出动作流", "冷静客观宏观综述"];
export const STAGES_BOARD = ["身份+体量画像", "这一注+现状", "实时盘面嵌入", "行为流 × 世界催化剂", "Edge 矩阵 + 局势判断"];

// 首页示例钱包：地址已正向 /analyze 验证、能产出精彩政治盘卡（2026-06-15 实测）。
// 置信度全谱：ImJustKen=高(Netanyahu) / debased=中(Vance 2028) / denizz=低(+555% 美伊)。
// pnl = 我方系统算的「历史累计盈亏」(pnl_history 末值) 的粗粒度快照，作"聪明钱"身份背书、非实时行情。
// 🔴 DEMO 前必预热体检（CLAUDE.md 已记）：①denizz 的盘 by June 15 当日结算，若 demo 在 6/15 之后已消失，
//    换 aenews2(0x44c1…ebc1) 或退回 Annica(0x689ae…779e)；②顺手核对 pnl 粗粒度是否还对，漂太多就更新。
export const EXAMPLES = [
  { nick: "ImJustKen", addr: "0x9d84ce0306f8551e02efef1680475fc0f1dc1344", pnl: "+$3.1M" },
  { nick: "debased", addr: "0x24c8cf69a0e0a17eee21f69d29752bfa32e823e1", pnl: "+$1.7M" },
  { nick: "denizz", addr: "0xbaa2bcb5439e985ce4ccf815b4700027d1b92c73", pnl: "+$2.6M" },
];
export const TRADERS_URL = "https://polymarketanalytics.com/traders?tab=Politics&category=Politics";
// 示例大户 + 累计盈利数字的权威来源：Polymarket 官方政治盈利榜
export const LEADERBOARD_URL = "https://polymarket.com/leaderboard/politics/all/profit";
