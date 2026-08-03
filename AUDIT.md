# AUDIT.md — Smart Money Decoder 全量健康检查

> 首次审计：2026-08-01 · 对象：`36d6412`（当时的 HEAD）
> 方法：逐文件阅读 `api/` `core/` `analyzer/` `fetcher/` `briefing/` `frontend/src/` `tests/`；跑完整测试套件（22/22 绿）；跑 `npm audit`；核对 git 状态与分支拓扑。
> 每条判断附 `文件:行号` 证据。**证据不足以下结论的地方明确标注"证据不足"，不编。**
>
> 🔴 **这是一份活文档，不是一次性报告。** 修完一条就回「零、进度看板」改状态；后来发现的新问题按编号追加（编号永不复用）。
> 行号基于首次审计时的 `36d6412`，重构后会漂移 —— 认编号，别认行号。

---

## 零、进度看板 ← 每次开工先看这里

**怎么用这份文档**：从看板挑一条 ⬜ → 翻到下面对应编号读证据和修复成本 → 做 → 回来把状态改成 ✅ 并填上 PR 号。
**改状态是每个 PR 的收尾动作，和写代码同等重要** —— 状态不更新，下次就又不知道站在哪了。

> 行号会随重构漂移。看板只认「问题编号」，编号永不复用；已修的条目保留在下面不删，方便回看当时的判断。

### P0 — 随时会崩

| 编号 | 问题 | 状态 | 落在哪 |
|:--:|---|:--:|---|
| P0-1 | 记分牌档案可被静默清零 + 全仓非原子写 | ✅ 已修 | PR #10（scorecard + jsonstore 原语）+ PR #14（其余 19 处落盘点全接 + `.data/` 业务读隔离）。尾巴见 P2-25 |
| P0-2 | 生产部署没有可用的 LLM key | ✅ 已修 | PR #9 |
| P0-3 | 服务用 HTTP 调用自己，可耗尽线程池 | ✅ 已修 | PR #18（`services/dashboard_build.py` 纯数据契约 + `recommend.ai_verify` 进程内直调 + anyio 上限显式化；`tests/test_dashboard_build.py` 钉死 8 出口） |
| P0-4 | `frontend/dist` 跟踪状态自相矛盾 | ✅ 已修 | PR #8 |

### P1 — 阻碍迭代

| 编号 | 问题 | 状态 | 备注 |
|:--:|---|:--:|---|
| P1-5 | 六道守卫覆盖 0 个用户可见路径 | ⬜ 未开始 | 审计最重要的发现；属 Phase 2 T2.1。2026-08-03 /analyze 下架后守卫唯一活调用方=backtest 重放（实现原封保留），T2.1 动机更强 |
| P1-6 | 声称的"回验闭环"没有实现 | ⬜ 未开始 | `confidence_log.jsonl` 只写不读 |
| P1-7 | 评分引擎不可复现 | ⬜ 未开始 | Phase 2 T2.2 |
| P1-8 | 核心判断逻辑零测试 | ⬜ 未开始 | Phase 2 T2.4，见「10 个测试点」 |
| P1-9 | "最大政治仓"两套并行实现 | ✅ 已修 | PR #20（随 /analyze 链路下架自然归一：data-api 版删除，唯一实现 = `fetcher/positions.py` Heisenberg 版，near_settled 守卫全覆盖） |
| P1-10 | 缓存失效是手写清单 | ⬜ 未开始 | Phase 2 T2.3 一并解决 |
| P1-11 | `api/main.py` 902 行 god module | ⬜ 未开始 | Phase 2 T2.3 |
| P1-12 | 零日志零监控，健康检查探不到真实健康 | 🟡 **部分完成** | 健康检查 ✅ PR #15（`/healthz` 真探活 + render.yaml 已指向）；日志/监控未动 |
| P1-13 | 无 CI，纪律靠未入库的本地 hook | ✅ 已修 | PR #13（CI 跑与本地同一个 `scripts/check.sh`、不注入 key；Actions 已观察 9 次运行全绿） |
| P1-14 | 前端依赖漏洞（postcss/vite/esbuild） | 🟡 **部分完成** | postcss 两条 high ✅ PR #19（`npm audit fix`，构建产物字节不变）；剩 vite high + esbuild moderate 需 vite@8 主版本 → **T2.7 做，不另开** |
| P1-15 | 烧 token 的端点无入站限流 | ✅ 已修 | PR #19（`core/ratelimit.py` IP 滑动窗口 + 每日 UTC 全局硬闸 → `/dashboard` `/analyze` 429；阈值 `core/config.py` 环境变量可调；「完全开放」产品决策不变） |
| P1-24 | **测试在无 key 环境下 import 就崩** | ✅ 已修 | PR #13（`fetcher/news.py` 惰性 client，干净检出零 key 全绿） |

### P2 — 技术债

| 编号 | 问题 | 状态 |
|:--:|---|:--:|
| P2-16 前端死代码进构建 · P2-17 异常吞噬 · P2-18 魔数散落 · P2-19 Bedrock 半成品 | | P2-16 ✅ PR #20（详情节有前提修正：JS 早已不进 bundle，本场=正式归档进 `frontend/archive/`；CSS 死规则/en.js 死 key 留 T2.6）· 其余 ⬜ |
| P2-20 默认分支不是真相 | | 🟡 已反转，见下 |
| P2-21 seed 入库 · P2-22 轮询状态机 · P2-23 记分牌读路径打外网 | | ⬜ 未开始 |
| P2-25 `backtest/pipeline.py` 结果落盘仍是裸 `write_text`（P0-1 唯一漏网） | | ✅ 已修 PR #19（接 `atomic_write_json`，格式字节不变，`tests/test_backtest_finalize.py` 钉死） |

### 阶段进度

| 阶段 | 完成判据 | 状态 |
|---|---|:--:|
| Phase 1 止血 | P0 全清 | ✅ **P0 全清**（PR #18 收掉最后的 P0-3；T1.5 日志/T1.6 npm audit 两个非 P0 尾巴仍在 P1/P2 表里） |
| Phase 2 结构 | 敢重构（评分层收口 + 核心测试覆盖） | ⬜ 未开始 |
| Phase 3 增值 | 见第三节 F1–F4 | ⬜ 未开始 |

---

## 一、健康评分

| # | 范围 | 评分 | 一句话理由 |
|---|------|:----:|-----------|
| 1 | 架构 | **C-** | 分层命名是清晰的（fetcher/analyzer/briefing/core/api 各管一摊），但 `api/main.py` 902 行是 god module，且"最大政治仓"这一核心概念存在两套并行实现 |
| 2 | API 层 | **C** | 每个出站调用都有 timeout + 分类异常（这点高于同类项目平均水平），但重试只有 Heisenberg 一家有，且服务会用 HTTP 调用自己 |
| 3 | 评分引擎 | **D+** | 两套确定性矩阵确实是纯函数、可单测；但**用户实际看到的 ⑥ 信心是 LLM 直出**，无 temperature/seed、无代码校验，"确定性"只来自文件缓存 |
| 4 | 推荐 pipeline | **C-** | 空榜保护 / 单飞锁 / stale-while-revalidate 三处失败路径设计得很好；但对外宣称的 6 道 guard **当前覆盖 0 个用户可见路径** |
| 5 | 前端 | **C** | 模块化真的做到了（App.jsx 51 行 + 30 个组件 + 16 个样式分区），但 3 个孤儿 view 仍进构建产物、轮询状态机有实缺陷 |
| 6 | 测试 | **D** | 22 个测试全绿、standalone、零网络（纪律确实好），但核心判断逻辑（decoder 六守卫、全部端点、briefing 编排）零覆盖 |
| 7 | 安全与配置 | **C+** | 无密钥入库、地址格式校验、Heisenberg「第七道守卫」是真本事；但 npm 2 high + 1 moderate，且按 Blueprint 部署的生产实例没有可用的 LLM key |
| 8 | 可持续性 | **D** | 零 logging / 零 CI / 零 metrics；JSON 文件当数据库且写入非原子；健康检查探不到真实健康 |

**关于"前端 layout 已知 bug 清单"**：**证据不足**。静态阅读源码 + CSS 无法确认视觉层缺陷，本次未做浏览器视觉回归。下文第五项只列**可静态证明**的前端问题（死代码、状态机缺陷、CSS 覆盖层规模），不臆测布局 bug。

---

## 二、问题清单

> 分级：**P0 = 随时会崩** · **P1 = 阻碍迭代** · **P2 = 技术债**
> 成本：**S** ≤ 0.5 人天 · **M** 1–2 人天 · **L** ≥ 3 人天

---

### P0 — 随时会崩

#### P0-1 · 记分牌档案可被静默清零，且全仓 JSON 写入非原子

> **状态：✅ 已修（PR #10 + PR #14）** —— PR #10 建好 `core/jsonstore.py`（原子写 + 损坏隔离）并接入 `scorecard.py`；PR #14 把其余 19 处落盘点全部换成原子写，并给 `.data/` 业务文件读路径加了损坏隔离（不再静默变空榜）。
> **2026-08-03 复查全仓裸写**：仅剩 5 处直写，逐条判定过——`core/health.py:53`（可写性探针，写失败本身就是探测信号，刻意直写）· `analyzer/market_thesis.py:216`（`confidence_log.jsonl` **append** 模式，原子替换语义不适用，丢一行可接受）· `tools/build_ai_en.py`×2 与 `tools/extract_ai_zh.py`（离线一次性工具，产物 git 跟踪、人工跑失败立刻可见）→ 均不需接。唯一漏网：`backtest/pipeline.py:245`，已记 **P2-25**。

**问题**：`_load()` 在 JSON 解析失败时吞掉异常返回空字典，紧接着 `record_judgment()` 就在这个空字典上写入并 `_save()` 覆盖整个档案；而所有写入都用 `write_text` 直写，没有 tmp+rename。

**证据**：
- `scorecard.py:27-33` — `_load()` 的 `except Exception: return {}`
- `scorecard.py:51-64` — `record_judgment` 在 `_load()` 结果上 `d[key] = {...}` 后 `_save(d)`
- `scorecard.py:36-41` — `_save()` 用 `ARCHIVE.write_text(...)` 直写，且自身 `except Exception: pass`
- 全仓 grep `os.replace` / `.rename(` / `NamedTemporary` → **零命中**，即所有落盘（`.data/scorecard.json`、`.data/recommendations.json`、`.cache/dashboard/*.json`）都是非原子写
- 同样模式：`api/main.py:652-657`（看板缓存）、`recommend.py:348-350`（推荐榜）

**影响**：Render 免费档闲置即休眠、冷启动频繁。进程在 `write_text` 中途被终止 → 半截 JSON → 下一次任何判断把整个档案覆盖成**单条记录**。丢的是产品唯一能回答"我的判断被现实证明对了多少"的资产，而 `scorecard.py:11` 自己写的红线是"**绝不造假回填**"——意味着丢了就永远补不回。这是一条静默的、不可逆的、且与产品灵魂直接冲突的数据丢失路径。

**修复成本**：**S**

---

#### P0-2 · 按 Blueprint 部署的生产实例没有可用的 LLM key

> **状态：✅ 已修（PR #9）** —— `render.yaml` 声明了 `ANTHROPIC_API_KEY` + `GITHUB_TOKEN`，`CLASSROOM_API_KEY` 降级为注明已失效的回落位；`.env.example` 从 2 项补到 5 项。

**问题**：`render.yaml` 声明的 LLM key 是 `CLASSROOM_API_KEY`，而该网关域名项目自己记录已 NXDOMAIN；真正在用的 `ANTHROPIC_API_KEY` 和状态持久层需要的 `GITHUB_TOKEN` 都没在部署蓝图里声明。

**证据**：
- `render.yaml:16-27` — envVars 只有 `PYTHON_VERSION` / `CLASSROOM_API_KEY` / `TAVILY_API_KEY` / `HEISENBERG_API_KEY` / `REDIS_URL`
- `core/llm.py:30-33` — 课堂网关默认 URL；`core/llm.py:13-16` 注释自述"2026-07-08 起默认域名 NXDOMAIN"
- `core/llm.py:61-67` — 无 `ANTHROPIC_API_KEY` 时直接回落到那个死网关，两者皆无才报 `NO_KEY`
- `core/persist.py:37,41-42` — `GITHUB_TOKEN` 缺失时保存端静默跳过
- `.env.example` 全文只有 `TAVILY_API_KEY` 和 `REDIS_URL`两项 —— 5 个实际必需的 key 里缺 3 个（`ANTHROPIC_API_KEY` / `HEISENBERG_API_KEY` / `GITHUB_TOKEN`）

**影响**：一个照着 README/Blueprint 走完流程的全新部署，对任何未缓存钱包都会 `GatewayError` → 502 或降级；同时 GitHub 状态持久层静默不保存，用户刷新出来的推荐榜每次冷启动都穿越回 `seed/` 里的旧快照——这正是 `core/persist.py:4-6` 记录的、本来已经解决过一次的问题会重新出现。对"展示给雇主"这个目标而言，这是一个访客点第一个陌生钱包就会撞上的失败。

**修复成本**：**S**

---

#### P0-3 · 服务用 HTTP 调用自己，可耗尽自身线程池

> **状态：✅ 已修（PR #18）。** `_dashboard_impl` 连同单飞锁抽进 `services/dashboard_build.py`（`build_dashboard` + 单飞入口 `get_dashboard`）；
> 8 个出口收口成**纯数据错误契约**：service 只返 dict、预期失败永不 raise，判别式 = `"error"` key；reason→HTTP 状态码映射是 api 层仅存的 HTTP 知识（`_dashboard_status`），对外行为逐字节不变。
> `recommend.ai_verify` 改进程内直调同一入口（同一把单飞锁，验证线程自己就是构建线程——不再是 5 等待 + 5 构建占 10 个 worker）；anyio 线程池上限顺带显式化（40，数值不变）。
> 契约由 `tests/test_dashboard_build.py` 钉死（8 出口 + 单飞包装 + 成功板无 error key，零网络零 key）；`tests/test_recommend_verify.py` 测试缝从 `recommend.requests` 换成 `recommend.get_dashboard`，语义检查一条没丢。
> 未尽事项：api 层 `_dashboard_status`（6 行查表）暂无法直测——测试禁 import `api.main`（import 副作用），端点层测试仍挂 T2.4 #4，等 T2.3 拆路由后补。

**问题**：扫榜的 AI 验证阶段起 5 个线程，每个用 `requests.get` 打**本进程自己**的 `/dashboard`（timeout 240s）；而 FastAPI 端点全是同步 `def`，跑在 anyio 默认 40 线程的线程池里，每条构建独占一个线程 1–3 分钟。

**证据**：
- `recommend.py:77` — `DASH_URL = f"http://localhost:{os.environ.get('PORT','8000')}/dashboard"`，注释明写"自指本服务"
- `recommend.py:86` — `requests.get(DASH_URL, params=params, timeout=240)`
- `recommend.py:142-143` — `ThreadPoolExecutor(max_workers=min(max_workers, len(targets)))`，`ai_verify` 默认 `max_workers=5`
- `api/main.py:190,323,672,757,789,800,819,875` — **全部端点都是同步 `def`**，无一 `async def`
- `api/main.py:731,747` — `_run_rec_scan` 本身已经在 `RecommendationRefresh` 起的后台线程里（`core/refresh_jobs.py:47`）

**影响**：一次扫榜刷新会让服务对自己发起 5 条并发长请求，每条占用一个线程池 worker 最长 240 秒，叠加真实访客的看板构建。这是典型的"能跑但一改就崩"——单机低负载下看不出来，Render 免费档单实例 + 一个访客同时点刷新就可能级联超时。另外 `recommend.py:88` 的失败提示写的是"后端未在线?"，说明这个自调用的脆弱性已经在实践中被撞到过。

**修复成本**：**M**

---

#### P0-4 · `frontend/dist` 的 git 跟踪状态与 `.gitignore` 自相矛盾（工作区未提交）

> **状态：✅ 已修（PR #8）** —— 3 个构建产物已从索引移除，`frontend/dist/` 进 `.gitignore`；本地文件保留，dev/preview 不受影响。

**问题**：`.gitignore` 已改为忽略 `frontend/dist/`，工作区里 JS 产物已删，但 HEAD 里仍跟踪着一个 `index.html`，它引用的正是那个被删掉的 JS 文件。这半截状态还没提交。

**证据**：
- `git status` → `M .gitignore` · `D frontend/dist/assets/index-Ct0KNBlf.js` · `M frontend/dist/index.html`
- `git show HEAD:frontend/dist/index.html` → `<script type="module" crossorigin src="/assets/index-Ct0KNBlf.js">`
- `.gitignore` 末段 — `frontend/dist/`（该行为本次工作区修改）
- `git ls-files frontend/dist` → 仍列出 3 个文件，即 HEAD 仍跟踪
- `api/main.py:900-902` — 只判断 `_FRONTEND_DIST.exists()`，目录在就 mount，不校验内容完整性

**影响**：如果这个半截状态被提交，任何 `npm run build` 失败的部署都会 mount 一个引用不存在 JS 的 `index.html` = 用户看到白屏，且后端一切正常、健康检查照样 200，排查会很困难。修复本身是 5 分钟的事，但必须作为**一个完整 commit**落地（`git rm -r --cached` + `.gitignore` 同时提交），否则问题只是换个形态存在。

**修复成本**：**S**

---

### P1 — 阻碍迭代

#### P1-5 · 六道守卫当前覆盖 0 个用户可见路径 ← 本次审计最重要的发现

> **2026-08-03 更新（PR #20）**：/analyze 链路已正式下架，`decode_position` 的唯一活调用方变为 `backtest/pipeline.py:126` 的历史重放
> （下面"全仓唯一调用点在 /analyze 内"的证据行在首次审计时就漏了 backtest 这个调用方，特此修正）。
> 六道守卫**实现原封保留在 `analyzer/decoder.py`**——它们现在离用户可见路径更远了，T2.1（抽 `guards.py` 给 ⑥ 复用）的动机因此更强、优先级应前移。

**问题**：项目对外宣称的"6 个输出 guard"全部位于 `analyzer/decoder.py`，只有 `/analyze` 端点会触发；而主界面（统一看板 ⑥）走的是 `market_thesis`，信心由 LLM 直出且代码不做任何校验。最近一次前端重构又把 Decode tab 移出了导航——于是这六道守卫现在一个用户可见路径都覆盖不到。

**证据**：
- `analyzer/decoder.py:286-389` — 六道守卫全部实现于此（`INVALID_FOLLOW_CALL` :288-294 / `CONFIDENCE_TAMPERED` :296-301 / `FABRICATED_CATALYST` :303-309 / `IRRELEVANT_CATALYST` :311-326 / `DURATION_COMPUTED` :328-353 / `ENTRY_PRICE_DENIED` :355-389）
- `api/main.py:250` — `decode_position` 全仓唯一调用点，在 `/analyze` 内
- `api/main.py:589-607` — `/dashboard` 的 ⑥ 由 `build_market_thesis` 直出 `confidence` / `market_lean` / `rationale`，代码只做**枚举归一**（`analyzer/market_thesis.py:263-267`），无任何内容守卫
- `frontend/src/App.jsx:9-10` — 注释"旧 Decode/Briefing/Context 已存档、不再入导航"；`App.jsx:47` 路由只剩 `TrackRecordView` / `BoardView`
- `CLAUDE.md` 红线 4 明写"按产品决策撤掉代码兜底守卫，靠 prompt 铁律 + 结构去 pnl 锚 + 对抗平衡输入"

**影响**：这**不是**要推翻红线 4——"信心不该被代码兜底"的论证是成立的（代码没资格替裁决人改判）。问题在于，撤掉"改信心"这一道的同时，**"不许编造引用"和"不许做日期数学"这两类与红线毫不冲突的守卫也一并缺席了**。`market_thesis.py:34,37` 的 prompt 里写着"只能用给定的真实文章、不许编造；不做任何日期/概率数学"，但这两条铁律在 ⑥ 这条链路上**只有 prompt、没有代码兜底**，而 `decoder.py:328-334` 的注释恰恰记录了同一条 HARD RULE 在 `/analyze` 上"反复被破，加代码兜底"的历史。同一个模型、同一类约束，在旧路径上被证明会破，在新路径上却裸奔。

**修复成本**：**M**

---

#### P1-6 · 声称的"回验闭环"没有实现

**问题**：`confidence_log.jsonl` 只有写入方，全仓没有任何读取方。

**证据**：
- `analyzer/market_thesis.py:28` — `LOG = Path(".data/confidence_log.jsonl")`
- `analyzer/market_thesis.py:211-222` — `_log_confidence()` 追加写
- `analyzer/market_thesis.py:282` — 每次构建调用一次
- 全仓 grep `confidence_log`（`.py` / `.js` / `.jsx`）→ **只有上述 2 处，均在同一文件，均为写**
- `.data/confidence_log.jsonl` 存在于本地，被 `.gitignore` 忽略，无轮转、无上限

**影响**：`CLAUDE.md` 红线 4 的核心论证是"**不加守卫≠不可观测**：每次 confidence/lean/rationale 记进 `.data/confidence_log.jsonl`，待盘真结算由记分牌回验'高信心是否真命中'"。这个论证是撤掉守卫的**正当性来源**，但它目前只有前半句成立。`scorecard.compute_scorecard()`（`scorecard.py:96-138`）确实按 `follow_call` 分组算命中率，但**从不读 confidence_log，也不按 confidence 分档**。所以"高信心是否真命中"这个问题，目前系统答不出来。这是一个诚实性设计上的空洞——不是撒谎，但是一张还没兑现的支票。

**修复成本**：**M**

---

#### P1-7 · 评分引擎不可复现

**问题**：产品展示的信心是 LLM 三连调用的产物，没有 temperature/seed 固定；唯一的"确定性"来自 `(cid, as_of)` 文件缓存，而这个缓存会被强制刷新删掉。

**证据**：
- `analyzer/market_thesis.py:254-261` — `bull` / `bear` / `reasoner` 三次 `_gw()` 调用
- `core/llm.py:78-86` — `_anthropic_body()` 只发 `model` / `max_tokens` / `messages` / `thinking`，**无 `temperature`、无 `top_p`、无 seed 概念**
- `analyzer/market_thesis.py:229-235` — 缓存命中即返回；`analyzer/market_thesis.py:207-208` — key = `f"{cid}_{as_of}.json"`
- `api/main.py:449-474` — `_purge_wallet_caches` 的 targets 包含 `thesis_cache_path(cid, as_of)`，即刷新会删掉它
- 对照组：`analyzer/reasoner_v3.py:41-82` 的 v3 矩阵、`analyzer/decoder.py:57-102` 的 v2 矩阵 —— 这两个**确实是**纯函数、确定性、可复现，且 v3 有测试（`tests/test_reasoner_v3.py`）

**影响**：项目定位里的"确定性置信度评分"在**代码层是真的**（两套矩阵），但在**用户看到的那个数字上不是**。同一个盘、同一天，删掉缓存重跑可能得到不同的 confidence/lean。这不必然是错的设计（对抗式裁决本就需要生成性），但它意味着：① 无法回归测试；② 无法归因"这次信心变了是因为世界变了还是因为采样变了"；③ P1-6 的回验闭环即使接上，也很难分离这两种波动。当前代码里**没有任何地方标注这个非确定性**——`api/main.py:598` 只标了 `confidence_source: "market_thesis"`，没标"非确定性"。

**修复成本**：**M**

---

#### P1-8 · 核心判断逻辑零测试

**问题**：22 个测试全绿，但集中在数据层与协调层；产品的**判断逻辑**几乎全裸。

**证据**：
- `tests/` 22 个文件全部通过（本次实测：`test_activity` / `test_cachefiles` / `test_dashboard_singleflight` / `test_full_activity` / `test_heisenberg_guard` / `test_heisenberg_retry` / `test_llm_backend` / `test_market_thesis` / `test_news` / `test_persist` / `test_position` / `test_positions_near_settled` / `test_precommit_gate` / `test_reasoner_v3` / `test_rec_board_sync` / `test_recommend_verify` / `test_recommendation_refresh` / `test_redis_coord` / `test_resolution` / `test_scorecard` / `test_trades` / `test_translate`）
- grep `decoder|decode_position` 在 `tests/` 下 → **零命中**
- 同样零覆盖：`analyzer/dual_catalyst.py`（398 行，含 4 道自有守卫）、`analyzer/price_reaction.py`、`api/main.py`（902 行，全部端点）、`briefing/assemble.py` · `board_feed.py` · `market_context.py` · `organize.py`、`recommend.scan`（只测了 `_verify_one` 与 `sync_candidates_with_boards`）、`fetcher/{profile,actions,price,social,markets}.py`、`renderer/card.py`、`hot_traders.py`
- `tests/test_market_thesis.py` 只测 `_parse_json` 与 `map_wallet` 两个纯函数

**影响**：`CLAUDE.md` 协作纪律 #1 写的是"**没测试的实现不算完成，不许开下一个 task**"。这条纪律对**新写的**协调层（redis / singleflight / persist / cachefiles）确实执行到位了，但**历史遗留的核心逻辑**（decoder、dual_catalyst、编排层、端点）从来没补过。结果是：最不敢动的正是最该重构的那些文件——`api/main.py` 37 次提交、`analyzer/decoder.py` 11 次提交，churn 最高的地方测试最少。

**修复成本**：**L**

---

#### P1-9 · "最大政治仓"存在两套并行实现

> **状态：✅ 已修（PR #20）。** 按本条自己的结论"该删一个而不是该同步两个"：data-api 版
> （`fetcher/polymarket.py` 的 get_top_political_position 及专属集）随 /analyze 链路下架删除，
> **唯一实现 = `fetcher/positions.py`（Heisenberg 版，带 near_settled 守卫 + 测试）**。
> polymarket.py 只保留 backtest 依赖的 `fetch_events_by_ids` + `_is_political_event`。

**问题**：同一个核心概念有两份独立实现，走不同数据源、有不同的守卫。

**证据**：
- `fetcher/polymarket.py:19` — `MIN_POSITION_VALUE_USD = 5000`；`:175` 过滤；`:216-264` 错误枚举。数据源 = Polymarket data-api
- `fetcher/positions.py:35` — `NEAR_SETTLED_PRICE = 0.95`；`:72-73` 地址校验。数据源 = Heisenberg
- `api/main.py:209` — `/analyze` 用 `get_top_political_position`（前者）
- `api/main.py:335,530,838` — `/market-context` · `/dashboard` · `/briefing` 用 `get_top_political_position_hz`（后者）
- `recommend.py:31,267,297` — 扫榜也用后者

**影响**：`near_settled` 守卫（"不给用户端上 99¢ 无悬念盘"，commit `2df0a64`）只存在于 Heisenberg 那一版；`/analyze` 至今没有。两份实现意味着任何"什么算最大政治仓"的规则变更都要改两处，而只有一处有测试（`tests/test_positions_near_settled.py`、`tests/test_position.py` 各测一边）。考虑到 `/analyze` 已被移出导航（见 P1-5），这更可能是**该删一个**而不是该同步两个。

**修复成本**：**M**

---

#### P1-10 · 缓存失效是手写清单 + 跨模块私有函数 import

**问题**：强制刷新要清哪些缓存，是一个硬编码的 7 元素列表，并且需要从三个模块 import 私有函数（下划线开头）。

**证据**：
- `api/main.py:453-455` — `from briefing.assemble import _cache_path` / `from briefing.market_context import cache_file` / `from analyzer.market_thesis import _cache_path`（三个跨模块 import，两个是私有名）
- `api/main.py:457-465` — 7 条硬编码路径：`DASHBOARD_CACHE` / `BRIEFING_CACHE` / `REASONER_CACHE` / `BOARD_AI_CACHE` / briefing / market_context / market_thesis
- 而缓存层实际有 8+ 处：上述 7 个，加 `.cache/analyze`（`api/main.py:135`）、`.cache/decoder`（`analyzer/decoder.py:26`）、`.cache/event_structure.json`（`analyzer/market_thesis.py:133`）、`.cache/news`

**影响**：新增任何一层缓存而忘记登记到这个列表 = 用户点"强制刷新"后拿到一个半新半旧的板，且**没有任何提示**。这类 bug 极难发现（只在特定组合下表现为"数据看着不对劲"）。私有函数跨模块 import 也让被 import 的模块无法自由重构自己的缓存路径逻辑。

**修复成本**：**M**

---

#### P1-11 · `api/main.py` 是 902 行的 god module

**问题**：HTTP 路由 + 缓存策略 + pipeline 编排 + i18n 挂载 + 记分牌钩子 + 种子恢复 + GitHub 状态恢复 + 静态托管，全在一个文件。

**证据**：
- `api/main.py` 902 行，仓库最大 Python 文件（第二名 `analyzer/decoder.py` 404 行）
- `api/main.py:36-57` — 模块顶层的启动副作用（seed 复制 + GitHub bundle 恢复），在 import 时执行
- `api/main.py:143-162,364-489,704-753` — 三大块业务逻辑（难度系数、缓存策略、状态持久化）夹在路由之间
- `api/main.py:492-665` — `_dashboard_impl` 单函数 174 行
- git churn：`api/main.py` 37 次提交，仅次于 `frontend/src/App.jsx`(52) 和 `frontend/src/index.css`(45)——而后两个**已经被拆过了**（commit `b6d4793` / `7e3d75e`），api/main.py 是同一类问题里唯一没动的

**影响**：`CLAUDE.md` 协作纪律 #7 写着"后端同理——每个模块一摊事，跨了职责就拆"。前端的巨石已经拆完（App.jsx 2210 → 51 行），后端的还在。这是当前最阻碍"敢重构"的单点。

**修复成本**：**L**

---

#### P1-12 · 零日志、零监控，健康检查探不到真实健康

> **状态：🟡 部分完成（PR #15）** —— 健康检查部分已修：`core/health.py` + `GET /healthz` 真探活（必填 key + 目录真写探针），缺必填项返 503，`render.yaml` 的 `healthCheckPath` 已从 `/backtest` 指向 `/healthz`。日志/监控部分未动。

**证据**：
- 全仓 grep `import logging` → **零命中**
- `print()` 计数：`analyzer/dual_catalyst.py` 18 · `briefing/assemble.py` 23 · `analyzer/price_reaction.py` 12 · `fetcher/profile.py` 12 · `recommend.py` 11 · `fetcher/heisenberg.py` 10 · `fetcher/price.py` 8 · `fetcher/actions.py` 7 · `briefing/organize.py` 7 · `api/main.py` 5 · 其余若干，合计 109 处
- `render.yaml:14` — `healthCheckPath: /backtest`
- `api/main.py:165-186` — `/backtest` 只读两个 **git 跟踪的静态 JSON**，且两处读失败都被 `except` 吞掉后照常返回 200

**影响**：无法按级别过滤、无 request id、无结构化字段 → 生产上一个"某钱包出不来板"的报障，只能靠翻 Render 的 stdout 大杂烩。更严重的是健康检查：`/backtest` 读的是仓库里的静态文件，即使 Heisenberg 全挂、LLM key 失效、磁盘只读，它照样 200，Render 认为实例健康。

**修复成本**：**M**

---

#### P1-13 · 无 CI；协作纪律靠一个未入库的本地 hook

> **状态：✅ 已修（PR #13）** —— `.github/workflows/check.yml` + `scripts/check.sh` 入库，CI 跑与本地同一个脚本、刻意不注入任何 key。2026-08-03 已在 Actions 页确认：入库以来 9 次真实运行全绿（含 `npm ci` 与 Python on ubuntu-latest）。

**问题**：`CLAUDE.md` 里写得非常严的 TDD 门禁，在一个新克隆的仓库里**不存在**。

**证据**：
- 无 `.github/` 目录（已确认）
- `git ls-files .claude/` → **空**（`.gitignore` 第 3 条 `.claude/` 忽略整个目录），而 commit gate 的配置正在 `.claude/settings.json` 里
- `git status scripts/` → `?? scripts/check.sh` —— CLAUDE.md 反复引用的"一把梭本地 CI"脚本**未被跟踪**
- `git ls-files scripts/` → 只有 `scripts/precommit_gate.py`（gate 的实现入库了，但触发它的配置没有）
- `.git/hooks/` 下无任何非 sample 钩子 → 这不是 git hook，是 Claude Code 的 PreToolUse hook，**只在 Claude 提交时生效，人手动 `git commit` 不触发**

**影响**：commit `26e97d8`「enforce English commits and green tests via pre-commit gate hook」的成果，实际只对"我用 Claude Code 在这台机器上提交"这一个场景有效。换台机器、换个协作者、或者自己手敲 `git commit`，门禁全部消失。对"展示给雇主"而言，一个没有 CI badge、没有 workflow 文件的仓库，外部看不到任何工程纪律的证据——尽管纪律实际上是存在的。

**修复成本**：**S**

---

#### P1-14 · 前端依赖漏洞（`npm audit` 实测）

> **状态：🟡 部分完成（PR #19）。** postcss 两条 high 已由 `npm audit fix` 清掉（semver 内 lockfile bump，构建产物字节不变）。
> 剩 vite high + esbuild moderate 需要 vite@8 主版本升级——**留到 T2.7**（依赖更新节奏一并建立），不在小修里冒破坏性升级的险。

**证据**（本次实跑 `npm audit`）：

| 包 | 严重度 | 问题 | 影响范围 |
|---|:---:|---|---|
| `postcss` | **high** | 路径遍历，sourceMappingURL 自动加载导致任意 `.map` 文件泄露（GHSA-r28c-9q8g-f849，CVSS 7.5） | `<=8.5.17`，`npm audit fix` 可修 |
| `vite` | **high** | 多条：optimized deps `.map` 路径遍历（GHSA-4w7w-66w2-5vf9）、launch-editor NTLMv2 hash 泄露（GHSA-v6wh-96g9-6wx3） | `<=6.4.2`，需升 `vite@8` 主版本 |
| `esbuild` | moderate | 任意网站可向 dev server 发请求并读响应（GHSA-67mh-4wv8-2f99） | `<=0.24.2`，随 vite 升级 |

汇总：`3 vulnerabilities (1 moderate, 2 high)`。

**影响**：三条都主要作用于**开发时**（dev server / 构建期），生产是静态产物同源托管，实际暴露面有限。但 `frontend/package.json` 里 `vite: ^5.4.11`，距当前主线已隔 3 个大版本——依赖更新节奏为零，这本身比这三条 CVE 更值得注意。

**修复成本**：postcss **S** / vite 主版本 **M**

---

#### P1-15 · 烧 token 的端点无任何入站限流

> **状态：✅ 已修（PR #19）。** `core/ratelimit.py`：每 IP 滑动窗口（默认 30 次/60s）+ 每日 UTC 全局总量硬闸（默认 500，被拒不计数），
> `/dashboard` `/analyze` 超限返 429 + 人话 message + retry_after；阈值收口 `core/config.py`、环境变量可调。
> 「完全开放」产品决策不变——闸拦的是脚本循环，正常浏览（缓存命中为主）够不到；进程内 ai_verify 不经路由、天然不受闸。
> 实现是进程内存（单实例够用；多实例各算各的=闸宽 N 倍，仍是硬顶）。`tests/test_ratelimit.py` 假时钟钉死窗口滑动/IP 隔离/全局闸/翻天。
> 未尽事项：异常流量**告警**仍没有（属 P1-12 日志/监控范畴）；api 层 429 wiring 不可直测同 T2.4 老问题。

**证据**：
- `api/main.py:85-93` — 唯一的 middleware 是 CORS，`allow_headers=["*"]`
- 全仓无 rate limit / 配额 / 鉴权中间件（grep `RateLimit` / `Depends` / `api_key` 在 `api/main.py` → 零命中）
- `api/main.py:672,190` — `/dashboard` / `/analyze` 接受任意 `wallet` 参数
- `CLAUDE.md`：「完全开放模式：陌生钱包/刷新都会真烧 token（产品决策 2026-07-07，用户自担额度）」

**影响**：这是一个**明确的产品决策**，不是疏忽。但"决定开放"和"没有任何闸"是两件事——目前没有速率限制、没有每日配额上限、没有异常流量告警。一个知道 URL 的人可以用一个循环把 Anthropic 额度打空，而系统不会有任何反应（P1-12 说的没监控让这个问题复合）。单飞锁（`api/main.py:668,680`）只防同钱包并发，不防不同钱包的高频遍历。

**修复成本**：**S**（一个基于 IP 的滑动窗口 + 每日总量硬闸即可，不违背"开放"的产品意图）

---

#### P1-24 · 测试在没有 API key 的环境下连 import 都过不去（2026-08-03 补充）

> **状态：✅ 已修（PR #13）** —— `fetcher/news.py` 改惰性 Tavily client（照搬 `dual_catalyst` 的既有写法），缺 key 的失败发生在调用时刻并走该模块既有错误契约；`tests/test_news_no_key.py` 钉死"零 key 可 import"。干净检出（`git archive` + 无 `.env`）零 key 下全部测试绿。

**发现方式**：用 `git archive origin/master | tar -x -C <临时目录>` 做了一次真正的干净检出（无 `.env`、无 `.venv`），清空全部 key 后跑测试套件 —— 因为 `load_dotenv()` 会读本地 `.env`，只靠 `env -u` 清环境变量测不出这个问题。

**问题**：`fetcher/news.py:25-31` 在**模块 import 时**就因缺 key 抛 `RuntimeError`；`:41` 也在 import 时构造 `TavilyClient`。于是 `tests/test_news.py` 与 `tests/test_market_thesis.py`（后者经 `analyzer/dual_catalyst.py:38` 间接 import）在无 key 环境下**连 import 都过不去**，2 个测试直接失败。

**影响**：
- **卡死 CI**：任何不注入 key 的 CI 都会红。而"不注入 key"正是我们想要的 —— 它才能钉死"测试是 mock、零网络、零 token"这条纪律（`CLAUDE.md` 协作纪律 #1）
- 违背同一条纪律的本意：一个新协作者 clone 下来、还没申请到任何 key 时，应该能立刻跑通全部测试
- 属于和 `api/main.py:36-57`（import 时复制 seed 目录 + 打 GitHub 请求）同一类的 **import 时副作用**问题

**现成的正确写法就在同一个代码库里**：`analyzer/dual_catalyst.py:53` 是 `TavilyClient(api_key=KEY) if KEY else None`，调用点 `:114` 判 `None` 后降级。news.py 照搬即可 —— 让失败发生在"真要用 key 的那一刻"，而不是 import 的那一刻。

另：`fetcher/news.py:27-29` 的注释自己就写着 LLM key 那道 import 时校验是多余的（后端选择早已收口在 `core/llm.py`），删掉它与文件原意一致。

**修复成本**：**S**

---

### P2 — 技术债

#### P2-16 · 前端死代码仍进构建产物

> **状态：✅ 已修（PR #20），且标题的前提要修正**：实测 dist 产物 grep 三视图名/独占组件名**全零命中**——
> Vite 的静态 import 图从 `36d6412` 起就不含它们，**JS 从未进过构建产物**（真进产物的是 CSS 16 个无条件
> @import 和 en.js 死 key）。本次做的是「正式存档形态」：三视图 + **6 个**独占组件（下面清单漏了
> CatColumn/Timeline/WalletHeader）移入 `frontend/archive/`（src 之外、天然不可达）+ README 说明；
> `STAGES_BRIEFING/STAGES_CONTEXT` 删除。**另一处更正：`STAGES` 不是孤儿**——LoadingStages.jsx:3 拿它做
> 默认参且被 BoardView 用。CSS 死规则与存活规则混排共享 `--bf-*` 变量（07-briefing 被 7 个分区消费），
> 拆分需视觉回归 → 与 en.js 死 key 一并留给 T2.6。构建验证：归档前后两个 asset hash 逐字节一致。
- `frontend/src/views/DecodeView.jsx`(101 行) · `BriefingView.jsx`(67) · `ContextView.jsx`(68) —— grep 确认**只被自己引用**，`App.jsx:47` 已不再路由到它们
- 连带只被孤儿 view 引用的组件：`Card.jsx`(122) ← 仅 DecodeView · `BriefingBody.jsx`(74) ← 仅 BriefingView · `ContextBody.jsx`(48) ← 仅 ContextView
- `frontend/src/utils/config.js:7-9` — `STAGES` / `STAGES_BRIEFING` / `STAGES_CONTEXT` 三个常量同样只服务孤儿 view
- 影响：bundle 体积 + 阅读时的认知负担（新读者会以为这是活代码）。**注意**：`CLAUDE.md` roadmap 第 1 条说 Decode tab 要"正式转成存档形态"——所以这里正确的动作可能是"明确归档 + 不进 bundle"，而非直接删。

#### P2-17 · 异常吞噬
- `except Exception:` 在 `api/` `core/` `fetcher/` `analyzer/` `briefing/` `recommend.py` 合计 **65 处**，其中 **34 处**紧跟 `pass`
- 典型：`api/main.py:290-291`（缓存写失败）· `api/main.py:395-396` · `api/main.py:472-473` · `scorecard.py:40-41`（存档写失败）
- 影响：大部分是刻意的 best-effort 降级（这是对的），但 `scorecard.py:40-41` 这类**吞掉存档写失败**的地方，与 P0-1 叠加后就是"数据丢了且没人知道"。区分"该吞的"和"该报的"目前没有标准。

#### P2-18 · 魔数散落 6+ 个文件，无中央常量层

完整清单（这些数字共同定义了产品的判断行为，却没有任何一处能一览）：

| 常量 | 值 | 位置 |
|---|---|---|
| 最小仓位门槛 | `5000` USD | `fetcher/polymarket.py:19` |
| 近结算价格线 | `0.95` | `fetcher/positions.py:35` |
| 置信度矩阵阈值 | `30` / `60`（pnl_pct） | `analyzer/decoder.py:72,93,98` + `analyzer/reasoner_v3.py:25,34,36` |
| R2 对冲判定倍数 | `×3` | `analyzer/reasoner_v3.py:64` |
| 市场反应显著阈值 | `5.0` % | `briefing/board_feed.py:22` + `analyzer/price_reaction.py:24` |
| CHASED 判定阈值 | `8` % | `api/main.py:371` |
| 扫榜质量门 | `gate_pnl=2000` | `recommend.py:254` |
| 扫榜打分权重 | `/20000` · `min(roi,40)` · `trades>=50` · `(win-0.5)*20` · `+15` · `+12` · `-40` | `recommend.py:312-320` |
| 社媒有机门槛 | `20.0` % | `fetcher/social.py:13` |
| 泛词剔除率 | `0.35` | `fetcher/social.py:26` |
| 价格可信度 | `85` 百分位 / `80` 人 / `35` % / `30` 人 | `analyzer/market_thesis.py:88-92` |
| 波动分档 | `0.12` / `0.06` | `analyzer/market_thesis.py:127` |
| 多结局判定 | `n >= 3` | `analyzer/market_thesis.py:177` |
| 新闻窗口 | 前 7 后 3 天 / `window_days=10` | `fetcher/news.py` / `analyzer/market_thesis.py:189` |
| 翻译上限 | `2000` / `12000` / `3000` / `500` 条 | `core/translate.py:26-28` + `:第一处 [:500]` |

#### P2-19 · Bedrock 迁移是绕开单一出口的半成品
- `analyzer/dual_catalyst.py:45` — `LLM_BACKEND = os.environ.get("DUAL_CATALYST_BACKEND", "gateway")`
- `analyzer/dual_catalyst.py:46` — `BEDROCK_MODEL = "claude-sonnet-4-6"`，注释"真实 inference-profile id 等账号开好再填"
- `analyzer/dual_catalyst.py:149-151` — `_call_bedrock` 直接 `raise NotImplementedError`
- `analyzer/dual_catalyst.py:158-163` — 后端分支逻辑
- 冲突点：`core/llm.py:1-2` 自述是"LLM 唯一客户端（全项目 AI 调用的单一出口）"，`CLAUDE.md` 架构图也写"全部 AI 调用走 call_gateway，不许再复制"。这个分支在 `dual_catalyst` 里开了第二个出口的口子，且只有一个模块有——真要接 Bedrock，正确位置是 `core/llm.py` 里加第三后端（那里已经有双后端的模式可循，`core/llm.py:58-67`）。

#### P2-20 · 分支拓扑与部署源脱节（2026-08-03 已反转，重新描述）

**审计当时（2026-08-01）**：`master` = `9d2c667`，落后 HEAD 91 个 commit；`render.yaml:9` 部署 `v3-briefing`（== HEAD）。结论是"默认分支不代表产品现状"。

**现在（2026-08-03）方向反了，但问题没消失，反而更危险**：
- `v3-briefing` 已于 PR #7 合进 `master`，`master` 成为真相（0 behind）
- 三个 P0 修复经 PR #8/#9/#10 合入 **master**
- 但 `render.yaml` 仍写 `branch: v3-briefing` → **线上跑的是落后 8 个 commit 的版本，三个 P0 修复一个都没上线**

**为什么比原来严重**：原来只是"clone 的人看到旧代码"，现在是"**合了 PR 却什么都没发生**"，而且没有任何提示 —— 你以为修好了，线上其实没有。

**根因不是哪个分支对，而是"真相分支"和"部署分支"是两个可以各自漂移的东西**。修法是让它们恒等：一个分支既是真相也是部署源，合 PR 即上线。

**状态**：✅ 已修（PR `chore/deploy-from-master`）—— `render.yaml` 改指 `master`，并把这条规则写进文件头注释，防止再长出第二个"真相分支"。

#### P2-21 · `seed/` 缓存快照入库
- `git ls-files seed/` → **250 个文件**，`du -sh seed` → 2.2MB
- 这是刻意设计（`api/main.py:36-44` 冷启动恢复），但随时间只增不减，且 `core/persist.py` 的 GitHub 状态层上线后，seed 的作用已被削弱为"首次冷启动兜底"。

#### P2-22 · 前端轮询状态机脆弱
- `frontend/src/views/BoardView.jsx:24-54` — `run()` 内部**改写自己的入参** `refresh`（:35, :42），同时用 `wantFresh`（:27）影子记录原始意图。两个变量表达同一件事的不同时相，可读性差且易在后续修改时出错
- `BoardView.jsx:30` — `attempt < 80`，配合 `:34` 的 `retry_after || 3` → 轮询上限 **240 秒**
- `core/dashboard_jobs.py:15` — 单飞锁 TTL = **600 秒**
- `BoardView.jsx:134` 前端自己写着"约 1-3 分钟"
- 影响：一次 3 分钟以上的构建，前端会在 240 秒时放弃并显示"看板仍在生成，请稍后重试"（`:50`），而后端还在正常构建。用户看到的是失败，实际是成功——诚实性上是个负分。
- `BoardView.jsx:28` — `setData(null)` 在请求前就清空，刷新期间旧板消失（与后端 stale-while-revalidate 的设计意图相反）

#### P2-23 · 记分牌读路径把外网调用放在请求线程里
- `api/main.py:800-815` — `/scorecard` 每次请求都调 `fetch_settlements(_resolve_574)`
- `scorecard.py:74-93` — 对**每条**未结算记录同步调用一次 resolver
- `api/main.py:802-808` — 每次 resolver 最多打 2 次 Heisenberg（先试 open，再试 `closed=True`）
- 无并发、无缓存、无"这条最近查过就跳过"
- `scorecard.py:74` — 且整个循环持有 `_LOCK`，会阻塞并发的 `record_judgment`
- 影响：档案里 pending 行只增不减（永不清理），`/scorecard` 的响应时间随判断累积**线性变慢**，且慢的部分全在外网 IO 上。

#### P2-25 · `backtest/pipeline.py` 结果落盘仍是裸 `write_text`（2026-08-03 补充，P0-1 收尾复查发现）

> **状态：✅ 已修（PR #19）。** `_finalize` 接 `atomic_write_json`（indent=2 + ensure_ascii=False 与旧格式字节一致，父目录改由原语自动建）；
> `tests/test_backtest_finalize.py` 钉死格式与空样本边界。全仓裸写清零（除 2026-08-03 复查里逐条判定过"刻意直写"的 5 处）。

- `backtest/pipeline.py:245` — `RESULT_PATH.write_text(json.dumps(result, ...))`，全量覆盖写 JSON，未走 `core/jsonstore`
- 是 PR #14「全部 JSON 写原子化」的唯一漏网（当时按运行时业务文件圈的范围，backtest 模块没进 grep 视野）
- 降级理由（所以只记 P2 不记 P0）：产物 git 跟踪、可 `git checkout` 恢复；但重跑一次 ~24min 且烧 token，中途被杀留半截 JSON 仍然疼
- 修法一行：换 `atomic_write_json`。修复成本 **S**

---

## 三、路线图

### Phase 1 · 止血
**目标**：P0 全清，项目"不再随时会崩"。
**预估**：5–7 人天（独立开发者）

| # | 任务 | 依赖 | 量 |
|:--:|---|:--:|:--:|
| **T1.1** | **原子写 + 档案自愈**。新建 `core/jsonstore.py`：`atomic_write_json`（tmp + `os.replace`）+ `load_json` 在解析失败时把原文件改名 `.corrupt` 并**拒绝在空数据上写回**。`scorecard.py` / `recommend.py` / 各缓存写入点全部改用。**先写测试再写实现**（红线 P0-1） | — | S 0.5d |
| **T1.2** | **部署契约修复**。`render.yaml` 补 `ANTHROPIC_API_KEY` + `GITHUB_TOKEN`；`.env.example` 补齐 5 个 key；新增 `/healthz`（校验：LLM key 存在 · Heisenberg key 存在 · `.cache`/`.data` 可写），`healthCheckPath` 改指它 | — | S 0.5d |
| **T1.3** | **dist 状态收口**。`git rm -r --cached frontend/dist` 与 `.gitignore` 改动**同一个 commit** 落地；`api/main.py` 在 dist 缺失时返回明确说明页，而非静默不 mount | — | S 0.25d |
| **T1.4** | **解自调用**。把 `_dashboard_impl` 抽成 `services/dashboard_build.build_dashboard()`；`recommend.ai_verify` 改为直接 import 调用，不再 HTTP 打自己；顺带给 anyio 线程池设显式上限 | T1.2 | M 1.5d |
| **T1.5** | **最小可观测**。`core/log.py` 用 `logging` 替换 109 处 `print`（保留 emoji 前缀，输出格式不变以免影响现有排查习惯），加 request id | — | S 0.5d |
| **T1.6** | `npm audit fix`（修 postcss）；vite 8 主版本升级明确排入 Phase 2，不在止血期做 | — | S 0.25d |
| **T1.7** | **把纪律入库**。提交 `scripts/check.sh`；新建 `.github/workflows/check.yml` 跑同一个脚本；`.gitignore` 改为放行 `.claude/settings.json`（仍忽略 `settings.local.json`） | T1.6 | S 0.5d |

**Definition of Done**
- CI 上 `bash scripts/check.sh` 全绿（测试 22/22 + 前端构建）
- 写档案途中 `kill -9` 后重启，`.data/scorecard.json` 一条记录不丢（有测试证明）
- 一个全新的 Render Blueprint 部署，**不改任何代码**即可对陌生钱包出板
- 扫榜进行中，`/healthz` p95 < 1s（自调用不再占线程池）
- `git status` 干净，`frontend/dist` 不再被跟踪

---

### Phase 2 · 结构
**目标**：架构重整 + 核心逻辑测试覆盖，达到"敢重构"状态。
**预估**：12–18 人天

| # | 任务 | 依赖 | 量 |
|:--:|---|:--:|:--:|
| **T2.1** | **守卫覆盖到主界面**。新建 `analyzer/guards.py`，把六道守卫抽成纯函数（输入：文本 + 契约 → 输出：violations 列表），`decoder` 与 ⑥ 共用。给 ⑥ 至少补三道：`DURATION_COMPUTED`（复用 `decoder.py:335-339` 的正则）· `FABRICATED_CITATION`（rationale 里引用的标题必须在 `shared_pool` 内）· `FEAR_WORDS`（复用 `dual_catalyst.py:61`）。**明确不加"改信心"守卫——红线 4 保持不变** | T1.1 | M 2d |
| **T2.2** | **确定性层收口**。新建 `scoring/` 包：`decoder` v2 矩阵 + `reasoner_v3` + `_code_follow_call`（已在 `services/dashboard_build.py`，PR #18 搬过去的）搬入，成为唯一确定性评分层；P2-18 的全部阈值收进 `scoring/constants.py`（带来源注释）。LLM 裁决保持独立模块，并在 payload 里显式标注 `deterministic: false`。（原计划还要搬 `_difficulty`——它已在 PR #20 作为验证过的死代码删除，不再搬） | T2.1 | M 2d |
| **T2.3** | **拆 `api/main.py`**。→ `api/routes/{dashboard,recommend,scorecard,archive}.py` + `services/` + `core/cachepolicy.py`。缓存失效改为**注册表**：每层缓存注册自己的 key 模板，`purge` 遍历注册表而非手写清单（根治 P1-10）。启动副作用（seed/GitHub 恢复）移出模块顶层，改为 lifespan | T1.4 | L 3d |
| **T2.4** | **补齐 10 个测试点**（明细见下） | T2.2 | L 3d |
| **T2.5** | **回验闭环接上**。`confidence_log.jsonl` 增加读取方；`/scorecard` 输出 high/med/low 分档命中率。**严守 `scorecard.py:6-9` 三条红线**：只算方向不算收益、NO BASIS 单列、纯代码不调 AI | T2.4 | M 2d |
| **T2.6** | **前端死代码 + 状态机**。3 个孤儿 view 及其独占组件明确归档（不进 bundle）；新建 `hooks/useDashboard.js`，把轮询重写为显式状态机（`idle`/`loading`/`polling`/`stale`/`error`），轮询上限对齐单飞锁 TTL，刷新期间保留旧板 | — | M 1.5d |
| **T2.7** | vite 8 升级 + 建立依赖更新节奏（每季度一次 `npm outdated` 复查） | T1.7 | M 1d |

#### 最值得先补的 10 个测试点（T2.4 明细）

按"坏了最疼 × 现在最裸"排序：

1. **decoder 六守卫各自的正/负样本** —— 尤其 `DURATION_COMPUTED` 的**豁免边界**：`decoder.py:332-334` 声称 `published_at`("2026-06-15") 与 `resolution_date_human`("December 31, 2026") 天然不触发正则，这个断言目前**没有任何测试**，而它是六道守卫里最容易误伤的一道
2. **scorecard 数据完整性** —— 损坏 JSON 不得清零（P0-1）· 并发 `record_judgment` 不丢记录（`scorecard.py:23` 的 `_LOCK` 只防线程不防进程）· 已结算条的 `final_result` 不被覆盖（`scorecard.py:61`）
3. **原子写** —— 写入中途抛异常，原文件必须保持完整可读
4. **`/dashboard` 三态路由** —— 缓存命中 / 202 单飞 / 刷新失败回退 stale 且带 `refresh_error`。用 fake 依赖注入，零网络（`tests/test_dashboard_singleflight.py` 已测协调层，缺端点层）
5. **`_purge_wallet_caches` 只删当天** —— `api/main.py:452` 的注释把"旧日期快照永不删 = 失败回退底"标为红线，但这条红线**零测试**。旧快照必须在刷新后幸存
6. **`market_thesis._parse_json` 脏输出矩阵** —— 现有测试覆盖了部分场景，需补**截断 JSON**（`core/llm.py:43-46` 注释说的正是 thinking 挤占 max_tokens 导致截断，这是真实发生过的故障模式）
7. **dual_catalyst 四道守卫** —— 相关性门(`:189-199`) · 类型校验(`:207-219`) · FEAR_WORDS · DIRECTIVE_WORDS。398 行零测试
8. **`translate` 分批不错位** —— `MAX_TOTAL_CHARS` 截断后中英必须仍一一对应；`core/translate.py` 里"长度不齐整批丢弃"是一行判断，一旦失效就是**中英文错配**（比缺翻译危险一个量级）
9. **`recommend.scan` 降级** —— 上游返空时旧榜必须保留（`api/main.py:742-744` 的空榜保护零测试）
10. **`reasoner_v3` "只降不升"改属性测试** —— 现有 `tests/test_reasoner_v3.py` 是样例式；改成随机组合 R1–R4 输入，断言结果恒 ≤ 底座矩阵。这条是 v3 矩阵的**唯一不变量**，值得用属性测试钉死

**Definition of Done**
- CI 绿 + `scoring/` 包分支全覆盖
- 给定同一份 facts JSON，确定性评分层输出 100% 可复现且被测试钉死
- `api/main.py` < 120 行，只剩 app 装配
- 任一模块重构时有测试兜底（= "敢重构"的操作性定义）
- ⑥ 的 payload 里能看到 `deterministic: false` 与 guard violations（如有）

---

### Phase 3 · 增值
**目标**：基于审计中发现的**已有但未被利用**的数据与能力空间，做新 feature。
以下四项的共同特点：**地基已经在仓库里了，缺的只是最后一段。**

#### F1 · 早期进场哨兵（L，≈5 人天）
- **为什么**：`KNOWN_ISSUES.md:192-195`（#27）已经论证过——alpha 主要来自新市场开盘头 2–6 小时的早进场，"解读已有持仓注定慢半拍"，产品目前解读的是"信号的残骸"。`KNOWN_ISSUES.md:240` 更直接："看动作是唯一能在 edge 蒸发前抓到它的形态"。
- **地基已有**：`fetcher/heisenberg.py:36` 的 556 Trades（历史全成交）· `fetcher/markets.get_market_holders`（反向找大户原语，`recommend.py:32` 已在用）· 574 市场列表（`analyzer/market_thesis.py:151` 已用它扫过全量未结算市场）
- **缺的**：一个"新政治盘上线 → 首批大额买入 → 谁在买"的轮询 + 通知面
- **价值**：这是产品从"事后解读"变成"实时信号"的唯一路径，也是护城河论述里"看动作"愿景的落地。

#### F2 · 信心校准曲线（M，≈2 人天）
- **为什么**：T2.5 一旦让 `confidence_log` 有了读取方，就能画出 high/med/low 三档的**实际命中率**。这个图表回答的是"我说高信心的时候，我到底有多准"。
- **为什么值钱**：绝大多数 AI 产品拿不出这张图——因为它们不敢存档、或存了不敢公布。这个项目的红线体系（存档不回填、命中率只算方向、NO BASIS 单列）恰好让它**有资格**画这张图。对雇主而言这是最直观的"这人懂什么叫诚实的 AI 产品"的证据。
- **前置**：T2.5

#### F3 · 同盘分歧独立面板（M，≈2 人天）
- **为什么**：`recommend.py:146-161` 的 `_mark_disagreements` 和 `:163-174` 的 `_mark_consensus` **已经在算了**，但产出只做成了推荐卡上的一个角标。而 `recommend.py:148` 的注释自己写着"这本身是高价值诚实信号——'聪明钱不是共识'"。
- **缺的**：把它从角标提升为独立视图——"这些盘上，被验证过的聪明钱正在互相对赌"。
- **价值**：几乎零新增数据成本（纯代码，已在算），但它展示的是一个反直觉的、其他工具不说的事实。

#### F4 · 输入可信度升为一等公民（M，≈2 人天）
- **为什么**：`analyzer/market_thesis.py:71-105` 的 `price_credibility`（575：流动性百分位/鲸控/参与人数）和 `:108-129` 的 `realized_vol`（568：市场自身犹豫度）都是**纯代码算出来的硬指标**，但目前只被拼成文本喂给 prompt（`:250-252`），算完就扔——`api/main.py:605` 虽然带回了 `input_trust.lines`，但只是那几行文本。
- **缺的**：把它做成"**这个盘的价格值不值得信**"的独立展示，并作为确定性信号进 `scoring/` 层。
- **价值**：这是少见的"代码能硬算、AI 不参与、且用户看得懂"的判断维度——完全符合红线 5（数字归代码），且能独立于 LLM 的非确定性存在。

---

## 四、一句话结论

这个项目的**判断力已经过验证、诚实性设计本身就是护城河**——它离"可持续的严肃产品"差的不是想法，而是**一层敢让人动手的地基**：判断存档会被静默清零、宣称的六道守卫覆盖不到任何一个用户可见路径、核心判断逻辑零测试；把"诚实"从写在 CLAUDE.md 里的原则，变成代码里被测试钉死的契约，它就成立了。

> **2026-08-03 进展**：上面三条里的第一条已经不成立了 —— 判断存档现在有原子写和损坏隔离兜底（P0-1，PR #10）。
> 后两条仍然成立，且仍是这句结论的重心：**守卫覆盖不到用户可见路径（P1-5）、核心判断逻辑零测试（P1-8）**。
> 这句结论修完剩下两条才算作废，在那之前它就是路线图的北极星。

---

*首次审计（2026-08-01）只做诊断、未改任何代码。此后本文件转为**活文档**：随修复推进更新「零、进度看板」与各条目状态，新发现按编号追加。*
*所有行号基于首次审计时的 `36d6412`，重构后会漂移 —— 认编号，别认行号。*
