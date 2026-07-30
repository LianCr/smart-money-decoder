import { useLang, ZhNote } from "../i18n.jsx";
import { abbrev } from "../utils/format.jsx";
import { BehaviorFlag } from "./BehaviorFlag.jsx";
import { Narrative } from "./Narrative.jsx";
import { OddsBar } from "./OddsBar.jsx";
import { Timeline } from "./Timeline.jsx";

export function ContextBody({ d }) {
  const { t } = useLang();
  const mc = d.market_context || {};
  const side = (mc.analyzed_side || "").toUpperCase();
  return (
    <div className="card bf ctx">
      <div className="c-head">
        <div>
          <div className="q">{mc.market_question}</div>
          <div className="meta">{t("市场 Context · 锁定 as-of")} {mc.as_of} · {t("钱包")} {abbrev(mc.wallet)}</div>
        </div>
        <span className="outcome">{side}</span>
      </div>

      <div className="ctx-split">
        {/* 实：实时盘面（Polymarket 直嵌） */}
        <div className="ctx-pane ctx-real">
          <div className="ctx-pane-h"><span className="ctx-live-dot" />{t("当前赔率 · 市场定价")}</div>
          <OddsBar held={mc.current_price} side={mc.analyzed_side} slug={mc.market_slug} />
          <div className="ctx-pane-foot">{t("市场当前对 Yes/No 的定价（高亮=钱包押的侧）· 与右侧 as-of 复盘相互独立")}</div>
        </div>

        {/* 虚：我们合成的 as-of 复盘 Context */}
        <div className="ctx-pane ctx-synth">
          <div className="ctx-pane-h">{t("复盘上下文 · 锁定 as-of")} {mc.as_of}{t("（防泄漏）")}</div>
          <BehaviorFlag b={mc.behavioral_flag} />
          {mc.ai_experimental_summary && (
            <div className="bf-narr-wrap ctx-summary">
              <h4>{t("宏观综述 · 只陈列事实,不替你判断")} <ZhNote text={mc.ai_experimental_summary} /></h4>
              <Narrative text={t(mc.ai_experimental_summary)} />
            </div>
          )}
          <div className="ctx-tl-h">{t("事件时间线 · 价格异动 × 催化剂 × 巨鲸动作")}</div>
          <Timeline events={mc.timeline_events} />
        </div>
      </div>

      <div className="foot">{t("价格异动窗 ≤ as-of(防泄漏) · 催化剂=GDELT 三层洗 · 因果→仅时间相关 · 巨鲸动作=事实非判断 · 仅公开数据 AI 整理,非投资建议")}</div>
    </div>
  );
}
