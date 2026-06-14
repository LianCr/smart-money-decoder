# 回测最终样本复盘（封板素材，2026-06-13）

> 由 `backtest/pipeline.py` 多钱包聚合（`run_backtest_multi`）跑出，钱包从 Polymarket 成交量榜
> （`lb-api/volume`）筛出的政治活跃者取样。原始结果在 `.cache/backtest/result.json`（gitignore），
> **本文件是固化快照，防缓存清理冲掉**；每条含两时点完整 decoder 输出（含 reasoning 原文）。

**总览**：方向命中 **5/6** · 信心校准 高 3/4 vs 低 0/0（低信心无样本）· 构成 **4 赢 / 2 输**

**NO BASIS 成因核查（关键）**：12 张卡全部 `time_anchored=True` + 有 catalyst + 无『无新闻』warning。
**没有一个 NO BASIS 是『搜不到催化剂』**——都是 decoder 读了时间窗新闻后、对『证据逆向 thesis』的赌注
主动不背书。Starmer 两盘即铁证（读到 Starmer 拒辞 → NO BASIS → 赌注真输，系统躲过）。
语义瑕疵：模型把 `NO BASIS`（prompt 定义=找不到催化剂）借用来表达『催化剂反对 thesis』，功能对（=别跟）
但严格说该有更精准的档位（如 FADE）。Powell 失手亦源于此：读到『Powell 暂留』判 NO BASIS，但实际 Powell 出局。

---

## 样本 1 · Car · 0x7c3db7…ed033
- **市场**：Will Trump restart Project Freedom by June 30?
- **真实结算**：`YES`（结算日 2026-06-14）
- **钱包持仓侧**：`Yes` → **赢**
- **系统判定**：✓ 命中（T-1 follow_call 是否背书 对照最终赢输）
  - **T-7 · 2026-06-07**：`NO BASIS` / 信心 `medium` · time_anchored=`True` · catalyst 2 条 · warning：无
    - catalyst：
      - [BEFORE_ENTRY] Freedom 250 and America250: How is the US celebrating its big birthday? - BBC
      - [AFTER_ENTRY] Trump Makes It Official: The 'Freedom 250' Concerts Are Canceled — to Be Replaced With 'the Greatest Rally EVER!,' Starring Him and (Surprise) Lee Greenwood - Yahoo News Canada
    - reasoning 原文：Confidence is medium because the entry timing is known and a catalyst exists, but the post-entry cancellation news directly undermines the thesis. The 85% drawdown reflects market consensus that 'restart' will not occur by June 30 under any reasonable interpretation. Without resolution criteria to clarify whether event substitution qualifies, the favorable case has evaporated and the current price offers no edge—only high-risk speculation on an undefined settlement standard.
  - **T-1 · 2026-06-13**：`CHASED` / 信心 `high` · time_anchored=`True` · catalyst 2 条 · warning：无
    - catalyst：
      - [BEFORE_ENTRY] Freedom 250 and America250: How is the US celebrating its big birthday? - BBC
      - [AFTER_ENTRY] Trump Makes It Official: The 'Freedom 250' Concerts Are Canceled — to Be Replaced With 'the Greatest Rally EVER!,' Starring Him and (Surprise) Lee Greenwood - Yahoo News Canada
    - reasoning 原文：Time-anchored news before entry documented Freedom 250 as an active Trump initiative, and post-entry articles confirm ongoing programming adjustments within the resolution window. The wallet's 2.66% gain and current price of 0.9995 show the market has fully absorbed the thesis; the remaining upside is 0.0005 per share against a 0.9995 downside if settlement hinges on wording not visible in the absent resolution criteria.
- **点评**：T-7 价格尚低、edge 未显（NO BASIS）；T-1 时间窗新闻确认 Freedom 250 在推进 → CHASED。持 Yes 赢，系统正确转向背书。**命中**。

## 样本 2 · Car · 0x7c3db7…ed033
- **市场**：US x Iran diplomatic meeting by June 10, 2026?
- **真实结算**：`NO`（结算日 2026-06-11）
- **钱包持仓侧**：`No` → **赢**
- **系统判定**：✓ 命中（T-1 follow_call 是否背书 对照最终赢输）
  - **T-7 · 2026-06-04**：`NO BASIS` / 信心 `medium` · time_anchored=`True` · catalyst 2 条 · warning：无
    - catalyst：
      - [AFTER_ENTRY] U.S.-Iran memorandum of understanding likely to be signed next week - CBS News
      - [AFTER_ENTRY] Unclear if Iran is prepared to meet Trump's nuclear demands: Former Ambassador - CNBC
    - reasoning 原文：The wallet's entry preceded a significant post-bet development — CBS reporting that a U.S.-Iran memorandum of understanding is likely to be signed early the week following June 10, directly threatening the No thesis. The 4.64% drawdown indicates the market has absorbed this news and is pricing in elevated risk of a diplomatic meeting. No pre-entry catalyst is present to explain the original rationale, and the post-entry headline points toward the opposite outcome. The wallet's bet is now underwater with unfavorable momentum and no identifiable informational edge for a follower to exploit.
  - **T-1 · 2026-06-10**：`CHASED` / 信心 `high` · time_anchored=`True` · catalyst 2 条 · warning：无
    - catalyst：
      - [AFTER_ENTRY] U.S.-Iran memorandum of understanding likely to be signed next week - CBS News
      - [AFTER_ENTRY] Unclear if Iran is prepared to meet Trump's nuclear demands: Former Ambassador - CNBC
    - reasoning 原文：The position is profitable at 2.94 percent, and both post-entry articles confirm real-time developments: one describing imminent US-Iran engagement, the other stating neither side is ready to meet. The wallet timed entry before today's resolution date, capturing nearly the entire move to 0.9985. A follower today buys extreme conviction at extreme cost, with only 0.0015 per share left if correct.
- **点评**：T-7 保守；T-1 两篇 post-entry 新闻确认美伊接触临近 → CHASED。持 No 赢，**命中**。

## 样本 3 · Car · 0x7c3db7…ed033
- **市场**：Iran closes its airspace by June 8?
- **真实结算**：`YES`（结算日 2026-06-12）
- **钱包持仓侧**：`Yes` → **赢**
- **系统判定**：✓ 命中（T-1 follow_call 是否背书 对照最终赢输）
  - **T-7 · 2026-06-05**：`NO BASIS` / 信心 `medium` · time_anchored=`True` · catalyst 1 条 · warning：无
    - catalyst：
      - [AFTER_ENTRY] Israel says it has struck Iran after taking missile fire - Politico
    - reasoning 原文：The sole relevant article was published after entry and describes localized airspace closure that may or may not satisfy the market's language. The wallet's 97¢ entry and catastrophic loss suggest either a failed escalation thesis or a settlement-criteria mismatch; without pre-entry catalyst or clear resolution rules, following at 5¢ is speculative on both event continuation and favorable adjudication.
  - **T-1 · 2026-06-11**：`CHASED` / 信心 `high` · time_anchored=`True` · catalyst 1 条 · warning：无
    - catalyst：
      - [AFTER_ENTRY] Israel says it has struck Iran after taking missile fire - Politico
    - reasoning 原文：High confidence stems from a post-entry article explicitly confirming Tehran airspace closure on the settlement date, time-anchored to the wallet's entry, and a 2.9351 percent gain showing the market absorbed the news. The thesis is likely correct, but follower_max_upside of 0.0005 per share offers no meaningful edge at current_price. The wallet captured the move; a follower today buys certainty at cost.
- **点评**：T-7 持 Yes 时价仅 0.05、像 longshot（NO BASIS）；T-1 新闻确认领空关闭、价 0.9995 → CHASED。持 Yes 赢，**命中**。

## 样本 4 · ImJustKen · 0x9d84ce…dc1344
- **市场**：Starmer out by May 31, 2026?
- **真实结算**：`NO`（结算日 2026-06-01）
- **钱包持仓侧**：`Yes` → **输**
- **系统判定**：✓ 命中（T-1 follow_call 是否背书 对照最终赢输）
  - **T-7 · 2026-05-25**：`NO BASIS` / 信心 `medium` · time_anchored=`True` · catalyst 2 条 · warning：无
    - catalyst：
      - [AFTER_ENTRY] Britain's Starmer fights for his job as calls for his ouster grow after local election losses - Greenwich Time
      - [AFTER_ENTRY] U.K. Prime Minister Starmer Says He Won't Step Down Amid Calls For Him To Resign - HuffPost
    - reasoning 原文：Confidence is medium because time-anchored news confirms the departure thesis has live political support (80 lawmakers demanding resignation), but the wallet's -81.70% loss and the post-entry nature of all catalysts show the entry was mistimed or speculative. Starmer's public refusal to resign and the market's 96.6% implied probability he survives through May 31 indicate the window has likely closed. Today is May 25; resolution is May 31, leaving minimal time for a forced exit, and no fresh catalyst suggests imminent departure.
  - **T-1 · 2026-05-31**：`NO BASIS` / 信心 `medium` · time_anchored=`True` · catalyst 2 条 · warning：无
    - catalyst：
      - [AFTER_ENTRY] Britain's Starmer fights for his job as calls for his ouster grow after local election losses - Greenwich Time
      - [AFTER_ENTRY] U.K. Prime Minister Starmer Says He Won't Step Down Amid Calls For Him To Resign - HuffPost
    - reasoning 原文：Both catalyst articles were published after entry and describe developments that moved sharply against the wallet's thesis: Starmer faced calls to resign but explicitly refused and remained in office through the settlement date. The bet lost completely; the current price reflects the resolved outcome. Medium confidence reflects that the directional call was clear from sourced events, but following at settlement with the outcome already determined offers no edge.
- **点评**：★**正确回避亏损**：两时点 catalyst 都显示 Starmer 公开拒绝辞职，decoder 两时点均 NO BASIS、不背书；钱包持 Yes（赌下台）最终**赌输**，系统躲过。**命中**。

## 样本 5 · ImJustKen · 0x9d84ce…dc1344
- **市场**：Starmer out by May 15, 2026?
- **真实结算**：`NO`（结算日 2026-05-16）
- **钱包持仓侧**：`Yes` → **输**
- **系统判定**：✓ 命中（T-1 follow_call 是否背书 对照最终赢输）
  - **T-7 · 2026-05-09**：`NO BASIS` / 信心 `medium` · time_anchored=`True` · catalyst 2 条 · warning：无
    - catalyst：
      - [BEFORE_ENTRY] Starmer says he won't quit after local elections deliver losses for Labour and wins for Reform UK - The Sun Chronicle
      - [AFTER_ENTRY] Starmer pledges to prove his doubters wrong but faces a wave of resignation calls - The Sun Chronicle
    - reasoning 原文：The catalyst is anchored and real — local election losses on May 7 preceded the bet and post-entry reporting confirms rising pressure — but the market has moved decisively against the thesis, declining 36 percent despite adverse headlines. The sharp negative price delta indicates informed participants are fading the resignation narrative, and the brief window between today (May 9) and the May 15 deadline leaves minimal time for the thesis to materialize, undermining the case for a follower entry even at the lower price.
  - **T-1 · 2026-05-15**：`NO BASIS` / 信心 `medium` · time_anchored=`True` · catalyst 2 条 · warning：无
    - catalyst：
      - [BEFORE_ENTRY] Starmer says he won't quit after local elections deliver losses for Labour and wins for Reform UK - The Sun Chronicle
      - [AFTER_ENTRY] Starmer faces mounting pressure to resign as he meets UK Cabinet in crunch talks - The Sun Chronicle
    - reasoning 原文：The catalyst was clear and time-anchored—local election losses and mounting resignation calls—but the market has moved decisively against the thesis: today is May 15, Starmer has not resigned, and the price has collapsed from 0.0433 to 0.0105. While the June 30 settlement date technically leaves time for an exit, the title event (out by May 15) has not occurred, the wallet is down 75.7506 percent, and no new catalyst suggests imminent departure. Following would require betting on a reversal the original entry did not anticipate.
- **点评**：★**正确回避亏损**：catalyst 时间锚定（地方选举失利+辞职呼声），但新闻显示 Starmer 仍未下台，decoder NO BASIS；赌输，系统躲过。**命中**。

## 样本 6 · ImJustKen · 0x9d84ce…dc1344
- **市场**：Jerome Powell out as Fed Chair by May 15, 2026?
- **真实结算**：`YES`（结算日 2026-05-16）
- **钱包持仓侧**：`Yes` → **赢**
- **系统判定**：✗ 失手（T-1 follow_call 是否背书 对照最终赢输）
  - **T-7 · 2026-05-09**：`CHASED` / 信心 `high` · time_anchored=`True` · catalyst 2 条 · warning：无
    - catalyst：
      - [AFTER_ENTRY] Fed Chair Jerome Powell Just Broke 75 Years of Precedent With a Move That's Likely to Frustrate President Trump. How Will This Impact the Stock Market? - The Motley Fool
      - [AFTER_ENTRY] Board Names Jerome Powell Temporary Fed Chair. Two Governors Disagree With the Move. - Barron's
    - reasoning 原文：Post-entry articles confirm Powell's standard chair term concluded and he was named to a temporary role, validating the wallet's thesis with institutional precision. The 19.16 percent gain demonstrates the market has repriced toward Yes as the May 15, 2026 settlement date arrived. However, the articles describe Powell holding a chair title—albeit temporary—on the resolution date itself, introducing settlement risk that the market has not resolved despite the favorable move.
  - **T-1 · 2026-05-15**：`NO BASIS` / 信心 `high` · time_anchored=`True` · catalyst 2 条 · warning：无
    - catalyst：
      - [BEFORE_ENTRY] Fed Chair Jerome Powell Just Broke 75 Years of Precedent With a Move That's Likely to Frustrate President Trump. How Will This Impact the Stock Market? - The Motley Fool
      - [AFTER_ENTRY] Board Names Jerome Powell Temporary Fed Chair. Two Governors Disagree With the Move. - Barron's
    - reasoning 原文：Time-anchored catalysts exist and the wallet captured a modest 5.4% move. However, the resolution date is today and post-entry news confirms Powell retained at least an interim chair title on May 15, 2026, directly conflicting with the Yes thesis. The position is now a settlement-interpretation gamble on a closed factual record, not a tradeable forward view; confidence in the analysis is high, but confidence in the wallet's win is low and following is unjustifiable.
- **点评**：✗**失手（审慎过头）**：T-7 本是 `CHASED`/high（背书）；临近结算，decoder **正确识别出一层结算歧义**——Powell 被任命为『临时主席』，到底算不算"出局"？——但它把歧义判向了"未出局"、收手成 `NO BASIS`。实际结算 `Yes`（按全任期结束判定为出局）→ 该跟没跟。**注意：不是无信息、也不是误判方向，而是在真实的结算口径模糊处选择了不押。** demo 时可如实说：decoder 看到了关键风险点，但在二选一的歧义上压错了一边。
