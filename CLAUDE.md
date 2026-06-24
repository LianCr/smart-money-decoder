# CLAUDE.md

给 Claude Code 的操作手册。**只放"开工前必须知道、且读代码看不出来"的东西**：红线、API 坑、协作纪律、关键契约。
项目编年史见 `DEV_LOG.md`；产品演进与 v3 蓝图见 `KNOWN_ISSUES.md`。这三个文件不重复，各管一摊。
测试钱包速查见 `test_wallets.md`（验规则按特征精准挑、别随机拿月榜）；字段留空先按 `empty_field_guide.md` 诊断（先分清"数据真相该留空" vs "bug 该修"，**诚实留空是产品灵魂，别默认把空当 bug 填**）。

---

## 项目定位

**smart-money-decoder**：输入 Polymarket 钱包 → 定位其最大政治预测盘仓位 → 生成**统一看板**：①身份+体量 ②这一注+现状(含 What the bet) ③实时盘面(Polymarket 嵌入) ④巨鲸 48h 行为流 ⑤世界催化剂(GDELT+Tavily+gamma 三源:综述+时间线新闻流) ⑥Edge/Reasoning(置信度矩阵+局势判断)。只读 API，不涉及交易或私钥。
（旧"最大仓解读卡"仍在 Decode tab 存档；统一看板是 v3 收官主形态。）

**产品灵魂（一句话）**：不卖确定性，卖对不确定性的清醒。代码算硬数字、AI 只做软解读、守卫防瞎说；没证据就说"没依据"，从不编造。

---

## 🔴 红线（任何改动都不许越，包括 AI 自己）

1. **绝不为让指标好看而调松 decoder 跟单门槛。** 它的保守是对的——正是"躲过 Starmer 亏损"和 lift 裁决成立的原因。保守反映的是证据的真实缺席，不是可调的阈值。
2. **绝不篡改数字的真实含义。** "命中"≠"翻倍"，"测判断方向"≠"测能赚多少钱"。视觉/文案可以炫，数字含义一个字都不能为了好看而改。
3. **凡涉及"胜率"，先问一句：赢家是不是已经赎回消失了？** 公开接口看不到已离场的赢家（96% 赢家赎回后链上记录消失），自算胜率必被幸存者偏差污染。要用胜率类信号，必须用可信第三方质量评分（如新数据 API 的 Falcon Score），不能用公开 positions 硬算。
4. **信心分由代码算、AI 不准改。** 依据是"这注盈亏状态 + 有无新闻证据"，有专门守卫（CONFIDENCE_TAMPERED）拦截 AI 篡改。
5. **数字/日期数学只能代码做，AI 不准算。** price_delta、空间、时长、日期全由代码预算好喂给 AI。
6. **最大仓 ≠ 最值得看的仓。** 对冲/做市玩家的最大仓是对冲的一条腿，不代表方向信念（R2 已对此降级、`position_type` 已分类）。定位"最大政治仓"是**入口启发式**，不是"最强信念仓"的保证——看 `position_type` 和行为流，别被仓位金额骗。

---

## 🔴 已验证的 API 坑（读代码看不出来，必看）

| 坑 | 结论 |
|----|------|
| activity `conditionId` 服务端过滤 | **失效**，必须拉全量本地过滤 |
| **禁止用 `eventSlug` 匹配交易** | 同一父 event 下多个子市场各有独立 conditionId；用 eventSlug 会把别的子市场的交易时间错配到本仓，污染新闻时间窗。**错配比 None 危险一个量级。**（建仓时间用 `trades.py` 的 `/trades?market=<cid>&user=<wallet>` 精确查，天然不错配） |
| 已结算**输盘**公开接口查不到 | 份额归零、无事件、赎回后从 positions 消失 → 回测样本偏差的总根源。胜率口径会虚高到 90%+，须走"净实现盈亏"而非胜率 |
| Gamma 查已结算市场 | **必带 `closed=true`**（默认不返回已结算市场）；`outcomes`/`outcomePrices` 是 JSON 字符串需 parse；结算时间锚 `closedTime`（实际）非 `endDate`（预定），实测可差几天 |
| Gamma events 多值参数 | 用 `[("id", id1), ("id", id2)]`，逗号分隔返回 422 |
| Gamma/Data category 过滤 | 参数被忽略，必须本地按 tag slug 过滤（政治：`events[0].id` → `/events?id=` 的 tags 区分体育/政治） |
| Tavily `published_date` | RFC 2822 格式，用 `email.utils.parsedate_to_datetime` 转换 |
| positions API 地址 | `data-api.polymarket.com`（不是 gamma-api） |
| CLOB 历史价 | `clob.polymarket.com/prices-history?market=<tokenId>&...`；token=记录里的 `asset` 字段；短命市场 T-7 未创建返回 None |
| **decoder 缓存 key 含 current_price** | 盘中市价漂移会 miss → 单靠它省不了 token。**靠 `/analyze` 外层"(钱包,日期)"缓存兜底** |
| 课堂网关模型 | **只有 `claude-sonnet-4.5`（点号不是横杠）能用，haiku 返回 502**。maxTokens 上限 2048 |
| **[Heisenberg v3] 参数真名因 endpoint 而异** | 官方 context 文档参数名不可靠，**实测真名**：569 PnL=`wallet`（传 proxy_wallet→400）· 556 Trades=`proxy_wallet`（文档写 `wallet_proxy` **被静默忽略→返回全局交易流**，错配比报错危险）· 581 Wallet360=`proxy_wallet` · 579 Leaderboard=`wallet_address`。打之前先核对真名 |
| **[Heisenberg v3] `pagination.limit` 上限 200** | 传 >200（如 500）直接 404 `'max' tag` 校验失败、静默返空——别把它误判成"无数据" |
| **[Heisenberg v3] 569 宽窗口只返回前若干天** | 宽时间窗（如 80 天）只回前 10 天左右，**结算日的亏损落在返回范围外→看着像 0**。要看某盘结算盈亏必须把 start/end **窄锚到结算期**附近分段查 |
| **[Heisenberg v3] 584 H-Score 无按地址 lookup** | 是纯筛选榜，给不了"某钱包排名"。要定位具体钱包官方排名走 **579**（有 `wallet_address`） |
| **[Heisenberg v3] 569 含『持到归零』全损，但 per-cid 归因对超高频 bot 会丢尘埃仓** | 实测 569 完整记录输方归零亏损（23/24 干净单边输方精确到分，`size`=份额，输方=`−Σ(size×price)`、赢方=`Σ(size×(1−price))`，记在结算日）。**唯一边界**：单日结算上千仓的 bot，个别尘埃仓（实测 $0.10）cid-scoped 返 0、但钱包级仍可见。**路 B 算收益率用 `556 Trades + 574 结算结果` 自重建（确定性 payout−cost），569 只交叉校验** |

---

## 🟡 协作纪律（这个项目怎么和 Claude 配合，重要）

这些是这个项目反复验证有效的工作方式，开工默认遵守：

1. **大改先出方案/计划，确认再动手。** 不要看到任务就一口气改一大片。先列"改哪些文件、怎么改"，等拍板。
2. **探不确定的路 = 先验证再构建，先诊断后修复。** 凡"可能有解可能无解"的（新数据源、新方法），先做最小可行性验证拿数字，再决定投不投入。不在没验证的地基上押注。
3. **token 额度紧张 = 任何要烧 token 的操作先估算、先确认。** 课堂 key 是老师的、快烧光。烧 token 前报预算，给 demo / 关键验证留余量。
4. **纯前端改动不准碰** API / 缓存 / 回测数据 / decoder。视觉归视觉，逻辑归逻辑。
5. **不删内容、不粉饰。** "AI 推理"原文、诚实 caveat 是产品诚实性的体现，只能视觉弱化不能删。
6. **诚实优于好看，验证优于假设。** 这是贯穿全项目的元原则。

---

## 环境与运行

```bash
source .venv/bin/activate                      # 或直接用 .venv/bin/python 前缀

# 测试（mock，无网络秒出）
.venv/bin/python tests/test_position.py
.venv/bin/python tests/test_activity.py

# Web 全栈
.venv/bin/uvicorn api.main:app --port 8000     # 后端
cd frontend && npm install && npm run dev       # 前端 → http://localhost:5173
# 前端截图调试：cd frontend && node shot.mjs / shot-track.mjs（产物已 gitignore）

# 回测取样（诊断脚本，零 token 看静态产物即可，一般不用重跑）
python -m backtest._market_lift                 # 路 A lift 取样器（~24min，会烧 token，非必要别跑）
```

**`.env` 必填**：`TAVILY_API_KEY`（app.tavily.com）· `CLASSROOM_API_KEY`（课堂网关，老师分配，pending 时 403）
**开发开关**：`USE_FAKE_KEYWORDS=true`（跳过 AI 关键词，403 时用）· `USE_DECODER_CACHE=false`（调 prompt 时关）

**课堂网关调用**（不用 anthropic SDK，直接 requests.post）：
```python
resp = requests.post(
    "https://4dm65e698a.execute-api.us-west-2.amazonaws.com/prod/invoke",
    headers={"Content-Type": "application/json", "x-api-key": CLASSROOM_API_KEY},
    json={"model": "claude-sonnet-4.5", "input": prompt, "maxTokens": 2000}, timeout=15)
output = resp.json()["output"]   # 结果在 output，不是 content[0].text
```

---

## 架构

```
fetcher/polymarket.py   →  get_top_political_position(address)   # 持仓+政治过滤+$5k
fetcher/trades.py       →  get_entry_time_v2(addr, cid)          # 建仓时间·首选（按市场查 /trades）
fetcher/activity.py     →  get_entry_time(addr, cid)             # 建仓时间·fallback（翻全活动，150 条上限，禁止为回测改它）
fetcher/news.py         →  get_news_for_market(q, entry_time, as_of=None)  # 关键词+Tavily 时间窗+缓存；as_of 防回测泄漏
analyzer/decoder.py     →  decode_position(assembled, as_of=None)         # sonnet-4.5 + 6 道守卫；as_of 时间旅行
renderer/card.py · main.py                                       # 终端卡片 + CLI
api/main.py             →  GET /analyze（v2 解读卡）· /backtest（静态）· /briefing（v3 完整简报）· /market-context（Context 一虚一实）· /dashboard（v3 统一看板①-⑥，整份按(钱包,AS_OF)硬缓存零 token）· /scorecard（诚实记分牌：增量抓 574 结算+冷数字）
fetcher/heisenberg.py   →  Heisenberg 共享客户端（参数真名表/limit≤200/🛡第七道守卫:返回钱包≠请求钱包→拦）
fetcher/profile.py·actions.py·price.py  →  简报数据层 A画像/B动作/C价格（建在 heisenberg 上，全免费 key）
analyzer/dual_catalyst.py  →  双向催化剂辩证（材质标签+守卫；as_of_anchor=锚现在(live)/锚建仓(replay)）
analyzer/price_reaction.py →  新闻↔价格反应=份量刻度+市场测谎仪（复用 price.price_at；归因只说"前后变动非导致"）
analyzer/reasoner_v3.py    →  ⑥ Edge/Reasoning：v3 置信度矩阵(底座删 rule5+R1-R4 只降不升)+reasoner+5 守卫（只读封板输出,不改 decoder v2）
briefing/assemble.py·organize.py  →  A段编排(串数据层+催化剂+测谎)·B段第三个AI诚实整理(只整理不判断)
briefing/market_context.py →  Context「一虚一实」：价格异动≤as-of × GDELT 三层洗催化剂 × 巨鲸 48h 行为流(get_behavior_flags)
briefing/board_feed.py     →  统一看板⑤三源合并(GDELT+Tavily+gamma:综述+时间线流,每条带 dual_catalyst 方向标支持/威胁 + ↑印证/↓不买账符号)+②what_bet（纯组合层,复用 compute_reaction,不改封板模块）
scorecard.py            →  诚实记分牌：record_judgment(钩子,/analyze=decode·/dashboard=board)+fetch_settlements(574注入resolver)+compute_scorecard(纯代码)。档案 .data/scorecard.json(gitignored,装上后累积)
frontend/ (Vite+React)  →  src/App.jsx 单页（统一看板 / Decode 实时 / 完整简报 / 市场Context / Track Record含记分牌）· src/index.css
backtest/               →  独立模块，诊断脚本带 _ 前缀；产物全 git 跟踪、静态、零 token
```
**🔴 简报 AS_OF 数据世界坑**：Heisenberg/gamma 都是 2026 数据世界，`/briefing` 的 `as_of` 用常量 `BRIEFING_AS_OF`（默认 `2026-06-20`）**不能用 wall-clock `date.today()`**（会查错时点价/新闻窗）。切 Bedrock 跑实时数据后再改 today。
**🔴 数据层第七道守卫**：参数名写错→API 返 200 静默返全局流（状态分类抓不到），heisenberg 客户端核对"返回钱包==请求钱包"拦截，加新 endpoint 时别绕过。
**🔴 诚实记分牌三契约**（`scorecard.py`，改它不许越）：① 顶上是「判断方向命中率」，**永不算跟单收益率**（不碰任何 $ 收益）；② NO BASIS **不进命中率**分子分母，单列（+"事后看其实有清晰方向"自审）；③ 顶上冷数字**纯代码算、不调 AI**。档案从装上往后累积、第一天空=正常（**绝不回填造假**）；命中率要等盘真结算才长出来。574 `winning_outcome` 实测=字面 `"Yes"/"No"`。

**实时数据流**：positions（data-api 拿持仓 + gamma 批量拿 tags，本地过滤最大政治仓 >$5k）→ trades v2 拿建仓时间（fallback activity，再 fallback None）→ news（关键词 + Tavily，窗口 entry_time 前7后3，缓存 `.cache/news/`）→ decoder（sonnet-4.5 出卡）。
**关键缓存**：`/analyze` 顶层按 `(小写钱包, 当天日期)` 缓存整条 pipeline 到 `.cache/analyze/<wallet>_<date>.json` → 同钱包当天重复 = 零 token 秒回。**这是 demo 不烧穿额度的命门。**

---

## 解码层契约（analyzer/decoder.py）

**输入**：position dict（来自 `get_top_political_position()`）核心字段——
`market_question`(str) · `outcome`("Yes"/"No") · `entry_price`(float, 可 None，**与 entry_time 独立**) · `current_price` · `position_value` · `cash_pnl` · `pnl_pct`(**百分比数值非小数**，0.58=0.58%，矩阵阈值直接用 30/60) · `resolution_criteria`(可 None，AI 写 what_bet 必读防胡编) · `resolution_date`(可 None) · `market_id`/`event_id`(内部 ID 不入卡)
独立返回 `entry_time`(int Unix 秒, **可 None**=翻页未找到，合法降级)
news dict：`articles`(可空 `[]`) · `search_query` · `time_anchored`(bool，顶层) · 每条 `{title, url, published_at("YYYY-MM-DD"，字段名固定非 date), source, snippet}`

**输出卡片**：`what_bet`(AI 一句话) · `catalyst`(AI 从 articles 选 1-2 条带 title+url+date) · `price_info`(**代码直填防幻觉**) · `follow_advice`(AI：还有空间/太迟了/没依据 + 理由) · `confidence`(AI 按矩阵表达，**不准改**) · `warnings`(代码填降级原因)

**置信度矩阵 v2**（`decoder.py`，`/analyze` 用，代码算，优先级高→低）：articles 空→低(强制) · pnl_pct>60%→低 · pnl_pct<0% 且(无新闻或未锚定)→低 · pnl_pct<0%→中(封顶) · time_anchored=False→中(封顶) · 有新闻+anchored+0≤pnl<30%→高 · 有新闻+anchored+30≤pnl<60%→中

**置信度矩阵 v3**（`reasoner_v3.py`，⑥ 用，与 v2 并存、不替代）：v2 底座**删 rule5**(time_anchored=False→封中,实时场景不再因此降级) → 依次 `R1`(支持侧催化剂被市场反向定价:全背离→低/部分→封中)→`R2`(主仓 shares<另侧×3=对冲/做市→封中)→`R3`(48h 大额退出 clear_exit→封中)→`R4`(支持+威胁证据双空→低)，**逐条只降不升** + 输出**降级原因列表**(喂 ⑥ prompt) + 升级模块预留 no-op(现无升级路径)。`decoder.py` v2 矩阵原封不改。**R1 真实场景罕见**(市场否定钱包多由 R4 兜底,逻辑已零成本证明,不专门猎盘)。

**六道防幻觉守卫**（prompt 引导 + 代码硬拦）：INVALID_FOLLOW_CALL · CONFIDENCE_TAMPERED · FABRICATED_CATALYST · ENTRY_PRICE_DENIED · IRRELEVANT_CATALYST · DURATION_COMPUTED。
**算术边界**：模型禁做任何涉及今天/日期的时长推算（无字段，必是自算，盲区系统性）；允许价格单位换算、契约内两真数的简单比例（edge 分析核心）。
**Prompt 硬约束**：新闻为空时禁止编造催化剂，必须如实写"无新闻支撑"。

---

## 回测（v2 已封板，静态零 token）

`GET /backtest` 读三个 git 跟踪的静态文件渲染，**不重跑、零 token**：
- `backtest/cases.json` → Track Record 6 个案例卡（手填自 `final_samples.md` 诚实 5/6 版）
- `backtest/lift_result.json` → 折叠的 lift 卡（手填自 `lift_v1.md`）
- `backtest/final_samples.md` · `lift_v1.md` → 叙事/数字正本（git 跟踪防缓存清理）

**v2 结论（钉死，详见 KNOWN_ISSUES.md 顶部）**：lift N=94，全集 +10% / edge-band +13%。三层裁决：① decoder「诚实保守不瞎跟」**已验证**（94 盘只 GO 17）；② 「硬盘能否发现可盈利 edge」**测不出但非证伪**（口径喂不饱，非 decoder 没 edge）；③ 救它 = 换「离场盈亏」口径（路 B）= **v3 首要任务**。lift 是一次抽样、会波动（前端已标）。

**回测模块约束**：`backtest/` 独立模块，**禁止为回测改 `fetcher/activity.py`**（正向流程的 150 条降级语义是契约，共用会失去含义）；历史翻页用 `backtest/full_activity.py`。

---

## 🟢 v3 现状 + 下一程 roadmap

**v3 已收官（`v3-briefing` 分支，已 push origin）**：统一看板 ①-⑥ 跑通——身份/这一注(含 what_bet)/实时盘面/巨鲸 48h 行为流/三源催化剂(综述+时间线·带方向标)/⑥ Edge。数据地基(Heisenberg)、完整简报、Context 一虚一实、⑥ v3 置信度矩阵、**诚实记分牌(decode/board 判断自我验证)** 均落地。详见 `DEV_LOG.md`(2026-06-23) + `KNOWN_ISSUES.md` 第八类各愿景 ✅。

**下一程 roadmap**：
1. **Decode → 存档/记分牌**：✅ 记分牌机制已落地(`scorecard.py` + Track Record 顶部)；待办 = 把旧"最大仓解读卡"(Decode tab)正式转成存档形态、不再是主入口。
2. **扫榜推荐主页**：从"用户输钱包"→"系统扫政治盈利榜、主动推荐值得看的钱包/仓位"，主页即推荐流（接愿景 A 看动作 + B 哨兵）。
3. **路 B 离场盈亏 ROI 回测（v3 第一仗，仍开放）**：performance 从"测判断方向"升级为"AI 判 GO 跟入 $1000 平均收益率 vs 无脑全抄基线"。数据已绿灯(569 PnL 实测含全损)、口径已定，**尚未跑全量验收**。

**🟡 待验证假设**：记分牌端到端只在"市场真结算 → 574 填结果 → 命中率长出来"跑通后才算完整闭环；目前格式/数学/UI 三态都验过，但**真实时间推进下的自动填充尚未观察到**（开放盘暂全"待结算"，正常）。下次开工值得回 Track Record 看记分牌是否随数据世界推进自动长出已结算行。

**护城河**：不在数据（谁都能买），在判断（聪明钱行为 + 新闻 + 价格三合一的可信、诚实判断）。完整蓝图在 `KNOWN_ISSUES.md`（第七世界观 / 第八愿景 / 第九数据 API / 第十导师反馈）。

---

*本项目可用命令：`/checkpoint` —— 整理进度并存档。*
*历史编年史在 `DEV_LOG.md`；产品蓝图在 `KNOWN_ISSUES.md`。改这三个文件时保持各管一摊、不重复。*
*测试钱包速查 `test_wallets.md`（验规则按特征精准挑）；字段留空诊断 `empty_field_guide.md`（先分清真相 vs bug，诚实留空是产品灵魂）。*
