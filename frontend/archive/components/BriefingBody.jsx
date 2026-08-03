import { useLang, ZhNote } from "../i18n.jsx";
import { price, money } from "../utils/format.jsx";
import { flagsCN } from "../utils/labels.js";
import { CatColumn } from "./CatColumn.jsx";
import { Narrative } from "./Narrative.jsx";

export function BriefingBody({ d }) {
  const { t } = useLang();
  const m = d.meta || {};
  const who = d.who_trader_profile || {};
  const rk = who.official_rank || {};
  const q = who.quality || {};
  const pol = (who.category_specialization || []).find((c) => /Politics/i.test(c.category || ""));
  const act = (d.what_position_actions || {}).actions || {};
  const ts = (d.what_position_actions || {}).two_side_distribution || {};
  const un = (d.what_position_actions || {}).unrealized || {};
  const pc = d.price_context || {};
  const cats = d.catalysts || { positive: [], negative: [] };
  const wrLie = Number(rk.win_rate) > 0.8 && Number(rk.total_pnl) < 0;
  const upct = un.unrealized_pct;

  return (
    <div className="card bf">
      <div className="c-head">
        <div>
          <div className="q">{m.market}</div>
          <div className="meta">{t(m.settle)} · {t("催化剂锚")} {m.catalyst_anchor === "entry_time" ? t("建仓时(复盘)") : t("现在(实战)")}</div>
        </div>
        <span className="outcome">{(m.analyzed_side || "").toUpperCase()}</span>
      </div>

      {/* WHO / WHAT / PRICE 三联卡 */}
      <div className="bf-grid">
        <div className="bf-mini">
          <div className="bf-mini-h">{t("WHO · 这人靠不靠谱")}</div>
          <div className="bf-kv"><span>{t("官方排名")}</span><b className="num">#{rk.rank ?? "—"}</b></div>
          <div className="bf-kv"><span>{t("胜率 / 累计盈亏")}</span><b className="num">{rk.win_rate ? (rk.win_rate * 100).toFixed(1) + "%" : "—"} · {rk.total_pnl ? money(Number(rk.total_pnl)) : "—"}</b></div>
          {pol && <div className="bf-kv"><span>{t("政治盘专长")}</span><b className="num">{(pol.win_rate * 100).toFixed(0)}% · {money(Number(pol.total_pnl))}</b></div>}
          {wrLie && <div className="bf-lie">{t("⚠ 胜率谎言:高胜率但净盈亏为负 — 看净盈亏,非胜率")}</div>}
          {q.flagged_metrics && <div className="bf-sub">{t("风险标记: ")}{flagsCN(q.flagged_metrics, t)}</div>}
        </div>

        <div className="bf-mini">
          <div className="bf-mini-h">{t("WHAT · 他做了什么")}</div>
          <div className="bf-kv"><span>{t("建仓 / 均价")}</span><b className="num">{act.entry_time?.slice(0, 10) || "—"} · {price(act.avg_entry_price)}</b></div>
          <div className="bf-kv"><span>{t("买入 / 成本")}</span><b className="num">{act.num_buys ?? "—"}{t("笔")} · {money(act.net_cost_usd)}</b></div>
          <div className="bf-kv"><span>{t("盈亏")}</span><b className={`num ${Number(un.unrealized_pnl_usd) >= 0 ? "pos" : "neg"}`}>{money(un.unrealized_pnl_usd)} {typeof upct === "number" ? `(${upct >= 0 ? "+" : ""}${upct}%)` : ""}</b></div>
          <div className="bf-note">{ts.hedged ? t("两边对冲 · 做市/非单边信念") : t("单边建仓 · 信念注")}</div>
        </div>

        <div className="bf-mini">
          <div className="bf-mini-h">{t("PRICE · 还有没有空间")}</div>
          <div className="bf-kv"><span>{t("现价 / 隐含概率")}</span><b className="num">{price(pc.current_price)} · {pc.implied_probability_pct}%</b></div>
          <div className="bf-kv"><span>{t("剩余空间(赢)")}</span><b className="num">{pc.remaining_upside_pct_if_win}%</b></div>
          <div className="bf-kv"><span>{t("赔率 / vs入场")}</span><b className="num">{pc.odds_to_one ?? "—"} · {typeof pc.price_delta_pct === "number" ? (pc.price_delta_pct >= 0 ? "+" : "") + pc.price_delta_pct + "%" : "—"}</b></div>
        </div>
      </div>

      {/* 双向催化剂 + 市场测谎 */}
      <div className="bf-dialectic">
        <CatColumn title="支持 · 正向证据" side="pos" items={cats.positive || []} />
        <CatColumn title="威胁 · 负向证据" side="neg" items={cats.negative || []} />
      </div>

      {/* 第三个 AI 诚实整理（产品魂） */}
      <div className="bf-narr-wrap">
        <h4>{t("AI 诚实整理 · 只陈列证据,不替你判断")} <ZhNote text={d.organized_text} /></h4>
        <Narrative text={t(d.organized_text)} />
      </div>

      <div className="foot">{t("仅为公开数据 AI 整理,非投资建议")}</div>
    </div>
  );
}
