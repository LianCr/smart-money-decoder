"""
scoring/constants.py — 🔴 判断阈值唯一正本（T2.2 收编 P2-18 的散落魔数）

这些数字共同定义了产品的判断行为。规矩：
  · 判断阈值（决定"算不算/信不信/推不推"）只在这里定义，使用方 import——
    别处再写同义字面量 = tests/test_scoring_layer.py 的源码扫描会红。
  · infra 配置（限流/超时/翻译预算/API 调用预算/缓存路径）**刻意不收**——
    那些决定的是"跑多快/花多少"，不是"怎么判断"，留在 core/config.py 或模块本地
    （如 fetcher/positions.MAX_PRICE_CHECKS、core/translate.MAX_TOTAL_CHARS）。
  · `CONF_VALUES`（market_thesis 的 LLM 输出清洗枚举）也不收：那是解析容错面，
    不是判断阈值。
每条带来源注释：从哪个文件收来、什么含义、谁标定的。改任何一条 = 改产品判断行为，
过既有边界测试（test_credibility / test_reasoner_v3 / test_scoring_layer 等）才算数。
"""
import os

# ── 置信度矩阵带（v2=scoring/matrix_v2 · v3=scoring/reasoner_v3 共用；CLAUDE.md 定稿矩阵）──
# pnl_pct 是百分比数值（0.58 = 0.58%），阈值直接用 30/60
PNL_HIGH_MAX = 30            # 0 ≤ pnl < 30 → high（浮盈还没被吃透）
PNL_LOW_MIN  = 60            # pnl > 60 → low（涨幅已被吃透）；30-60 之间 → medium
CONF_ORDER = {"low": 0, "medium": 1, "high": 2}   # 只降不升的排序基准（reasoner_v3 R1-R4）

# ── reasoner v3 逐条降级（analyzer 时代 :64/:122 收来）──
R2_HEDGE_MULT = 3            # R2：主仓 shares < 另一侧×3 = 两侧均衡（对冲/做市）→ 封 medium
MM_TWO_SIDE_RATIO = 0.5      # classify_position_type：小侧/大侧 ≥ 0.5 = 做市/对冲玩家

# ── follow_call（services/dashboard_build._code_follow_call 收来，原 api/main :371）──
FOLLOW_CALL_ENUM = {"ROOM LEFT", "CHASED", "NO BASIS"}   # 正本（guards re-export 保旧 import 链）
CHASED_MOVED_PCT = 8         # 入场后价已走 ≥8% → CHASED（追高）；判定本质是价格位移数学（红线 5）

# ── 市场反应（price_reaction 收来；board_feed 曾有同口径重复常量 REACT_THRESHOLD，已消灭）──
MEANINGFUL_MOVE_PCT = 5.0    # 新闻前后价格变动 <5% = 反应微弱，不触发矛盾旗标（防噪音误报）

# ── 输入可信度门（575/568 指标分档；market_thesis.price_credibility 与 scoring.credibility 共用——
#    曾是两处重复字面量，T2.2 合并；F4 首版标定，对三份真实政治盘 sanity 过）──
LIQ_PCT_LOW, LIQ_PCT_MID = 50, 85    # 流动性百分位：<50 薄盘 / ≥85 深盘（thesis 的 great 门同值）
PART_LOW, PART_MID = 30, 80          # 近 7 天独立参与人数：<30 = 几个人的赌局 / ≥80 = 人群
CONC_TOP1, CONC_TOP10 = 35, 70       # 头部集中度 %：top1≥35 或 top10≥70 = 价格是少数人的意见
VOLA_HIGH, VOLA_MID = 0.12, 0.06     # 已实现日波动：≥0.12 市场没拿定 / <0.06 共识已稳（沿用 realized_vol 原阈值）

# ── credibility 扣分表（F4，analyzer/credibility 收来；起点 100 只扣不加、每项设上限防重复计罪）──
LIQ_D_LOW, LIQ_D_MID, LIQ_D_FLAG, LIQ_CAP = -25, -10, -10, -25
CONC_D_TOP1, CONC_D_TOP10, CONC_D_WHALE, CONC_D_TRADE, CONC_D_SQUEEZE, CONC_CAP = -15, -10, -15, -10, -5, -30
PART_D_LOW, PART_D_MID = -20, -10
VOLU_D_COLLAPSE, VOLU_D_DECLINE = -10, -5    # 量能：塌缩 flag / "Significant Decline"
VOLA_D_HIGH, VOLA_D_MID = -15, -5
AGE_YOUNG_DAYS = 3           # T1（2026-08-07）：开盘 <3 天=价格发现未完成（575 created_at，首版标定）
AGE_D_YOUNG = -10
# T2（2026-08-08，572 口簿实测标定：健康政治盘价差 0.3-1¢、单侧深度 $1.5k-$2.8M，
# 实抓到一例薄 bid 侧 $1.5k）：价差宽=定价粗糙；薄侧深度小=一笔就能砸动价格
SPREAD_WIDE = 0.04           # 价差 ≥4¢ = 宽（健康样本 ≤1¢，留 4 倍余量）
SPREAD_D_WIDE = -10
DEPTH_THIN = 2000.0          # 薄侧名义深度 < $2k = 一笔小单可击穿
DEPTH_D_THIN = -10
BOOK_CAP = -15               # 盘口子指标合计上限（防叠罚）
TIERS = ((90, "A"), (75, "B"), (60, "C"), (45, "D"))   # 低于 45 → F
BAD_DELTA = -15              # 单子指标扣到这个量级 → verdict=bad

# ── 信心回验分档（T2.5，core/config 收来——原注释即承诺"T2.2 迁走"）──
# 样本数低于此的信心档不显示命中率百分比（两三个样本的 100%/0% 是误导，宁可不给数字）
REPLAY_MIN_BUCKET_N = int(os.environ.get("REPLAY_MIN_BUCKET_N", "5"))

# ── 多结局判定（market_thesis.event_structure 收来）──
MULTI_OUTCOME_MIN = 3        # 同 event 兄弟市场 ≥3 = 多结局（八选一），隐含概率不可当二元读

# ── 近结算守卫（fetcher/positions 收来，2026-07-09 实测 0xe8dd… NO 农场钱包标定）──
NEAR_SETTLED_PRICE = 0.95    # 持有侧 ≥95¢ = 没悬念，入口跳过找下一个有悬念仓

# ── 社媒有机门（fetcher/social 收来）──
ORGANIC_MIN = 20.0           # author_diversity_pct ≥ 20% 视为有机，否则疑似刷量（585 文档定义）
GENERIC_HIT_FRAC = 0.35      # 返回帖命中率 >35% 的关键词 = OR 拉进来的泛词，剔出相关性门

# ── 扫榜打分权重（recommend.scan 收来；🔴 被验证的体量+胜率为主，ROI 封顶防小样本
#    高方差盖过真鲸鱼——实测 21 注/306% ROI 曾压过 $1.26M 鲸鱼）──
REC_GATE_PNL = 2000.0        # 政治盘净盈利质量门
REC_PNL_SCALE = 20000.0      # 体量分刻度：politics_pnl / 20000
REC_ROI_CAP = 40.0           # ROI 加分封顶
REC_MIN_TRADES = 50          # 胜率只在注数 ≥50（不是运气）时才加分
REC_WINRATE_COEF = 20        # (win_rate - 0.5) × 20
REC_BONUS_579 = 15           # 官方月榜在榜交叉信号
REC_BONUS_ADD = 12           # 48h 行为流 = 加仓
REC_PENALTY_EXIT = -40       # 主力撤退 = 别推

# ── T1 质量门增强（2026-08-07；🔴 只降不升——第三方质量分/反作弊信号只许降级候选）──
FSCORE_LOW = 40              # 584 F-Score(实名 h_score) tier 带：Novice 20-39（官方 docs），<40 = 未及格线
REC_PENALTY_LOW_FSCORE = -15 # 低 F-Score 降级（红线 3：用第三方质量分替代自算胜率；高分绝不加分）
REC_PENALTY_ANOMALY = -25    # 581 反作弊旗标（sybil/timing/胜率异常/仓位波动/完美择时）任一为真 → 一次性降级
ANOMALY_FLAG_KEYS = ("perfect_timing_flag", "position_size_volatility_flag",
                     "suspicious_win_rate_flag", "sybil_risk_flag", "timing_anomaly_flag")
                             # 581 五旗标真名（2026-08-07 探针逐一核实；quality 门与 self_check 共用）
