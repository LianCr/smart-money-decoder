# frontend/archive — v2 三视图正式存档（P2-16 / CLAUDE.md roadmap 第 1 条）

这里是 v2 时代三个视图的**正式存档形态**：`36d6412` 把导航瘦成 统一看板 + Track Record
后它们就不再被路由；2026-08-03 移到 `src/` 之外，成为明确的存档而非"看起来像活代码的孤儿"。

## 内容（9 个文件，互相成树、与 src/ 零依赖交叉）

- `views/DecodeView.jsx` — 旧「最大仓解读卡」（v2 主形态），打 `GET /analyze`
- `views/BriefingView.jsx` — 完整简报视图，打 `GET /briefing`
- `views/ContextView.jsx` — 市场 Context 视图，打 `GET /market-context`
- `components/` — 只被上述三视图引用的独占组件：
  `Card`(←Decode) · `WalletHeader`(←Card) · `BriefingBody`(←Briefing) · `CatColumn`(←BriefingBody) ·
  `ContextBody`(←Context) · `Timeline`(←ContextBody)

## 为什么存档、不是删

产品决策（CLAUDE.md roadmap）：旧解读卡是产品演进的真实一环（Track Record 的 6 个案例、
记分牌里 source=decode 的历史判断都出自它），代码留作可读的存档。**产品级存档**在
Track Record（案例卡 + 记分牌），这里是**代码级存档**。

## 已知状态（刻意如此）

- **不可构建**：相对 import（`../i18n.jsx`、`../utils/config.js` 等）在本目录下不解析——
  本目录在 Vite 的 import 图之外（入口 `src/main.jsx`，无动态 import/glob），永不进 bundle。
- **后端已不齐**：`/analyze` 路由与其整条链（CLI、fetcher 专属函数）已于 2026-08-03 下架；
  `/briefing`、`/market-context` 路由暂存但无前端消费者。要复活得先看 git 历史把后端找回来。
- 三视图的专属 CSS 规则仍混在 `src/styles/`（05/07/08 分区，与存活规则共享变量/选择器，
  拆动会改构建字节、需视觉回归）——清理归 AUDIT T2.6，不随本次归档。
- `locales/en.js` 里三视图的词条同理保留（错删的代价是静默退中文，风险不对称）。
