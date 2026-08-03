# CLAUDE.md

给 Claude Code 的操作手册。**只放"开工前必须知道、且读代码看不出来"的东西**：红线、API 坑、协作纪律、关键契约。
项目编年史见 `DEV_LOG.md`；产品演进与 v3 蓝图见 `KNOWN_ISSUES.md`。这三个文件不重复，各管一摊。
**🔴 工程健康度与"我做到哪了"看 `AUDIT.md`**（2026-08-01 全量审计产出，**活文档**）：顶部「零、进度看板」列全部 24 条问题 + 状态 + 落在哪个 PR。
**开工第一件事 = 看那张看板挑一条；收工最后一件事 = 回去把状态改掉。** 不改状态，下次就又不知道站在哪了（这是实践中真栽过的坑）。
分工：`KNOWN_ISSUES.md` 管**产品该往哪走**，`AUDIT.md` 管**工程地基还缺什么**，两者不重复。
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
4. **信心 = 市场命题级、单一、不锚钱包盈亏。** （2026-06-25 重设计，推翻旧"信心由代码矩阵算"）旧矩阵锚在钱包 pnl → 出现"证据反对这一注、却因 +10% 浮盈给高信心"（实证见 `_market_thesis_probe`：同一 Iran 盘两个反向钱包，老矩阵给 HIGH/MEDIUM 自相矛盾）。**新**：`analyzer/market_thesis.py` 把参照系从钱包换成市场——同一文章池 bull 论证 YES ‖ bear 论证 NO → reasoner 中立裁决，**直出单一最终信心**（按产品决策撤掉代码兜底守卫，靠 prompt 铁律 + 结构去 pnl 锚 + 对抗平衡输入）。按 (cid,as_of) 缓存→两个反向钱包共享同一份市场观、信心一致，差异挪到"顺/逆 edge"。**不加守卫≠不可观测**：每次 confidence/lean/rationale 记进 `.data/confidence_log.jsonl`，待盘真结算由记分牌回验"高信心是否真命中"。社媒只作减分/背离，不许加信心。（旧 decoder v2 矩阵 `/analyze` 仍在用、reasoner_v3 仍供 follow_call+代码 facts；dashboard ⑥ 的**信心**已切到 market_thesis。）
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
| 课堂网关模型（旧后端） | **只有 `claude-sonnet-4.5`（点号不是横杠）能用，haiku 返回 502**。maxTokens 上限 2048。官方 API 后端无此限制（模型 id 是横杠 `claude-sonnet-4-5`） |
| **[Heisenberg v3] 参数真名因 endpoint 而异** | 官方 context 文档参数名不可靠，**实测真名**：569 PnL=`wallet`（传 proxy_wallet→400）· 556 Trades=`proxy_wallet`（文档写 `wallet_proxy` **被静默忽略→返回全局交易流**，错配比报错危险）· 581 Wallet360=`proxy_wallet` · 579 Leaderboard=`wallet_address`。打之前先核对真名 |
| **[Heisenberg v3] `pagination.limit` 上限 200** | 传 >200（如 500）直接 404 `'max' tag` 校验失败、静默返空——别把它误判成"无数据" |
| **[Heisenberg v3] 569 宽窗口只返回前若干天** | 宽时间窗（如 80 天）只回前 10 天左右，**结算日的亏损落在返回范围外→看着像 0**。要看某盘结算盈亏必须把 start/end **窄锚到结算期**附近分段查 |
| **[Heisenberg v3] 584 H-Score 无按地址 lookup** | 是纯筛选榜，给不了"某钱包排名"。要定位具体钱包官方排名走 **579**（有 `wallet_address`） |
| **[Heisenberg v3] 569 含『持到归零』全损，但 per-cid 归因对超高频 bot 会丢尘埃仓** | 实测 569 完整记录输方归零亏损（23/24 干净单边输方精确到分，`size`=份额，输方=`−Σ(size×price)`、赢方=`Σ(size×(1−price))`，记在结算日）。**唯一边界**：单日结算上千仓的 bot，个别尘埃仓（实测 $0.10）cid-scoped 返 0、但钱包级仍可见。**路 B 算收益率用 `556 Trades + 574 结算结果` 自重建（确定性 payout−cost），569 只交叉校验** |

---

## 🟡 协作纪律（这个项目怎么和 Claude 配合，重要）

这些是这个项目反复验证有效的工作方式，开工默认遵守。
**元原则：这不是 vibe coding。** 按生产级标准要求自己和任何协作 agent——task 的能力/边界/定义/方法要尽量定义干净，**tests 定义边界，roadmap（`KNOWN_ISSUES.md`）定义方向**。

**工作流铁律（每个垂直 task 开工前 → 完成后）**

1. **测试先行（TDD）：先写测试把契约钉死，再写实现。** 动手实现前，先写测试定义这个 task 的输入/输出/边界/降级。测试 follow `tests/` 惯例——standalone 可跑、`def check(name, got, want)` + `sys.exit(1 if failed else 0)`、in-file fake 不打网络、纳入 `scripts/check.sh`（无 pytest，就这一套）。
   **🔴 测试必须能在"零 API key + 没有 .env"的机器上跑通**——CI 就是这么跑的（`.github/workflows/check.yml` 刻意不注入任何 key），这把"测试是 mock、零网络、零 token、谁 clone 都能跑"从口号变成机器可验证的事实。
   推论：**任何模块都不许在 import 时因缺 key 抛错**（真栽过：`fetcher/news.py` 曾在模块顶层 `raise RuntimeError`，导致 2 个测试连 import 都过不去）。缺 key 该让**用到它的那次调用**失败，走该模块既有的错误契约。惰性 client 写法参考 `fetcher/news.py` / `analyzer/dual_catalyst.py`。
   自测干净环境：`git archive HEAD | tar -x -C <临时目录>` 后清空 key 再跑——**只清环境变量测不出来**，`load_dotenv()` 会把 `.env` 读回来。**"完成"的唯一定义 = 该 task 的测试全绿 + 你亲自 review 过测试确实覆盖了契约（而非"碰巧能跑"）。没测试的实现不算完成，不许开下一个 task。** 测试是 mock 零 token——多写不心疼。
2. **动手前把 task 定义干净。** 一句话写清这个垂直 task 的：能力(capability)、边界(boundary)、完成判据(definition)、方法(method)。定义不清先问、别猜着开工。
3. **大改先出方案/计划，确认再动手。** 先列"改哪些文件、怎么改、怎么测"，等拍板。不要看到任务就一口气改一大片。
4. **探不确定的路 = 先验证再构建，先诊断后修复。** 凡"可能有解可能无解"的（新数据源、新方法），先做最小可行性验证拿数字，再决定投不投入。不在没验证的地基上押注。

**预防式协作 / 对抗式 review（怎么和其他 agent、和上游产出配合）**

5. **默认别人都是错的。** multi-agent 最有效的形态是**互相 challenge、预防式合作、预防式管理、预防式 review**——不是 1000 个 agent 包饺子、大团圆、无休止闲聊。接手任何上游产出（别的 agent 的输出、上一个 task、codex 的改动、"看起来能跑"的代码）前：先假设它是错的 → 自己 review 一遍 → 在自己手里写足够多测试验证它真完成了契约 → **验不过就直接拒绝接手，绝不在未验证的地基上继续。**
6. **token 额度紧张 = 任何要烧 token 的操作先估算、先确认。** 烧 token 前报预算，给 demo / 关键验证留余量。

**代码与产品纪律**

7. **代码守最佳实践：单一职责、模块化，别堆积。** `frontend/src/App.jsx` 已从 2210 行拆成 **`components/`(30 个) + `views/`(5 个) + `utils/`**（App.jsx 现 ~69 行，仅根组件 + tab 路由；commit `b6d4793`，单一职责一文件一组件）。**新增/重构 UI 一律进 `frontend/src/components/`·`views/`·`hooks/`·`utils/`，禁止回堆 App.jsx。** `index.css` 也已按区拆成 `frontend/src/styles/`（16 文件 + `index.css` 作 `@import` 清单，**保序=构建 CSS 字节一致**；commit `7e3d75e`）——改样式进对应区文件、别动 @import 顺序（顺序里含刻意的后置覆盖）。后端同理——每个模块一摊事，跨了职责就拆。
8. **纯前端（视觉）改动不准碰** API / 缓存 / 回测数据 / decoder 逻辑。视觉归视觉，逻辑归逻辑。（把巨石文件拆成组件属重构、不算逻辑改动；但一旦动了逻辑就按逻辑改动走 TDD。）
9. **垂直 task 完成即英文 commit。** 见 `AGENTS.md`（该规则的正本）：每个可独立测试的垂直 task 一旦完成并验证，**立即用英文单独 commit**——不攒、不把多个 task 混进一个 commit、不夹带无关改动；完成的活没 commit 不许开下一个 task。
10. **不删内容、不粉饰。** "AI 推理"原文、诚实 caveat 是产品诚实性的体现，只能视觉弱化不能删。
11. **诚实优于好看，验证优于假设。** 这是贯穿全项目的元原则。

---

## 环境与运行

```bash
source .venv/bin/activate                      # 或直接用 .venv/bin/python 前缀

# 测试（mock，无网络秒出；tests/ 下全部可单跑）—— TDD 门禁，改动前后都要绿
for t in tests/test_*.py; do .venv/bin/python "$t"; done
bash scripts/check.sh                            # 一把梭：跑全测试 + 前端构建校验
# 🔴 scripts/check.sh 就是 CI 跑的那个脚本（.github/workflows/check.yml），本地绿=CI 绿，不维护两套清单
# 覆盖：老地基(position/activity/trades/news/backtest) + 核心新逻辑(scorecard 命中率数学/
# market_thesis 解析守卫/heisenberg 第七道守卫/v3 矩阵只降不升) + 工程地基(jsonstore 原子写与
# 损坏隔离/无 key 可 import/业务文件读隔离/health 探活)

# Web 全栈
.venv/bin/uvicorn api.main:app --port 8000     # 后端
cd frontend && npm install && npm run dev       # 前端 → http://localhost:5173
# 前端截图调试：cd frontend && node shot.mjs / shot-track.mjs（产物已 gitignore）

# 回测取样（诊断脚本，零 token 看静态产物即可，一般不用重跑）
python -m backtest._market_lift                 # 路 A lift 取样器（~24min，会烧 token，非必要别跑）
```

**`.env` 必填三项**（与 `render.yaml`、`.env.example`、`core/health.py` 三处严格一致，**契约只有一份，改一处要改四处**）：
`ANTHROPIC_API_KEY`（官方 API，console.anthropic.com，自己的 key）· `TAVILY_API_KEY`（app.tavily.com）· `HEISENBERG_API_KEY`（免费，整个数据层靠它）。
**可选**：`GITHUB_TOKEN`（状态持久层，不填则刷新的榜冷启动后退回 seed）· `REDIS_URL`（跨实例协调，不填自动回退进程内单飞）。
`CLASSROOM_API_KEY` 为旧课堂网关回落位（**2026-07-08 起域名 NXDOMAIN 已失效**，有 ANTHROPIC_API_KEY 就无需填）。
**自检**：`GET /healthz` —— 必填 key 齐不齐 + 缓存目录写不写得动，缺必填项返回 **503**（判定口径在 `core/health.py`，改口径记得同步 render.yaml 注释）。⏳ 该端点在 `feat/healthz` 分支，**合并后才可用**。
**开发开关**：`USE_FAKE_KEYWORDS=true`（跳过 AI 关键词，403 时用）· `USE_DECODER_CACHE=false`（调 prompt 时关）

**部署（Render 免费档）**：`render.yaml` Blueprint 一键部署——FastAPI 同源托管 `frontend/dist`（生产前端 `API=""`，本地 dev 仍打 8000）。
🔴 **部署分支 = `master`，合了 PR 就是上线**（2026-08-03 收口）。`v3-briefing` 已合进 master 并退役，**别再新增长期分支当"真相"**——曾出现"PR 合进 master 但线上仍跑 v3-briefing、三个 P0 修复一个没上线"且毫无提示。健康检查已从 `/backtest`（读静态文件，全挂也返 200）改成 `/healthz`。
`frontend/dist` **不再入库**（每次部署 `npm run build` 重生成）；本地要看前端先 build。`seed/` 是 git 跟踪的缓存快照（~2.2MB），云端磁盘 ephemeral、每次冷启动由 api/main.py 自动恢复 → 已缓存钱包零 token 秒回；**☁️ GitHub 状态持久层（core/persist.py，2026-07-09）**：扫榜成功后把 推荐榜+精选看板缓存+记分牌 打成 bundle 存 **`app-state` 分支**（非部署分支不触发重部署；保存需 Render 环境变量 `GITHUB_TOKEN`=fine-grained PAT 仅本仓库 Contents 读写），冷启动 seed 恢复后再从 raw 拉 bundle **谁新用谁**（恢复端无需 token）→ 用户刷新的榜跨部署/冷启动持久，不再穿越回 seed 快照；`GET /demo-wallets` 给入口页"秒开"列表。**`/dashboard?refresh=1` = 在今天强制重建**（真·实时；只删"今天"key 的各层缓存含共享 market_thesis，**旧日期快照永不删=失败回退底**，烧 token；前端看板右上 ↻ 按钮带确认框，失败回旧板+refresh_error 横幅）；`fresh=1`（扫榜 ai_verify 用）=要今天的数据但今天已有缓存不重烧。完全开放模式：陌生钱包/刷新都会真烧 token（产品决策 2026-07-07，用户自担额度）。**i18n**：前端 `src/i18n.jsx` 中文原文即 key，EN 四层查表：UI 词典 `locales/en.js` → **运行时词典**（2026-07-08 起的正解：后端构建看板/简报/推荐时 `core/translate.py` 把 AI 中文批量翻好、payload 带 `i18n_en` 映射随缓存持久化，前端 fetch 后 `registerAiTranslations()` 注册，~$0.01-0.03/构建、命中零成本；7-08 后缺翻译的缓存命中时懒自愈回写）→ 离线词典 `ai_en.js`（6-25 冻结世界的历史兜底）→ 模式引擎；全 miss 回退中文+ZhNote 诚实标注（现仅翻译调用失败时出现）；右上 中|EN 胶囊。

**LLM 调用（core/llm.py 双后端，全部走 `call_gateway`，不用 SDK 直接 requests.post）**：
有 `ANTHROPIC_API_KEY` → 官方 `https://api.anthropic.com/v1/messages`（headers 带 `x-api-key` + `anthropic-version: 2023-06-01`；模型 **`claude-sonnet-5`**（2026-07-08 升级，推广价 $2/$10 至 2026-08-31 比 sonnet-4-5 还便宜、指令遵循更强）；🔴 **thinking 显式 `{"type":"disabled"}`**——Sonnet 5 不传会默认开自适应思考、挤占 max_tokens(最大才2000)截断 JSON 炸解析器；`ANTHROPIC_MODEL`/`ANTHROPIC_THINKING` 环境变量可覆盖（开思考须同时加大调用点 max_tokens）；文本在 `content[]` 的 text 块）；否则回落课堂网关（`CLASSROOM_API_KEY`，**2026-07-08 起默认域名 NXDOMAIN**，坑：模型名 `claude-sonnet-4.5` 点号、maxTokens≤2048、结果在 `["output"]`）。错误分类两后端共用：NO_KEY/TIMEOUT/UNREACHABLE/RATE_LIMITED(含 529)/HTTP_ERROR。

---

## 架构

```
core/llm.py             →  🔴 LLM 唯一客户端·双后端（ANTHROPIC_API_KEY→官方 API / 回落课堂网关；URL/model/错误分类一处定义）。全部 AI 调用走 call_gateway，不许再复制 requests.post
core/config.py          →  🔴 BRIEFING_AS_OF 单一出口（改它 re-key 全部缓存→重烧，别随手改）
core/jsonstore.py       →  🔴 全项目落盘唯一原语：atomic_write_json/atomic_write_text（tmp+os.replace，无中间态）
                           + load_json→(status,data)，status∈ok|missing|corrupt。**损坏隔离不销毁**（改名 .corrupt-<ts>，
                           原始字节留着可人工抢救）。🔴 新增落盘点一律用它，禁止再写裸 write_text
core/health.py          →  ⏳(feat/healthz 分支,待合并) /healthz 的纯函数（env/路径注入 → 可单测）。
                           必填 key 缺失/目录不可写 = 不健康(503)
                           ⚠️ 逻辑不能写进 api/main.py：后者 import 时就复制 seed + 打 GitHub 请求，测试碰不得
fetcher/polymarket.py   →  get_top_political_position(address)   # 持仓+政治过滤+$5k
fetcher/trades.py       →  get_entry_time_v2(addr, cid)          # 建仓时间·首选（按市场查 /trades）
fetcher/activity.py     →  get_entry_time(addr, cid)             # 建仓时间·fallback（翻全活动，150 条上限，禁止为回测改它）
fetcher/news.py         →  get_news_for_market(q, entry_time, as_of=None)  # 关键词+Tavily 时间窗+缓存；as_of 防回测泄漏
analyzer/decoder.py     →  decode_position(assembled, as_of=None)         # sonnet-4.5 + 6 道守卫；as_of 时间旅行
renderer/card.py · main.py                                       # 终端卡片 + CLI
api/main.py             →  GET /analyze（v2 解读卡）· /backtest（静态）· /briefing（v3 完整简报）· /market-context（Context 一虚一实）· /dashboard（v3 统一看板①-⑥，整份按(钱包,AS_OF)硬缓存零 token；**⑥ 信心由 market_thesis 直出、⑤ 用市场级共享池、reason_v3 瘦身只供 follow_call+facts**）· /recommendations（扫榜推荐流）· /hot-traders（本周政治热门条）· /scorecard（诚实记分牌：增量抓 574 结算+冷数字）
fetcher/heisenberg.py   →  Heisenberg 共享客户端（参数真名表/limit≤200/🛡第七道守卫:返回钱包≠请求钱包→拦）
fetcher/profile.py·actions.py·price.py  →  简报数据层 A画像/B动作/C价格（建在 heisenberg 上，全免费 key）
analyzer/dual_catalyst.py  →  双向催化剂辩证（材质标签+守卫；as_of_anchor=锚现在(live)/锚建仓(replay)）
analyzer/price_reaction.py →  新闻↔价格反应=份量刻度+市场测谎仪（复用 price.price_at；归因只说"前后变动非导致"）
analyzer/reasoner_v3.py    →  ⑥ 的代码层：v3 置信度矩阵(底座删 rule5+R1-R4 只降不升)+build_facts 数据契约。纯代码零网关（旧 B 段 reasoner prose 已删：follow_call 由 api 代码判、信心由 market_thesis 直出）
analyzer/market_thesis.py  →  🔴 市场命题级对抗推理(取代钱包方向归因的信心)：共享池→bull(YES)‖bear(NO)→reasoner 直出单一信心+市场倾向+胜负手，按(cid,as_of)缓存(两反向钱包共享)，记 confidence_log.jsonl 待回验。map_wallet→顺/逆 edge
recommend.py·hot_traders.py·fetcher/markets.py  →  扫榜推荐(方法 E 市场反向找大户:种子→热门政治盘→共持大户→质量门→打分→⑥验证+同盘分歧检测) · 本周政治热门滚动条(579 7d∪政治共持池→581 7d政治盈亏) · get_market_holders 反向原语。产物 .data/recommendations.json·hot_traders.json(gitignored)
briefing/assemble.py·organize.py  →  A段编排(串数据层+催化剂+测谎)·B段第三个AI诚实整理(只整理不判断)
briefing/market_context.py →  Context「一虚一实」：价格异动≤as-of × GDELT 三层洗催化剂 × 巨鲸 48h 行为流(get_behavior_flags)
briefing/board_feed.py     →  统一看板⑤三源合并(GDELT+Tavily+gamma:综述+时间线流,↑印证/↓不买账)+②what_bet+持有侧 price_series。**新增 build_market_news_stream**：⑤ 改市场级共享池(两个反向钱包同一批新闻、方向标移交 ⑥ 顺/逆 edge)（纯组合层,不改封板）
fetcher/social.py       →  585 Social Pulse 社媒情绪动量（关键词→acceleration/author_diversity_pct/有机帖；🔴情绪非事实·仅实时·进不了回测；剔通用词+相关性过滤防 OR 误匹配）
scorecard.py            →  诚实记分牌：record_judgment(钩子,/analyze=decode·/dashboard=board)+fetch_settlements(574注入resolver)+compute_scorecard(纯代码)。档案 .data/scorecard.json(gitignored,装上后累积)
frontend/ (Vite+React)  →  src/App.jsx 单页（统一看板:英雄结论+D3上帝视角时间轴(实时光标)+原生赔率条(替iframe)+新闻×社媒并排 / Decode / 完整简报 / 市场Context / Track Record含记分牌）· src/index.css · 依赖 d3-scale/shape/array
backtest/               →  独立模块，诊断脚本带 _ 前缀；产物全 git 跟踪、静态、零 token
```
**🔴 简报 AS_OF（2026-07-08 晚起全实时）**：`BRIEFING_AS_OF`（**唯一定义在 `core/config.py`**）**默认 = `date.today()`**——课堂网关死亡后切自有 `ANTHROPIC_API_KEY`，"钉死 6-25 省老师 token"的历史约束解除。经济性由缓存层兜住：/dashboard 默认读该钱包**最新日期**快照（`core/cachefiles.newest_dated`，旧快照零 token 秒回），只有 新钱包/↻刷新/扫榜 ai_verify(fresh=1) 才在今天真烧（自有 key，~$0.05/钱包）。旧日期快照永不被刷新删除→重建失败自动回退（`_stale_dashboard_fallback`）。环境变量 `BRIEFING_AS_OF` 可覆盖回某天（回测/复现用）。已知边界：值在进程启动时求值，长驻进程跨天需重启才换日（Render 免费档常冷启动，实际无感）。AI 精选 = 推荐榜 top 5（`AI_TOP` 可调）。
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

**v3 已收官（现全部在 `master`）**：统一看板 ①-⑥ 跑通——身份/这一注(含 what_bet)/实时盘面/巨鲸 48h 行为流/三源催化剂(综述+时间线·带方向标)/⑥ Edge。数据地基(Heisenberg)、完整简报、Context 一虚一实、⑥ v3 置信度矩阵、**诚实记分牌(decode/board 判断自我验证)** 均落地。详见 `DEV_LOG.md`(2026-06-23) + `KNOWN_ISSUES.md` 第八类各愿景 ✅。

**下一程 roadmap**：
1. **Decode → 存档/记分牌**：✅ 记分牌机制已落地(`scorecard.py` + Track Record 顶部)；待办 = 把旧"最大仓解读卡"(Decode tab)正式转成存档形态、不再是主入口。
2. **扫榜推荐主页**：从"用户输钱包"→"系统扫政治盈利榜、主动推荐值得看的钱包/仓位"，主页即推荐流（接愿景 A 看动作 + B 哨兵）。
3. **路 B 离场盈亏 ROI 回测（v3 第一仗，仍开放）**：performance 从"测判断方向"升级为"AI 判 GO 跟入 $1000 平均收益率 vs 无脑全抄基线"。数据已绿灯(569 PnL 实测含全损)、口径已定，**尚未跑全量验收**。

**🟡 待验证假设**：记分牌端到端只在"市场真结算 → 574 填结果 → 命中率长出来"跑通后才算完整闭环；目前格式/数学/UI 三态都验过，但**真实时间推进下的自动填充尚未观察到**（开放盘暂全"待结算"，正常）。下次开工值得回 Track Record 看记分牌是否随数据世界推进自动长出已结算行。

**护城河**：不在数据（谁都能买），在判断（聪明钱行为 + 新闻 + 价格三合一的可信、诚实判断）。完整蓝图在 `KNOWN_ISSUES.md`（第七世界观 / 第八愿景 / 第九数据 API / 第十导师反馈）。

---

## 🔧 工程地基硬化轨（2026-08-01 起，与产品 roadmap 并行的另一条线）

起因：2026-08-01 做了一次全量健康检查（产出 `AUDIT.md`，24 条问题分 P0/P1/P2 + 三阶段路线图）。
结论是**判断力已验证、诚实性设计是真护城河，缺的是一层"敢让人动手的地基"**。此后两条线并行：产品线看 `KNOWN_ISSUES.md`，地基线看 `AUDIT.md` 的进度看板。

**已完成并验证（8 个 PR，全部 TDD + `scripts/check.sh` 绿；7 个已合入 master，`feat/healthz` 待开 PR）**

| 模块 / 改动 | 职责 | 关联 |
|---|---|---|
| `core/jsonstore.py` + `tests/test_jsonstore.py` | 全项目落盘唯一原语：原子写 + 损坏隔离 | P0-1 |
| `scorecard.py` `_load`/`_save` | 接入 jsonstore。**三条记分牌红线的数学一字未动** | P0-1 |
| 其余 19 处落盘点（`api/main.py`·`core/persist.py`·`analyzer/*`·`briefing/*`·`recommend.py`·`hot_traders.py`） | 全部换原子写 | P0-1 |
| `.data/` 业务文件读路径 + `tests/test_business_file_reads.py` | 推荐榜/热门条损坏时隔离并留证据，不再静默变空榜 | P0-1 |
| `core/health.py` + `/healthz` + `tests/test_health.py` ⏳**待合并** | 真探活（必填 key + 目录可写），缺必填项 503。已 TDD 验过 + 真机跑过两态，但**还在 `feat/healthz` 分支，未进 master** | P1-12 |
| `fetcher/news.py` + `tests/test_news_no_key.py` | 去掉 import 时硬失败，惰性 Tavily client | P1-24 |
| `.github/workflows/check.yml` + `scripts/check.sh` 入库 + `.claude/settings.json` 放行 | CI 上线，跑与本地同一个脚本、**不注入任何 key** | P1-13 |
| `render.yaml` / `.env.example` / `frontend/dist` 退出版本控制 / 部署分支收口 master | 部署契约与分支拓扑 | P0-2·P0-4·P2-20 |
| `AUDIT.md` 入库 + 进度看板 | 让"我做到哪了"随时可查 | — |

**🔴 下一步（明确单一）：清掉最后一个 P0 —— P0-3「服务用 HTTP 调用自己」**
`recommend.ai_verify` 起 5 个线程用 `requests.get` 打**本进程自己**的 `/dashboard`（timeout 240s），而 `api/main.py` 全部端点是同步 `def`、跑在 anyio 默认 40 线程池里 → 扫榜期间自己把自己的线程池占满。
做法：把 `_dashboard_impl` 连同单飞锁抽进 `services/`，`recommend` 改进程内直接调用。
**先决**：`_dashboard_impl` 有 8 个 `_err`/`_stale_dashboard_fallback` 出口（返回 `JSONResponse`），抽 service 前**必须先定好错误契约**（service 返纯数据、HTTP 映射留在 api 层）。约 2 小时，**值得单独一场、别和别的任务混**。做完 Phase 1「止血」即收工。

**🟡 待解决 / 待验证（地基线）**

1. **`/healthz` 缺 key 返 503 是个可推翻的取舍**。缺 key 的实例其实仍能靠缓存服务已有钱包，判 503 会让 Render 认定部署失败。选择失败得响一点，是因为"起来了、首页能开、一点陌生钱包就 502、哪儿都不说为什么"正是 P0-2 那次事故的形态。要改成"警告但放行"很容易，口径集中在 `core/health.py`。
2. **CI 尚未观察到真实运行**。workflow 已入库、干净检出零 key 本地验过（24 个测试文件全绿），但**GitHub Actions 上的首次真实运行还没看过**（尤其 `npm ci` 与 Python 3.13 在 ubuntu-latest 上的表现）。下次开工先扫一眼 Actions 页。
3. **本地分支卫生**：`master` 曾长期落后 91 个 commit，收尾时误切过去导致工作区退回旧状态（已快进修复）。`slim-dashboard-track-record`、`v3-briefing` 均已过时，**建议删掉**，只留 master + 在做的功能分支。
4. **`AUDIT.md` 的行号会漂**。所有证据行号基于首次审计时的 `36d6412`，重构后会失效 —— **认问题编号，别认行号**（编号永不复用）。

**地基线剩余大头（都在 `AUDIT.md`，按价值排）**：P1-5 六道守卫覆盖 0 个用户可见路径（审计最重要的发现）→ P1-8 核心判断逻辑零测试 → P1-11/P1-10 拆 `api/main.py` 902 行 god module + 缓存失效注册表 → P1-6 回验闭环（`confidence_log.jsonl` 至今只写不读）。

---

*本项目可用命令：`/checkpoint` —— 整理进度并存档。*
*历史编年史在 `DEV_LOG.md`；产品蓝图在 `KNOWN_ISSUES.md`；**工程地基进度在 `AUDIT.md` 的进度看板**。改这四个文件时保持各管一摊、不重复。*
*测试钱包速查 `test_wallets.md`（验规则按特征精准挑）；字段留空诊断 `empty_field_guide.md`（先分清真相 vs bug，诚实留空是产品灵魂）。*
