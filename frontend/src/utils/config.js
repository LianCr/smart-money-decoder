// Shared config + constants extracted from App.jsx (pure move, no logic change).

// 生产构建走同源（后端托管 dist），本地开发默认打 localhost:8000
export const API = import.meta.env.VITE_API_BASE ?? (import.meta.env.DEV ? "http://localhost:8000" : "");

// 看板轮询预算（P2-22）：🔴 对齐后端单飞锁 TTL（core/dashboard_jobs.py = 10 分钟）——
// 预算内 202/限流都不算失败；改后端 TTL 记得同步这里（两处契约）。
export const POLL_BUDGET_MS = 10 * 60 * 1000;

// 流水线阶段文案（喂给 LoadingStages；STAGES 是其默认参，别删——归档视图的
// STAGES_BRIEFING/STAGES_CONTEXT 已随视图归档，见 frontend/archive/）
export const STAGES = ["定位最大政治仓位", "追溯链上建仓时间", "检索时间窗新闻", "AI 解读 / 置信度矩阵"];
export const STAGES_BOARD = ["身份+体量画像", "这一注+现状", "实时盘面嵌入", "行为流 × 世界催化剂", "Edge 矩阵 + 局势判断"];

// 首页示例钱包（2026-10-30 换大选主题）：取自中期选举盘扫榜（Polymarket 免费 API，AI_TOP=0）。
// pnl = Polymarket 官方 politics 全时盈亏榜（/v2/leaderboard?category=politics&time_period=all）粗粒度快照，
// 作"聪明钱"身份背书、非实时行情。无用户名的钱包如实用缩写地址，不编昵称。
// 🔴 DEMO 前必预热：这三个钱包的看板首次点开要现场构建（~1-2 分钟、烧少量 token），之后走缓存秒回。
export const EXAMPLES = [
  { nick: "0x4488…e319", addr: "0x448861155279dbf833d041b963e3ac854599e319", pnl: "+$1.1M" },   // Michigan Senate · No
  { nick: "Contestable-Parfait", addr: "0xc301c1e034e71e1a6ce9684f029c4674a00466aa", pnl: "+$170K" }, // Balance of Power · adding
  { nick: "wagwanshawty", addr: "0xe5714557d7e870942af0eaed188f1620fa33f17b", pnl: "+$74K" },         // House: Democrats · Yes
];
export const TRADERS_URL = "https://polymarketanalytics.com/traders?tab=Politics&category=Politics";
// 示例大户 + 累计盈利数字的权威来源：Polymarket 官方政治盈利榜
export const LEADERBOARD_URL = "https://polymarket.com/leaderboard/politics/all/profit";
