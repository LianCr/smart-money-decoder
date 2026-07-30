import { useLang, ZhNote } from "../i18n.jsx";
import { price, money } from "../utils/format.jsx";
import { flagsCN } from "../utils/labels.js";
import { BehaviorFlag } from "./BehaviorFlag.jsx";
import { Fold } from "./Fold.jsx";
import { GodModeTimeline } from "./GodModeTimeline.jsx";
import { Narrative } from "./Narrative.jsx";
import { NewsStream } from "./NewsStream.jsx";
import { OddsBar } from "./OddsBar.jsx";
import { PnlChart } from "./PnlChart.jsx";
import { SocialPulse } from "./SocialPulse.jsx";
import { VerdictHero } from "./VerdictHero.jsx";

export function BoardBody({ d }) {
  const { t } = useLang();
  const id = d.identity || {};
  const who = id.who_trader_profile || {};
  const rk = who.official_rank || {};
  const q = who.quality || {};
  const pos = d.position || {};
  const m = pos.meta || {};
  const wpa = pos.what_position_actions || {};
  const act = wpa.actions || {};
  const ts = wpa.two_side_distribution || {};
  const un = wpa.unrealized || {};
  const pc = pos.price_context || {};
  const wrLie = Number(rk.win_rate) > 0.8 && Number(rk.total_pnl) < 0;
  const upct = un.unrealized_pct;

  return (
    <div className="card bf db">
      {/* 首屏：结论先行 */}
      <VerdictHero d={d} />

      {/* 局势时间轴（核心视觉，紧跟结论）*/}
      <GodModeTimeline d={d} />
      {d.world_summary && <div className="db-wsum gmt-summary"><ZhNote text={d.world_summary} /><Narrative text={t(d.world_summary)} /></div>}

      {/* 新闻(事实) × 社媒(情绪) 并排 —— 同一问题的两面，视觉刻意分开 */}
      <div className="db-sec-tag">{t("世界发生了什么 × 在怎么议论")}</div>
      <div className="ns-split">
        <div className="ns-col news">
          <div className="ns-col-h"><span className="ns-ico">📰</span>{t("新闻 ·")} <b>{t("事实")}</b><span className="ns-sub">{t("世界发生了什么")}</span></div>
          <NewsStream items={d.news_stream} />
        </div>
        <div className="ns-col social">
          <div className="ns-col-h soc"><span className="ns-ico">💬</span>{t("社媒 ·")} <b>{t("情绪")}</b><span className="ns-sub">{t("小心是情绪、可能刷量")}</span></div>
          <SocialPulse s={d.social} />
        </div>
      </div>
      <div className="ns-diverge">{t("⚖️ 最值钱的对照：新闻在涨 + 社媒在嗨，但 ")}<b>{t("聪明钱（行为流）信不信？市场价跟没跟？")}</b>{t(" 顺风只陈列，背离才是金。")}</div>

      {/* 巨鲸 48h 行为流（折叠）*/}
      <Fold title={t("巨鲸 48h 动作流")} sub={t("加仓 / 减仓 / 没动 + 3h/24h/48h 窗口")}>
        <BehaviorFlag b={d.behavior} />
      </Fold>

      {/* ② 这一注 · 明细 */}
      <div className="db-sec-tag">{t("② 这一注 · 明细")}</div>
      <div className="c-head db-pos-head">
        <div>
          <div className="q">{m.market}</div>
          <div className="meta">{t(m.settle)} · {t("建仓")} {act.entry_time?.slice(0, 10) || "—"}</div>
        </div>
        <span className="outcome">{(m.analyzed_side || "").toUpperCase()}</span>
      </div>
      <div className="bf-grid db-grid">
        <div className="bf-mini">
          <div className="bf-mini-h">{t("动作 · 他做了什么")}</div>
          <div className="bf-kv"><span>{t("均价 / 成本")}</span><b className="num">{price(act.avg_entry_price)} · {money(act.net_cost_usd)}</b></div>
          <div className="bf-kv"><span>{t("买入笔数")}</span><b className="num">{act.num_buys ?? "—"}</b></div>
          <div className="bf-kv"><span>{t("盈亏")}</span><b className={`num ${Number(un.unrealized_pnl_usd) >= 0 ? "pos" : "neg"}`}>{money(un.unrealized_pnl_usd)} {typeof upct === "number" ? `(${upct >= 0 ? "+" : ""}${upct}%)` : ""}</b></div>
          <div className="bf-note">{ts.hedged ? t("两边对冲 · 做市/非单边信念") : t("单边建仓 · 信念注")}</div>
        </div>
        <div className="bf-mini">
          <div className="bf-mini-h">{t("价格 · Entry ↗ Current")}</div>
          <div className="bf-kv"><span>{t("入场 → 现价")}</span><b className="num">{price(act.avg_entry_price)} → {price(pc.current_price)}</b></div>
          <div className="bf-kv"><span>{t("vs 入场 / 隐含概率")}</span><b className="num">{typeof pc.price_delta_pct === "number" ? (pc.price_delta_pct >= 0 ? "+" : "") + pc.price_delta_pct + "%" : "—"} · {pc.implied_probability_pct}%</b></div>
          <div className="bf-kv"><span>{t("剩余空间(赢) / 赔率")}</span><b className="num">{pc.remaining_upside_pct_if_win}% · {pc.odds_to_one ?? "—"}</b></div>
        </div>
      </div>

      {/* ③ 当前赔率 · 原生条（替 iframe）*/}
      <div className="db-sec-tag">{t("③ 当前赔率 · 市场怎么定价")}</div>
      <OddsBar held={pc.current_price} side={(m.analyzed_side || "").toUpperCase()} slug={d.market?.slug} />

      {/* 降级：钱包历史体量（资格审查，不再霸占首屏）*/}
      <Fold title={t("钱包历史体量 · 身份背书")} sub={t("累计盈亏曲线 + 风险标记（背景调查，非本注结论）")}>
        {id.pnl_history && id.pnl_history.length > 1 && <PnlChart points={id.pnl_history} />}
        {wrLie && <div className="bf-lie">{t("⚠ 胜率谎言:高胜率但净盈亏为负 — 看净盈亏,非胜率")}</div>}
        {q.flagged_metrics && <div className="bf-sub db-flags">{t("风险标记: ")}{flagsCN(q.flagged_metrics, t)}</div>}
        <div className="db-id-stats db-id-stats-full">
          <span>{t("官方榜")} <b className="num">#{rk.rank ?? "—"}</b></span>
          <span>{t("胜率")} <b className="num">{rk.win_rate ? (Number(rk.win_rate) * 100).toFixed(1) + "%" : "—"}</b></span>
        </div>
      </Fold>

      <div className="foot">{t("结论由代码矩阵算定信心、AI 只解释不改判 · 价格为市场隐含概率(非胜率) · 公开数据整理,非投资建议")}</div>
    </div>
  );
}
