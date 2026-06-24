# DEV_LOG.md — 开发编年史（归档）

> 这里是 smart-money-decoder 的开发历史留档，从 CLAUDE.md 拆分出来，避免拖慢每次开工。
> **操作性内容（红线 / API 坑 / 契约 / 协作纪律）在 CLAUDE.md；产品蓝图在 KNOWN_ISSUES.md。**
> 本文件只读、供需要追溯"某个决策当时为什么这么定"时翻阅。倒序排列（新在上）。

---

## 2026-06-23 · v3 收官 — 统一看板（①-⑥）+ ⑥ Edge/Reasoning

- **统一看板**：把 Decode / Briefing / Context 三个分散版本的长板合并成一屏 6 段——①身份+体量(头像+PnL曲线+官方榜/胜率/政治盘专长) · ②这一注+现状 · ③实时盘面(Polymarket 嵌入) · ④⑤折叠双栏(钱包48h行为流 × 世界催化剂,催化剂带 BEFORE/AFTER ENTRY + ↑↓市场反应符号+幅度) · ⑥Edge。**旧三 tab 原封保留(纯增量,一行没删)**。`/dashboard` 端点复用已封板模块输出(briefing + 行为流 + ⑥ + PnL曲线)，整份按 (钱包,as_of) 硬缓存→重复零 token。
- **⑥ Edge/Reasoning（本轮唯一新逻辑）= `analyzer/reasoner_v3.py`**：
  - **新 v3 置信度矩阵**：v2 底座**删 rule5**(未锚→封中,实时场景不再因此降级) + `R1`(支持侧催化剂被市场反定价)→`R2`(对冲:主仓<另侧×3)→`R3`(48h大额退出)→`R4`(证据双空) **逐条只降不升**(min cap) + 输出**降级原因列表** + **升级模块预留 no-op**(无任何升级路径)。**不改 decoder v2 矩阵**(/analyze 在用)，独立模块只读封板模块输出。
  - **reasoner**：读 `reasoner_v3_prompt.txt`(三铁律:不判对错 / 测谎≠水平判断 / 不替用户决定) + 代码算好的字段 → 网关出 `follow_call`/`confidence`(echo不改)/**简体中文** reasoning；**5 道守卫**(CONFIDENCE_TAMPERED · INVALID_FOLLOW_CALL · 三铁律扫词 · DURATION_COMPUTED · FABRICATED)。
  - **5 个真实 case 验证(~25k token)**：矩阵 R1-R4 + 底座全部正确降级；reasoning 说人话、守住三铁律(没判对错、没替用户决定)；**DURATION_COMPUTED 守卫在 Starmer 盘真实发火一次**(模型想算"距 6/30 还剩 X 天"被拦)——守卫不是摆设。
  - **诚实发现(钉死)**：`R1`(支持催化剂被市场反定价)**真实场景罕见**——市场否定钱包时,证据多表现为"浮亏 + 证据空/威胁多",由 `R4` 兜底；R1 逻辑已零 token 证明(高→低/高→中)，不专门猎盘，省 5-8k。
  - prompt **强制简体中文**(reasoning 之前中英混杂,改后统一中文)。

## 2026-06-20→22 · v3 数据地基 + 完整简报 + Context 一虚一实 + 巨鲸行为流

- **Heisenberg 数据层全验通**：参数真名因 endpoint 而异(569=wallet/556=proxy_wallet/581=proxy_wallet/579=wallet_address)、limit≤200、**第七道守卫**(返回钱包≠请求钱包→拦,防参数名写错静默返全局流)。**路 B 离场盈亏绿灯**(569 含持到归零全损)。其上建免费数据层 profile/actions/price。
- **完整简报 `/briefing`**：钱包→顶仓→A段编排(WHO/WHAT/PRICE + 双向催化剂 + 市场测谎仪)+ B段第三个 AI 诚实整理(只整理不判断)，整份硬缓存零 token。
- **市场 Context「一虚一实」`/market-context`**：左=Polymarket 实时嵌入(**实**)、右=as-of 复盘(**虚**)=价格异动 × GDELT 三层催化剂 × 巨鲸 48h 行为流。
- **巨鲸行为流(556 48h)**：愿景 A「看动作」落地——`ADD`信念增强 / `EXIT`主力撤退 / `STATIC`诚实留白；**事实陈述非判断**("过去 24h 大额 SELL 流…由你裁决")。
- **GDELT 三层管线**(海量召回→实体硬过滤→LLM重排, as-of 物理防泄漏)：**验证为催化剂来源**；**证伪为市场交叉判定**(实体聚合 tone/volume 粒度太粗,Burnham +35% 跳变 tone/volume 都哑火)→ 钉死:GDELT 只当催化剂源、不当测谎,测谎维持单层(Polymarket 盘价 × 单条新闻)。

## 2026-06-15 · demo 收尾（视觉重构 + 部署/简历讨论）

- 首页 / 回测页 / loading 页全套视觉重构为"彭博终端冷冽 + 克制多巴胺"风：去中二代号、加层级、统一终端语言、克制发光。
- 顶栏改"实时战力状态栏"：砍平级 tab，右上 `[TRACK RECORD: 5W·1L]` 功勋章（**不挂 +10% LIFT**——需语境才诚实，留在回测页四层说明里）。
- 回测统计区改"四层渐进式金字塔"：一句话定调 → +10%/+13% 大数字 → 诚实说明 → `[SYSTEM AUDIT]` 折叠审计日志（法定译文，严禁把"命中"说成"翻倍"、"没本事"说成"风控猛"）。
- 示例钱包定稿（见 CLAUDE.md demo 前固定动作）；胜率标签去掉（非我方实时计算、会过期，破诚实人设）；累计盈利 +$X.XM 是手填快照。
- 20 秒 demo 脚本：点大户 → 出卡（4 步流程可视化"AI 走真流程"）→ Starmer 避坑案例（杀手锏）→ 5对1错背书 → "卖清醒不卖确定" slogan。
- **未装 Tailwind**（无 config 无依赖）：所有 slate/mono/rounded 类用项目现有 CSS 变量等价实现。

## 2026-06-14 · v2 lift 封板（路 A 跑通）

- **`backtest/_market_lift.py`**（路 A「市场优先」lift 取样器）：Gamma 已结算政治盘（中量、可翻页，深 offset 1900–6000）→ `/trades` 全成交两侧重建「持到结算」买家（赢家+输家**同一套 B 机制**，net buy−sell>0）→ 滤成本 >$5k → 建仓时点重放 decoder（current≈entry、news `as_of=entry_time`、decode `as_of=建仓日`）→ GO 子集方向胜率 vs 全集 lift。输家全取、赢家每盘限 4 凑平衡；边算边记 entry_price，输出含 edge-band 切片。
- **`backtest/lift_v1.md`**（结果固化，git 跟踪）：数字表 + 三层裁决 + 4 caveat + 27 盘扫描日志 + 方法论。
- **第一版 lift（N=94 / 27 盘 / 15 输 79 赢）**：全集 GO 94% vs 基线 84% = **+10%**；edge-band（0.10<entry<0.90, N=30）GO 67% vs 53% = **+13%**。近明牌占 68% 抬高基线。
- **三层裁决（钉死）**：① decoder「诚实保守不瞎跟」**验证成立**（94 盘只 GO 17、edge-band 30 盘只 GO 3，高度选择性非橡皮图章）；② 「能否在硬盘发现可盈利 edge」**测不出但非证伪**——结算输赢口径在 edge-band GO 太稀（3，2/3 翻 1/3 就反号；躲掉硬盘赢 52%≈基线 53%），是口径喂不饱不是 decoder 没 edge；③ 救它 = 换「离场盈亏」口径（路 B）= v3 愿景 A/B 同一工程 → v2 数据把路 B 从「可选」升成「v3 首要任务」（有据非直觉）。
- **取样管道验证**：N 从 v1 的 6 → 94（市场优先破样本稀缺）。输家高度集中在多候选人选举（Virginia AG 一盘贡献 7）——多候选人选举是输家唯一稳定蓄水池（押错者无法赎回、被迫持到结算）。
- demo 收尾同日：实时解读加「钱包+日期」外层缓存（命门）；Track Record 改"案例故事卡 + 折叠 lift"；`/backtest` 返回 `{cases, summary, lift}` 全静态零 token。

## 2026-06-13 · v2 方向确立 + 回测可读性重构

- **产品定位拍板 = C「聪明钱筛选器」**（#22）：「我不号称比鲸鱼聪明，我告诉你它哪注还值得跟」。回测口径走「GO 子集方向胜率 vs 全集 lift」——只需公开结算结果，不依赖输盘数据。
- **#7 落地（回测无未来信息泄漏）**：`news.py` 加可选 `as_of`（unix 秒），回测窗 end 截到快照时点（`[建仓-7, as_of]`），晚于该刻的文章自动丢；窗口退化时不走 30 天兜底（会泄漏）返回空。正向 `as_of=None` 行为不变。`backtest/pipeline.py` 各时点各自重搜。
- **#4 诊断结案（决定 v2 方向）**：早时点 NO BASIS 干净 a/b 诊断——**4/6 是 (a) 那刻真没新闻，0/6 是 decoder 对支持性新闻过严**。冒烟的枪：同一批 Starmer 辞职新闻，对 May15 盘在 T-7 之后、对 May31 盘在 T-7 之前。**结论：decoder 没病、保守正当（红线证实，绝不调松）；「加强新闻源」是死路（4 个 a 是新闻尚未发生）；真正杠杆是「时点定义」——T-7 对短引信盘太早、早于催化剂。** → v2 新方向：早时点从「固定结算-7天」改锚「建仓时点 entry_time」。
- **关键实验 `backtest/_scan_timepoint.py`**：结算-7天 GO 0/6 → 建仓时点 4/6。「换时点救活 GO」核心假设成立，正式 lift 取建仓时点。
- **回测可读性重构**：列表瘦身（默认行 4 元素，其余收抽屉，T-7→T-1 演变移抽屉顶）；难度系数 `1-|entry_price-0.5|*2` 前端三档（迷雾/倾斜/近明牌，不碰 pipeline）；PnL 曲线可读化。动效全 CSS transition，零新依赖。

## 2026-06-13 · 回测 pipeline 封板（三块砖）

- **第一块 `backtest/full_activity.py`** `fetch_full_activity(wallet, start, end)`：独立翻页（破 150 上限）、时间窗闭区间筛、老边界提前停。13 单测 + 烟测过。
- **第二块 `backtest/resolution.py`** `get_market_resolution(condition_id)`：conditionId → 真实结算结果（获胜方 + 实际结算时间）。16 单测 + 三类真实市场对账。**gamma 必带 `closed=true`**；T 锚 `closedTime`（实测有市场与 endDate 差 4 天）。
- **第三块**：`snapshot.py` `get_price_at(token_id, ts)`（CLOB prices-history，短命市场 T-7 未创建返 None → 自然筛 ≥7天盘）；`pipeline.py` `run_backtest`（翻全活动重建持有侧 → 判赢输 → T-7/T-1 取历史价 → 新闻锚 entry_time 两时点共用 → 两时点重放 decoder 传 as_of → hit=T-1 背书==最终赢 → 聚合）；`decoder.py` `decode_position(assembled, as_of=None)` 修拦路 bug（历史重放传快照日，模型「今天」对齐 T-7/T-1，不再撞 DURATION_COMPUTED）。
- **最终样本：多钱包聚合 6 个**（伊朗 Car 3 + Netanyahu ImJustKen 3）：方向命中 5/6、构成 4 赢 2 输。**Starmer 两个亏损盘**最有说服力：钱包押"首相下台"赌输，decoder 两时点都读到"Starmer 拒辞"判 NO BASIS 不背书 → 正确躲过亏损。Powell 一个失手（T-7 CHASED → T-1 NO BASIS，识别"临时主席"歧义但压错边）。固化在 `final_samples.md`。
- **NO BASIS 成因核查**：6 样本 12 张卡没有一个 NO BASIS 是"搜不到新闻"，全部 time_anchored + 有 catalyst。都是 decoder 读了新闻、对"证据逆向 thesis"主动不背书。**demo 要诚实说"它在读新闻做判断"，不是"没信息所以保守"**。语义瑕疵：模型把 NO BASIS 借用表达"催化剂反对 thesis"（功能对=别跟，严格说缺个 FADE 档）。

## 2026-06-12 · 回测实探结论

- **「输」的信号公开接口缺失**：已结算**赢**盘有 REDEEM 事件（伊朗 84 条），但**输**盘份额归零、无事件、赎回后从 positions 消失 → 胜率不可靠（分母缺输，虚高 90%+）。战绩口径若真做应走「净实现盈亏」非胜率。
- ✅ **每个市场「真实结算结果」**：gamma `/markets?condition_ids=<cid>&closed=true` 可靠返回。**真因是默认过滤已结算市场，必须带 `closed=true`**（此前误判为 conditionId 反查失效）。`outcomes`/`outcomePrices` 是 JSON 字符串需 parse，获胜方 = outcomePrices argmax；`closedTime`=实际结算（T 锚）。封装为 `resolution.py`。
- **该钱包合格样本（≥7天+有历史价+cost≥1000）实测 10 个全赢 0 输**——长线政治盘全中。故回测「失手」主要来自「decoder 对赢盘误判 NO BASIS」（✗=该跟没跟），非钱包亏损。短引信盘多被 T-7 历史价缺失筛掉，losses 多在其中。
- CLOB 历史价：`clob.polymarket.com/prices-history?market=<tokenId>&...` → `{history:[{t,p}]}`，token=记录里 `asset`。
- 政治过滤：gamma 市场不带 tags，但 `events[0].id` → `/events?id=` tags 区分（体育 `['sports','soccer']` vs 政治 `['politics','geopolitics']`）。

## 2026-06-11 · 收官冲刺修复

- ENTRY_PRICE_DENIED 守卫子串误伤（"unknown by date" 良性措辞）→ 改为数值在场即放行。
- DURATION_COMPUTED 与 HARD RULE 4 矛盾 → 改 prompt（日期并列、禁止表述时长）。
- 字段值内裸双引号破坏 JSON → prompt 强制单引号。
- **news 缓存 key 漏带时间窗**（真 bug）→ key 改 `md5(question|start|end)`，否则 entry_time 变化后命中旧缓存返回过期 anchored 结果。
- **`fetcher/trades.py` 的 `get_entry_time_v2` 落地**：`/trades?market=<conditionId>&user=<wallet>` 按市场维度查，服务端精确过滤（伊朗 98 条全命中、Newsom 6 条全命中——后者 activity 翻 2000 条都找不到）。取最早一笔 BUY。main/api 均走 trades v2 优先 → activity fallback → None 降级。

## 2026-06-10 · activity conditionId 命中率诊断（钉死：非 Bug，禁用 eventSlug）

- **结论**：positions 和 activity 两接口的 `conditionId` 语义**完全一致**——都是子市场级 ID。伊朗钱包 positions 146 个 conditionId 与 activity 前 150 条 TRADE 的 18 个交集 15 个，证明匹配得上，老代码精确匹配是对的。
- **真实机制**：一个父 event 挂多个子市场（"before 2027" / "by September 30" / "by Dec 31"），各有独立 conditionId。持仓子市场的建仓动作不在最近 150 条 activity 内时（持仓老、近期交易在其它子市场）自然找不到。**`entry_time=None` 是正确降级。**
- **反例钉死**：aliens 钱包持有 "before 2027" 子市场 5 万股 No 仓（cid `0x747dc8...`），activity 前 150 条 146 条 TRADE 全属另一子市场 "by September 30"（cid `0xace3c7...`），两者共享 `eventSlug`。
- **禁止用 eventSlug 模糊匹配"修复"**：会把另一赌盘交易时间错配成本仓建仓时间，污染下游新闻窗。**错配比 None 危险一个量级**（None 触发明确降级，错配以 time_anchored=True 假象交给后续模块）。此条防未来任何人/AI 重提该方案。

---

*更早的数据契约定稿（2026-06-10 基于真实 API 核查）、置信度矩阵、算术边界等已上升为正式契约，移入 CLAUDE.md「解码层契约」节。*
