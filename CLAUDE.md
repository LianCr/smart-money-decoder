# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目定位

**smart-money-decoder**：输入 Polymarket 交易者钱包地址，找出其最大政治预测盘仓位，结合实时新闻生成 AI 解读卡片。只读 API，不涉及交易或私钥。

## 环境与运行

```bash
# 激活虚拟环境（所有命令都要在这个前缀下跑）
source .venv/bin/activate   # 或直接用 .venv/bin/python

# 安装依赖
.venv/bin/pip install -r requirements.txt

# 跑 mock 测试（无网络，秒出结果）
.venv/bin/python tests/test_position.py
.venv/bin/python tests/test_activity.py

# 跑完整流程（需要真实网络 + API key）
.venv/bin/python verify_activity_news.py
```

## 必填环境变量（.env）

```
TAVILY_API_KEY=...        # 新闻搜索，来自 app.tavily.com
CLASSROOM_API_KEY=...     # 课堂 AI 网关，老师分配，pending 时返回 403
```

## 架构：三层数据层 → 解码层 → 渲染层

```
fetcher/polymarket.py   →  get_top_political_position(address)
fetcher/trades.py       →  get_entry_time_v2(address, condition_id)   ← 首选（按市场查 trades）
fetcher/activity.py     →  get_entry_time(address, condition_id)      ← fallback（翻全活动流）
fetcher/news.py         →  get_news_for_market(market_question, entry_time)
                                    ↓
analyzer/decoder.py     →  decode_position(assembled)
                                    ↓
renderer/card.py        →  render(card, position)                     ← 终端卡片
main.py                 →  CLI 串联入口
api/main.py             →  FastAPI GET /analyze?wallet=               ← Web 后端
frontend/ (Vite+React)  →  单页 App.jsx                               ← Web 前端
```

**数据流**：
1. `polymarket.py` 发 2 次 HTTP（data-api 拿持仓，gamma-api 批量拿 tags），本地过滤出最大政治仓位（>$5,000，tag slug 含 `politics`，未结算）
2. `activity.py` 最多翻 3 页（150 条）activity 记录，本地过滤出目标市场最近一次 BUY TRADE 的时间戳
3. `news.py` 用课堂 AI 网关提取关键词（haiku-4.5），用 Tavily 搜新闻（时间窗：entry_time 前7天后3天），结果缓存在 `.cache/news/`
4. `analyzer/decoder.py`（待建）：调课堂网关 **sonnet-4-6** 生成解读卡片

## 已验证的 API 坑（别重蹈覆辙）

| 坑 | 结论 |
|----|------|
| Gamma events 多值参数 | 必须用 `[("id", id1), ("id", id2)]`，逗号分隔会返回 422 |
| Gamma/Data API category 过滤 | 参数传了被忽略，必须本地按 tag slug 过滤 |
| activity conditionId 过滤 | 服务器端失效，必须拉全量本地过滤 |
| Tavily published_date 格式 | RFC 2822（"Mon, 01 Jun 2026..."），需用 `email.utils.parsedate_to_datetime` 转换 |
| 正确 positions API 地址 | `data-api.polymarket.com`（不是 `gamma-api`） |

## 开发期开关（.env 或环境变量）

```
USE_FAKE_KEYWORDS=true    # news.py：跳过 AI 关键词提取，用占位词（课堂 key 403 时用）
USE_DECODER_CACHE=false   # decoder.py（待建）：默认关，调 prompt 时需要每次看新输出
```

## 异常设计规范

三层数据层各有自定义异常：`PolymarketAPIError` / `ActivityAPIError` / `NewsError`，全部携带 `reason`（机器读枚举）和 `message`（中文人读）。公开入口函数捕获后返回 `{"error": True, "reason": "...", "message": "..."}` 字典，不向上抛。

## 课堂 AI 网关调用方式

```python
# 不用 anthropic SDK，直接 requests.post
resp = requests.post(
    "https://4dm65e698a.execute-api.us-west-2.amazonaws.com/prod/invoke",
    headers={"Content-Type": "application/json", "x-api-key": CLASSROOM_API_KEY},
    json={"model": "claude-sonnet-4-6", "input": prompt, "maxTokens": 2000},
    timeout=15,
)
output = resp.json()["output"]   # 结果在 output 字段，不是 content[0].text
```

关键词提取と AI 解码统一用 `claude-sonnet-4.5`（点号，不是横杠）。网关只开放了 sonnet，haiku 返回 502。关键词提取 maxTokens: 100，解码 maxTokens: 2000。

## 解码层设计（analyzer/decoder.py，待实现）

**输入数据契约（定稿 2026-06-10，基于真实 API 返回核查）**

来自 `get_top_political_position()` 的 position dict：

| 字段 | 类型 | 可空 | 来源 | 用途 |
|------|------|------|------|------|
| `market_question` | str | 否 | positions API `title` | 市场标题，AI 生成"赌的是什么"那句大白话的输入 |
| `outcome` | str | 否 | positions API `outcome`（"Yes"/"No"） | 押注方向 |
| `entry_price` | float | **可 None** | positions API `avgPrice` | 买入均价；**与 `entry_time` 独立**，None 时表示 API 未返回均价，不受 entry_time 影响 |
| `current_price` | float | 否 | positions API `curPrice` | 当前市价 |
| `position_value` | float | 否 | positions API `currentValue`（USDC） | 持仓现值，用于 price_info 渲染 |
| `cash_pnl` | float | 否 | positions API `cashPnl`（USDC） | 现金浮盈，price_info 渲染用 |
| `pnl_pct` | float | 否 | positions API `percentPnl` | **百分比数值，不是小数**。0.5813 = 0.5813%（两钱包三字段算术对账证实：(curr-entry)/entry × 100 ≈ cash_pnl/cost × 100 ≈ pnl_pct）。置信度矩阵阈值直接用 30 / 60 |
| `resolution_criteria` | str | 可 None | Gamma events API `description` | 市场结算规则原文，AI 写 what_bet 时必读，避免胡编规则 |
| `resolution_date` | str | 可 None | Gamma events API `endDate`（ISO 8601） | 结算截止时间，follow_advice 判断"太迟了"用 |
| `market_id` | str | 否 | positions API `conditionId` | 内部 ID，给 activity 模块用，不入卡片 |
| `event_id` / `event_slug` | str | 否 | positions API | 内部 ID，不入卡片 |
| `size` | float | 否 | positions API `size` | 持仓股数，目前不入卡片 |

来自 `get_entry_time()` 的独立返回值：

| 字段 | 类型 | 可空 | 来源 | 用途 |
|------|------|------|------|------|
| `entry_time` | int | **可 None** | activity API trade `timestamp` | Unix 秒级时间戳；None 表示翻页 150 条未找到买入记录（合法降级，下游照常运行） |

来自 `get_news_for_market()` 的 news dict 顶层：

| 字段 | 类型 | 可空 | 来源 | 用途 |
|------|------|------|------|------|
| `articles` | list[dict] | 可空列表 `[]` | Tavily search results | 新闻列表，AI 选 catalyst 的素材 |
| `search_query` | str | 否 | 课堂网关 sonnet-4.5 提取 | 实际用于 Tavily 的关键词，调试/透明展示用 |
| `time_anchored` | bool | 否 | news.py `_build_time_window` | **顶层字段**，True=新闻锁在 entry±时间窗，False=降级到近 30 天；置信度矩阵和 warnings 都用它 |

`articles[i]` 每条新闻对象：

| 字段 | 类型 | 可空 | 来源 | 用途 |
|------|------|------|------|------|
| `title` | str | 否 | Tavily `title` | 催化剂卡片标题 |
| `url` | str | 否 | Tavily `url` | 催化剂卡片可点链接 |
| `published_at` | str | 否 | Tavily `published_date` 转 `"YYYY-MM-DD"` | 催化剂日期；**字段名固定 `published_at`，不是 `date`** |
| `source` | str | 否 | url 域名提取 | 媒体来源（如 `www.reuters.com`） |
| `snippet` | str | 否 | Tavily `content` 截 300 字 | AI 判断这条新闻是否与本次交易有关的依据 |

**输出卡片**：
- `what_bet`：AI 生成，一句大白话
- `catalyst`：AI 从 articles 里选 1-2 条，附 title + url + date
- `price_info`：代码直接填，不经 AI（防幻觉）
- `follow_advice`：AI 生成（还有空间 / 太迟了 / 错过了 + 理由）
- `confidence`：AI 按置信度矩阵判断（高 / 中 / 低）
- `warnings`：代码填，降级原因列表

**置信度矩阵**（优先级从高到低）：

| 条件 | 置信度 |
|------|--------|
| `articles` 为空 | 低（强制） |
| `pnl_pct > 60%` | 低 |
| `pnl_pct < 0%` 且（无新闻或时间未锚定） | 低 |
| `pnl_pct < 0%`（浮亏） | 中（封顶） |
| `time_anchored=False` | 中（封顶） |
| 有新闻 + anchored + `0% ≤ pnl_pct < 30%` | 高 |
| 有新闻 + anchored + `30% ≤ pnl_pct < 60%` | 中 |

**Prompt 硬约束**：新闻为空时禁止 AI 编造催化剂故事，必须如实写"无新闻支撑"。

**算术边界（定稿 2026-06-10）**

模型禁止做的：

- 任何涉及今天/日期的时长推算（"three weeks left"、"in seven months"、"for X more days" 等）。
  原因：契约里没有任何时长字段，叙述里出现"数字+日/周/月/年"必然是模型自算的；
  且日期数学这类计算的盲区是系统性的（模型自认为知道今天），错了用户也难发现。
  代码层用正则 `(one|two|...|twelve|\d+)[\s-]+(more\s+)?(day|week|month|year)s?`
  扫 what_bet / edge_analysis / reasoning / catalyst[i].why_relevant，命中即抛
  `DecoderError("DURATION_COMPUTED")`。

模型允许做的：

- 价格单位换算（`0.105` ↔ `10.5 cents`）。无错的恒等转换，对读者更友好。
- 契约内两个真数的简单比例（"two-thirds of the upside captured"、"about a quarter
  remaining"）。这是 edge 分析的核心价值，且没有日期推算那种系统性盲区。

回测时把这两类输出顺带人工抽查，发现错误率上升再收紧。

## 回测设计备忘

**【路线 A 专用】历史翻页不要复用现有 activity.py**

当前 `get_entry_time()` 翻最近 3 页（150 条）是为正向流程设计的：当下用户输入钱包，找最近建仓。activity API 的记录永存，但回测时反推历史持仓需要按时间段不设上限地翻页（可能要翻几百到几千条），与正向流程的硬性 150 条上限语义完全不同。

**禁止做的事**：把现有 `get_entry_time` 的页数上限调高、或加可选参数让它兼容回测。两个语义会在代码里互相干扰——正向流程的"超出 150 条即如实降级 None"是契约的一部分，被回测共用后会失去明确含义。

**应该做的事**：在 `backtest/` 模块下单独实现 `fetch_full_activity(wallet, start_time, end_time)`，独立的翻页逻辑、独立的边界处理。`fetcher/activity.py` 不动。

## 当前进度（2026-06-12）

**已完成并验证的模块（逐个职责）**：

数据层 / 解码层 / 渲染层（实时解读，全链路真实跑通）：
- `fetcher/polymarket.py`：持仓获取 + 政治过滤 + $5000 阈值。mock 测试全过。
- `fetcher/activity.py`：建仓时间 v1（翻全活动流，150 条上限）。保留为 **fallback**，未改。
- `fetcher/trades.py`【新】：`get_entry_time_v2` 按市场维度查 `/trades?market=&user=`，
  服务器端精确过滤有效，取**最早一笔 BUY**=真实建仓时间。解决老 activity 对 whale
  老仓位命中率低的问题（伊朗/Newsom 老 activity 全 None，v2 均命中）。6 项 mock 测试通过。
- `fetcher/news.py`：关键词提取 + Tavily 时间窗搜索 + 文件缓存。缓存 key 已带时间窗。
- `analyzer/decoder.py`：AI 解码（sonnet-4.5）+ 代码层硬约束守卫。
- `renderer/card.py` / `main.py`：终端卡片（price_info 代码直填）+ CLI 串联
  （`_resolve_entry_time` 三级降级：trades v2 → activity → None）。

Web 后端 / 前端：
- `api/main.py`【新】：FastAPI。`GET /analyze?wallet=` 跑完整 pipeline 返回卡片；
  CORS 放行 3000/5173；错误分层 400/404/500/502；进度打 stdout。
- `api/backtest_mock.py`【新】：`GET /backtest` 的**占位 mock**（3 条手工样本，hit/hit/miss）。
- `frontend/`【新】：Vite+React。`src/App.jsx` 组件化（Card 实时与回测快照共用 /
  DecodeView / LoadingStages 阶段进度 / TrackRecordView 回测页），`src/index.css` 视觉语言。
  两 tab：**Decode（实时解读，数据真实）/ Track Record（历史战绩，真实多钱包数据）**。
  视觉精修已完成（彭博克制 × 交易张力，深色 + cyan 强调 + follow 语义色）。
  **2026-06-13 可读性重构**：①回测列表瘦身——默认行只留 4 元素（Decoder 一句话判断 /
  RESOLVED 真相 / 难度标签 / ✓✗），其余收进抽屉（useRef 量高度 + CSS height 过渡平滑展开），
  T-7→T-1 演变线移入抽屉顶部；②**难度系数**——`/backtest` 读取时按建仓价注入
  `difficulty = 1-|entry_price-0.5|*2`（不碰 pipeline），前端三档：迷雾博弈/倾斜中/近明牌；
  ③**PnL 曲线可读化**——标题 + X 轴起止日期 + Y 轴峰值/当前值($3.13M) + 端点圆点 + 水下红绿分段。
  **动效全 CSS transition，未装 framer-motion（零新依赖）**。计划见
  `~/.claude/plans/radiant-sprouting-music.md`。

**运行 Web 全栈**：
```bash
.venv/bin/uvicorn api.main:app --port 8000     # 后端
cd frontend && npm install && npm run dev       # 前端 → http://localhost:5173
# 前端截图调试：cd frontend && node shot.mjs / shot-track.mjs（产物已 gitignore）
```

**2026-06-11 收官冲刺修掉的几处**：
- ENTRY_PRICE_DENIED 守卫子串误伤（"unknown by date" 良性措辞）→ 改为数值在场即放行。
- DURATION_COMPUTED 与 HARD RULE 4 矛盾 → 改 prompt（日期并列、禁止表述时长）。
- 字段值内裸双引号破坏 JSON → prompt 强制单引号。
- **news 缓存 key 漏带时间窗**（真 bug）→ key 改 `md5(question|start|end)`，否则 entry_time
  变化后会命中旧缓存返回过期 anchored 结果。

**回测 pipeline 已封板（2026-06-13）**：三块砖全部落地，`GET /backtest` 返回**真实回测数据**
（`_mock:false`），前端 Track Record 用真实 decoder 重放结果渲染。
- **最终样本：多钱包聚合 6 个**（伊朗 `Car` 3 个 + Netanyahu 钱包 `ImJustKen` 3 个）：
  方向命中 **5/6**、构成 **4 赢 / 2 输**。最有说服力的是 **Starmer 两个亏损盘**：钱包押"首相下台"
  赌输，decoder 两时点都读到"Starmer 拒辞"、判 `NO BASIS` 不背书 → **系统正确躲过亏损**。
  Powell 一个失手（T-7 CHASED → T-1 NO BASIS）：decoder 正确识别"临时主席"的结算歧义但压错一边。
- **完整复盘固化在 `backtest/final_samples.md`（git 跟踪，防缓存清理）** —— demo 核心素材，
  每样本含两时点 follow_call/confidence/reasoning 原文 + 点评。
- **NO BASIS 成因核查结论**：这 6 样本 12 张卡**没有一个 NO BASIS 是"搜不到新闻"**（全部
  time_anchored + 有 catalyst）。NO BASIS 都是 decoder 读了新闻、对"证据逆向 thesis"主动不背书。
  **demo 要诚实说"它在读新闻做判断"，不是"没信息所以保守"**。语义瑕疵：模型把 `NO BASIS`
  借用来表达"催化剂反对 thesis"（功能对=别跟，但严格说缺个 `FADE` 档）。
- 运行：单钱包 `python -m backtest.pipeline <wallet> <n>`；多钱包聚合
  `python -m backtest.pipeline multi <per_wallet> <total_cap> <w1> <w2>...`（钱包来源：
  `lb-api.polymarket.com/volume` 成交量榜筛政治活跃者）。结果写 `.cache/backtest/result.json`
  （gitignore），`/backtest` 自动读取，无则回退 MOCK。
- **低信心样本就此打住**（decoder 对这批已结算政治盘几乎都给中/高信心，低信心天然稀少，
  硬凑边际收益低）。前端校准块无样本时显示 `—`（非误导性的 `0%`）。

**回测三块砖（均已落地并跑通）**：
- 模块约束（见本文件「回测设计备忘」）：单独 `backtest/` 模块、**不动 `fetcher/activity.py`**。
- **第一块砖已落地**：`backtest/full_activity.py` 的 `fetch_full_activity(wallet, start_time,
  end_time)`——独立翻页（破 150 上限）、时间窗闭区间筛选、老边界提前停，13 项单测通过、
  真实烟测过。历史持仓反推的原料已就绪。
- **第二块砖已落地**：`backtest/resolution.py` 的 `get_market_resolution(condition_id)`——
  conditionId→真实结算结果（获胜方 + 实际结算时间）。16 单测 + 三类真实市场（Yes赢/No赢/
  开放）对账通过。**关键**：gamma 查询必带 `closed=true`（默认不返回已结算市场）。
  T 锚定为 `closedTime`（实际结算），优于 `endDate`（预定）——实测有市场两者差 4 天。
- **第三块砖已落地并跑通**：
  - `backtest/snapshot.py`：`get_price_at(token_id, ts)`——CLOB `prices-history` 取历史价。
    短命市场在 T-7 时未创建会返回 None（上层据此跳过 → 自然筛出时长≥7天的盘）。
  - `backtest/pipeline.py`：`run_backtest(wallet, max_samples)`——翻全活动重建持有侧仓位 →
    每个市场判赢输（持有侧 vs winner，**赢输都纳入**避免只测 REDEEM 全是赢）→ T-7/T-1 取历史价
    → 新闻锚 entry_time（两时点共用）→ 两时点重放 decoder（传 `as_of`=快照日 + 重试）→
    hit=（T-1 背书 == 最终赢）→ 聚合 overview。政治过滤复用 `_is_political_event`
    （gamma `events[0].id` → `/events?id=` 拿 tags，区分体育/政治）。
  - `analyzer/decoder.py`：`decode_position(assembled, as_of=None)`——**已修拦路 bug**。
    历史重放传快照日，模型「今天」对齐 T-7/T-1，不再算诡异时长撞 `DURATION_COMPUTED`。
    默认 None=真实当下，正向流程零影响。
  - `api/main.py` 的 `GET /backtest`：有 `result.json` 读它（`_mock:false`），否则回退 MOCK。
  - **遗留可优化**：① 仍有少数 DURATION 顽固盘重试后跳过，致样本偏少；② 该钱包长线政治盘
    全赢 → composition 全是 win、且常无 low-conf 样本（校准对比偏薄）。想要更丰富数据可调高
    `max_samples`/examined 上限跑更大批次，或换个有亏损样本的钱包。

**回测实探额外结论（2026-06-12，供下一步参考）**：
- CLOB 历史价：`clob.polymarket.com/prices-history?market=<tokenId>&startTs=&endTs=&fidelity=`
  → `{history:[{t,p}]}`。token 即记录里的 `asset` 字段。
- 政治过滤：gamma 市场不带 tags，但 `events[0].id` → `/events?id=` 的 tags 能区分
  （体育=`['sports','soccer']` vs 政治=`['politics','geopolitics']`）。
- **该钱包合格样本（≥7天+有历史价+cost≥1000）实测 10 个全赢、0 输**——长线政治盘确实全中。
  故回测的「失手」案例主要来自「decoder 对赢盘误判 NO BASIS」（✗=该跟却没跟），而非钱包亏损。
  短引信盘（"by June X"）多被 T-7 历史价缺失筛掉，losses 多在其中。

**待解决的硬问题 / 待验证假设（回测 pipeline 的拦路虎，2026-06-12 实探结论）**：
- **「输」的信号在公开接口里缺失**：已结算**赢**的市场有 REDEEM 事件（伊朗实测 84 条 REDEEM），
  但**输**的市场份额归零、无任何事件，且赎回后多从 `/positions` 消失。→ **胜率不可靠**
  （能数到的几乎全是赢，分母缺输，会虚高到 90%+）。**故战绩口径若要真做，应走「净实现盈亏
  （现金流：买入 vs 卖出+赎回）」而非胜率**——亏损单买入收不回，自然拖低净值。
  （注：回测页的「方向命中率」是另一回事——它对照的是 decoder 判断 vs 真实结算，不是钱包盈亏；
  但它同样需要先拿到每个市场的「真实结算结果」，见下条。）
- ✅ **【2026-06-12 已解决】每个历史市场的「真实结算结果」**：gamma
  `/markets?condition_ids=<cid>&closed=true` 可靠返回。**真因不是 conditionId 反查失效，而是
  默认过滤掉已结算市场——必须带 `closed=true`**（此前误判）。读法：`closed:true` 标识已结算；
  `outcomes`/`outcomePrices` 是 **JSON 字符串**需 parse，获胜方 = `outcomePrices` argmax 对应
  outcome（`["0","1"]`→No 赢、`["1","0"]`→Yes 赢）；`closedTime`=实际结算时间（T 锚），
  `endDate`=预定（两者实测可差几小时到几天）。已封装为 `backtest/resolution.py`。
- **历史时点的价格/新闻快照**：T-7/T-1 当时的 current_price、当时窗口的新闻，需要按历史时间点
  取数，正向流程的实时取数不能直接复用。
- 课堂网关已通（claude-sonnet-4.5，点号不是横杠），USE_FAKE_KEYWORDS 可改回 false ✅
- relation 主干道（BEFORE_ENTRY/AFTER_ENTRY）已实战验证（Netanyahu 钱包），但能否打出
  取决于 on-topic 文章是否落在锚定窗内；同名噪音（aliens 移民网站）被 admission 正确剔除。
- **【已诊断为非 Bug，且 v2 已落地】activity.py conditionId 命中率低**（2026-06-10 用 aliens + 伊朗两钱包真实数据核查）

  - **结论**：`positions` 和 `activity` 两个接口的 `conditionId` 字段语义**完全一致**——都是子市场（market）级别的 ID，不是 event 级别。伊朗钱包 positions 的 146 个 conditionId 与 activity 前 150 条 TRADE 的 18 个 conditionId **交集 15 个**，证明同一子市场两边匹配得上；老代码的精确匹配是对的。

  - **真实机制**：一个父 event 下可挂多个子市场（如同一父 event "aliens before 2027" 下挂 "before 2027" / "by September 30" / "by Dec 31" 等），用户可能在多个子市场都交易过，每个子市场都有独立的 conditionId。当持仓的那个具体子市场的**建仓动作不在最近 150 条 activity 内**时（持仓很老，最近交易全在其它子市场），自然找不到匹配。**`entry_time=None` 是正确降级**，比错配安全得多。

  - **反例钉死**：aliens 钱包持有 "before 2027" 子市场 5 万股 No 仓（conditionId `0x747dc8...`），而 activity 前 150 条里有 146 条 TRADE 全部属于**另一个子市场** "by September 30"（conditionId `0xace3c7...`）。两者共享 `eventSlug = will-the-us-confirm-that-aliens-exist-before-2027`。

  - **禁止改用 eventSlug 模糊匹配做"修复"**：会把另一个赌盘（"by September 30" 子市场）的交易时间错配成本仓（"before 2027" 子市场）的建仓时间，污染下游新闻搜索时间窗。**错配比 None 危险一个量级**——None 会触发明确的降级路径，错配会以 time_anchored=True 的假象交给后续模块。这条记在这里防止未来任何人（包括 AI）重新提出该方案。

  - **v2 已落地（2026-06-11）**：`fetcher/trades.py` 的 `get_entry_time_v2` 用 `/trades?market=<conditionId>&user=<wallet>` 按市场维度查，服务器端精确过滤有效（实测伊朗 98 条全命中、Newsom 6 条全命中——后者正是 activity 翻 2000 条都找不到的老仓位）。取最早一笔 BUY。`main.py` / `api/main.py` 均走 trades v2 优先、activity fallback、None 降级。**这是文档原定 v2 方向，未用被禁止的 eventSlug 模糊匹配**——trades 的 conditionId 精确过滤天然不会错配到别的子市场。


"本项目可用命令:/checkpoint —— 整理进度并存档"