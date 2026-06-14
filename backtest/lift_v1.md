# v2 第一版 lift —— 结算时刻存档（2026-06-14）

> **这是 v2 的核心成果。** 路 A 取样管道首次跑出 GO 子集 vs 全集的 lift。
> 与 `final_samples.md` 同等待遇：固化进 git，防临时文件被清。demo / 申请核心素材。
>
> **一句话**：decoder 不是橡皮图章（高度选择性、不瞎跟），GO 在两个切片都跑赢基线（方向对）；
> 但它保守到在真五五开的盘里几乎不开口（edge-band 仅 GO 3/30），**这个指标因此被"硬盘 GO 太稀"
> 饿死了**——救它的不是调松门槛（红线），是换 `离场盈亏` 口径（路 B）或上更大样本。

## 口径（路 A · C-降级）

- **取样**：市场优先。Gamma `closed=true` 政治盘（中量、可翻页）→ `/trades` 全成交两侧重建
  「持到结算」的买家（赢家 + 输家，**同一套 B 机制**）→ 滤 >$5k（聪明钱）。输家是瓶颈，全取；
  赢家每盘限 4，凑尽量平衡。
- **时点**：建仓时点（`current_price ≈ entry_price`，news `as_of=entry_time`，#7 无未来泄漏）。
- **输赢**：结算结果（持有侧 outcome == winner）。
- **lift**：GO 子集（decoder 在建仓时点判 `ROOM LEFT`/`CHASED`）方向胜率 − 全集方向胜率。
- 脚本：`backtest/_market_lift.py`（`python -m backtest._market_lift`）。

---

## 数字（27 盘 · N=94）

| 口径 | N | 全集胜率 | GO 子集胜率 | **lift** |
|---|---|---|---|---|
| **全集（含近明牌）** | **94**（79W / 15L） | 84% | 94%（16/17） | **+10%** |
| **edge-band 0.10<entry<0.90** | **30**（16W / 14L） | 53% | 67%（2/3） | **+13%** |

- decoder 建仓时点：GO（跟）**17** / 躲（NO BASIS）**77**
- 躲子集胜率：82%（63/77）；**edge-band 内**躲子集胜率：52%（14/27）≈ 基线 53%
- 信心校准（GO 子集）：high 92%（11/12）· low 100%（5/5）
- 近明牌占比：**64/94 = 68%**，胜率 98%（63/64）—— 几乎全是 decoder 判 NO BASIS 的零-edge 盘

---

## 三层裁决（诚实读法，分层否则会误判）

### ① 它不是橡皮图章 —— 这条立住了
全集只 GO 了 17/94，edge-band 更是只 GO 了 **3/30（10%）**。在真五五开的盘里它几乎全程
NO BASIS。这正是"躲过 Starmer"的那条红线保守性，现在被量化了。

### ② +10% 的体面数字，大头是"近明牌幻觉"
68% 的样本是 entry≥0.90 的近明牌盘（胜率 98%）。decoder 对其中 14 个判了 `CHASED`（跟住近乎
确定的赢家）——跟对了，但那是 ~0 edge 的送分题。**全集基线和 GO 子集双双被近明牌抬高**，所以
+10% 不是干净的 edge 判别力。
（拆解：17 个 GO 中，14 个在近明牌区、仅 3 个在 edge-band。）

### ③ 真正的考场是 edge-band，而它给的信号微弱
剔除近明牌后，全集塌到 53%（硬币），这才是 decoder 该证明自己的地方。结果：
- 它 GO 了 3 个，中 2 个（67%）——方向对，但 **N=3，2/3 翻成 1/3 就反号，统计上等于没说**。
- 它躲掉的 27 个里，赢 14（52%）≈ 基线 53%——**在硬盘里它的"别跟"几乎不带方向信息**
  （躲对躲错各半）。Starmer 那种"精准躲一个具体输盘"是逐案真实的，但在聚合层面这批样本里
  **没显现为系统性 edge**。

**裁决**：初步成立，远未盖棺。decoder 确实选择性强、GO 在两切片都跑赢基线（方向对）；但它保守到
在硬盘里几乎不开口（3/30），指标被硬盘 GO 太稀饿死。**binding constraint = "硬盘 GO 稀缺"，
不是样本量本身**——纯扩样本只能线性多挤出几个硬盘 GO，真解法是换 `离场盈亏` 口径（路 B，每笔
round-trip 都是样本、不需持到结算）或专挑 0.4–0.7 建仓的盘（#5）。**绝不为提高 GO 率调松门槛
（红线）——那会同时放大"被假新闻骗"的错误。**

---

## 完整 caveat（随数字一起，不可省）

1. **幸存者偏差**：样本仅含"持到结算者"，系统性排除了提前离场的聪明钱（赢了赎回 / 输了割肉）
   ——这批人可能不典型。对应 #24 世界观。
2. **输家过采**：聪明钱罕少把大额输盘扛到结算，15 个 >$5k 输家是过采的稀有滞留者，代表性有限
   （且其中 7 个来自单一多候选人选举 Virginia AG —— 多候选人选举是输家唯一稳定的蓄水池：
   押错候选人的人无法赎回、被迫持到结算）。
3. **决定性的 N 极小**：全集 N=94 不算小，但真正回答问题的 **edge-band GO 子集只有 3** ——
   **这是初步信号，不是定论**。
4. **方向胜率对 edge 盲**：近明牌赢家虚高基线，decoder 正确判 NO BASIS 却被记为"漏掉赢家"
   → 拉低 lift；低/负 lift 可能是 decoder 正确回避零 edge，而非失手。真口径是"跟它能赚多少钱"
   （`离场盈亏`，v3 / #25 / #26），不是"方向对不对"。

---

## 附带确认的 v2 成果

**路 A 取样管道跑通且能放量**：N 从 v1 的 **6 → 94**（27 盘）。Step 2"市场优先取样"破样本稀缺
这条路**验证成立**——不再赌单个钱包有没有已结算政治盘，直接从已结算政治盘反查大持仓者，每个
（>$5k 持有者 × 已结算盘）= 一个保底样本。

---

## 原始扫描日志（27 盘 · 证据留存）

> 列：市场 | 该盘实际取样数（部分候选 decode 返回 None 被跳过）（输候选/赢候选）| 累计输家。
> 注意"输家"高度集中在多候选人选举（Virginia AG 一盘贡献 7），印证 caveat ②。

```
  Where will the next US-Iran di | 该盘取 2（输0/赢2）| 累计输家 0
  Virginia Attorney General Elec | 该盘取 10（输7/赢4）| 累计输家 7   ← 输家蓄水池
  Jerome Powell out as Fed Chair | 该盘取 4（输0/赢4）| 累计输家 7
  Maine Presidential Election Wi | 该盘取 4（输0/赢4）| 累计输家 7
  AfD % of vote in German Electi | 该盘取 4（输0/赢4）| 累计输家 7
  US x Cuba diplomatic meeting b | 该盘取 0（输1/赢4）| 累计输家 7   ← 1输家 decode 失败被跳
  Turnout in 2025 Honduran Gener | 该盘取 1（输0/赢1）| 累计输家 7
  Wyoming Presidential Election  | 该盘取 2（输0/赢2）| 累计输家 7
  Next Prime Minister of Nepal   | 该盘取 1（输0/赢2）| 累计输家 7
  Will the Virginia redistrictin | 该盘取 4（输1/赢4）| 累计输家 8
  Will Israel allow independent  | 该盘取 4（输0/赢4）| 累计输家 8
  Ohio Presidential Election Win | 该盘取 4（输0/赢4）| 累计输家 8
  Biden drops out by July 12?    | 该盘取 5（输2/赢4）| 累计输家 10
  Will Israel strike Syria by... | 该盘取 4（输0/赢4）| 累计输家 10
  U.S. recognizes Machado as lea | 该盘取 4（输0/赢4）| 累计输家 10
  Iran agrees to end enrichment  | 该盘取 2（输0/赢2）| 累计输家 10
  Kevin Warsh formally nominated | 该盘取 3（输0/赢3）| 累计输家 10
  # of jobs Elon and DOGE cut in | 该盘取 2（输1/赢1）| 累计输家 11
  U.S. Government Funding Lapse  | 该盘取 4（输0/赢4）| 累计输家 11
  # of seats Liberals win in Can | 该盘取 3（输0/赢3）| 累计输家 11
  U.S. tariff rate on China on N | 该盘取 6（输2/赢4）| 累计输家 13
  Elon Musk # tweets May 9 - May | 该盘取 1（输0/赢4）| 累计输家 13
  Which party wins most seats in | 该盘取 2（输0/赢2）| 累计输家 13
  US inauguration on January 20? | 该盘取 4（输0/赢4）| 累计输家 13
  Nicolás Maduro seen in public  | 该盘取 4（输0/赢4）| 累计输家 13
  Biden removed via 25th Amendme | 该盘取 5（输1/赢4）| 累计输家 14
  Trump, Putin, and Zelensky mee | 该盘取 5（输1/赢4）| 累计输家 15
```

汇总：N=94（79W / 15L），27 盘，GO 17 / 躲 77。
