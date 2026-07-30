import { useLang, ZhNote } from "../i18n.jsx";
import { renderInline } from "../utils/format.jsx";
import { CONF_CN, FOLLOW_LABEL_CN } from "../utils/labels.js";
import { CredBadge } from "./CredBadge.jsx";

// 状态灯配色（🔴 守魂#4：判断非买入信号——CHASED 用 amber 表"谨慎,好价过了",不用红"别买";NO BASIS 灰=中性）
const LIGHT_CLS = { "ROOM LEFT": "green", CHASED: "amber", "NO BASIS": "grey" };

const cent = (v) => (typeof v === "number" ? Math.round(v * 100) + "¢" : "—");

// 把代码降级原因（R2/底座矩阵/pnl…）翻成人话（守协作纪律#5：弱化不删，原文仍在审计脚注）
function reasonCN(s, t = (x) => x) {
  s = String(s || "");
  if (s.startsWith("底座矩阵")) {
    const m = s.match(/底座矩阵:(\w+)\(pnl=([^)]+)\)/);
    const conf = m ? t({ high: "高", medium: "中", low: "低" }[m[1]] || m[1]) : "";
    const pnl = m ? m[2] : "—";
    return { tag: t("起步"), txt: `${t("按他这注的浮盈(")}${pnl}${t(")和单边/证据情况，矩阵起步给「")}${conf}${t("」")}` };
  }
  if (s.startsWith("R1")) return { tag: t("市场测谎"), txt: s.includes("全部") ? t("他押的方向有支持新闻，但市场全程反着定价（不买账）→ 打到低") : t("他押的方向有支持新闻被市场部分反着定价 → 压到中") };
  if (s.startsWith("R2")) return { tag: t("对冲"), txt: t("他两边都压了不少（像在做市/对冲），不是单边信念 → 信心压到中") };
  if (s.startsWith("R3")) return { tag: t("退出"), txt: t("近 48 小时他在大额减仓离场 → 信心压到中") };
  if (s.startsWith("R4")) return { tag: t("证据双空"), txt: t("支持和威胁两边都没找到对题证据 → 打到低") };
  return { tag: "", txt: s };
}

// 首屏判断英雄区：结论先行，0.5 秒拿到"还能不能跟"
export function VerdictHero({ d }) {
  const { t } = useLang();
  const r = d.reasoning || {};
  const pos = d.position || {};
  const m = pos.meta || {};
  const wpa = pos.what_position_actions || {};
  const act = wpa.actions || {};
  const un = wpa.unrealized || {};
  const pc = pos.price_context || {};
  const id = d.identity || {};
  const profile = { ...(id.profile || {}), address: id.profile?.address || d.wallet };
  const rk = (id.who_trader_profile || {}).official_rank || {};
  const side = (m.analyzed_side || "").toUpperCase();
  const cls = r.follow_call ? (LIGHT_CLS[r.follow_call] || "grey") : "grey";
  const upct = un.unrealized_pct;
  const gain = typeof upct === "number"
    ? upct >= 0
    : (typeof pc.current_price === "number" && typeof act.avg_entry_price === "number"
        ? pc.current_price >= act.avg_entry_price : true);
  const dirCls = gain ? "pos" : "neg";

  // ⑥ 体检 chip（纯前端代码算，不改 AI 输出、不拦截——"不加守卫≠不可观测"的界面化）
  const advisories = [];
  if (pos.near_settled) {
    advisories.push(`${t("⚠ 近结算盘：该钱包整本政治仓位都推到了 ≥95¢（持有侧现价")} ${Math.round((pos.held_price || 0) * 100)}¢${t("）——无悬念、无跟单价值，这里如实展示他最大的那注")}`);
  }
  if (r.market_lean && r.thesis_audit) {
    const nArt = r.thesis_audit.n_articles;
    if (typeof nArt === "number" && nArt < 3) advisories.push(`${t("⚠ 证据薄：共享文章池仅")} ${nArt} ${t("篇，裁决人输入有限")}`);
    const conf = String(r.confidence || "").toLowerCase();
    if (conf === "high" && typeof r.lean_strength === "number" && r.lean_strength < 60)
      advisories.push(t("⚠ 信心与倾向强度不符：高信心但证据压倒性 <60/100，谨慎采信"));
  }

  return (
    <div className="vh">
      <div className="vh-top">
        <div className="vh-q">{m.market} <span className="vh-side">· {t("押")} {side}</span></div>
        <CredBadge profile={profile} rk={rk} pnlHistory={id.pnl_history} />
      </div>

      {(pos.what_the_bet || pos.resolution_criteria) && (
        <div className="db-whatbet vh-whatbet">
          <div className="db-whatbet-h">{t("这一注在赌什么")} <ZhNote text={pos.what_the_bet} /></div>
          {pos.what_the_bet && <div className="db-whatbet-t">{renderInline(t(pos.what_the_bet))}</div>}
          {pos.resolution_criteria && (
            <details className="db-rc">
              <summary>{t("官方结算规则原文（什么算赢）")}</summary>
              <div className="db-rc-body">{pos.resolution_criteria}</div>
            </details>
          )}
        </div>
      )}

      <div className="vh-essence">
        <div className="vh-e"><span>{t("入场成本")}</span><b className="vh-from num">{cent(act.avg_entry_price)}</b></div>
        <span className="vh-arrow">→</span>
        <div className="vh-e vh-e-main">
          <span>{t("现价 · 隐含概率")}</span>
          <div className="vh-now-row">
            <b className={`vh-now num ${dirCls}`}>{cent(pc.current_price)}</b>
            {typeof upct === "number" && (
              <span className={`vh-delta ${dirCls}`}>{upct >= 0 ? "▲" : "▼"} {upct >= 0 ? "+" : ""}{upct}%</span>
            )}
          </div>
        </div>
        <div className="vh-e vh-room"><span>{t("剩余空间(若赢)")}</span><b className="num">{pc.remaining_upside_pct_if_win != null ? pc.remaining_upside_pct_if_win + "%" : "—"}</b></div>
      </div>

      {r.guard_tripped ? (
        <div className="vh-light guard"><span className="vh-call">{t("🛡 守卫拦截")}</span>
          <span className="vh-conf">{t("该判断触发诚实守卫,不输出结论")}</span></div>
      ) : (
        <div className={`vh-light ${cls}`}>
          <span className="vh-dot" />
          <span className="vh-call">{t(FOLLOW_LABEL_CN[r.follow_call] || r.follow_call || "—")}</span>
          <span className="vh-conf">{t("信心")} <b>{t(CONF_CN[r.confidence] || r.confidence || "—")}</b></span>
        </div>
      )}

      {r.confidence_source === "fallback_v2_matrix" && !r.guard_tripped && (
        <div className="vh-fallback">{t("⚠ 市场级推理暂不可用，本次信心来自旧的代码矩阵（锚钱包盈亏），参考价值打折")}</div>
      )}

      {r.market_lean && (
        <div className="vh-edge">
          {t("市场倾向")} <b>{r.market_lean}</b>{r.lean_strength != null && <span className="vh-edge-str"> {r.lean_strength}/100</span>}
          {r.alignment && <span className={`vh-align ${r.alignment.includes("逆") ? "against" : "with"}`}> · {t("这一注")} {t(r.alignment)}</span>}
          {r.event_structure && r.event_structure.multi && (
            <span className="vh-multi" title={t("多结局事件：隐含概率是「此候选 vs 全场」，非二元 Yes/No")}>
              · {t("多结局")} {r.event_structure.n_candidates} {t("选 1（基线")} {r.event_structure.baseline_pct}%）
            </span>
          )}
        </div>
      )}

      {advisories.length > 0 && (
        <div className="vh-advisories">
          {advisories.map((a, i) => <span className="vh-advisory" key={i}>{a}</span>)}
        </div>
      )}

      <div className="vh-verdict">{r.guard_tripped ? r.guard_message : t(r.reasoning)}{!r.guard_tripped && r.reasoning && <ZhNote text={r.reasoning} />}</div>

      {!r.guard_tripped && r.pivotal_unknown && (
        <div className="vh-pivotal">{t("⚖ 胜负手：")}{t(r.pivotal_unknown)}</div>
      )}

      {!r.guard_tripped && r.market_lean && r.thesis_audit && (
        <details className="vh-audit">
          <summary>{t("信心怎么来的？（多空对抗 → 中立裁决，单一信心直出）")}</summary>
          {r.input_trust && r.input_trust.length > 0 && (
            <div className="vh-trust">
              <div className="vh-trust-h">{t("输入可信度（决定价格/证据该信几分）")}</div>
              {r.input_trust.map((l, i) => <div className="vh-trust-l" key={i}>· {t(l)}</div>)}
            </div>
          )}
          <div className="vh-audit-th"><b>{t("多头(押 YES)：")}</b>{t(r.thesis_audit.bull)}</div>
          <div className="vh-audit-th"><b>{t("空头(押 NO)：")}</b>{t(r.thesis_audit.bear)}</div>
          <div className="vh-audit-foot">{t("↑ 同一市场只算一次、两个反向钱包共享同一份市场观；信心由裁决人直出、不锚钱包盈亏 · 已记日志，待盘结算回验是否真命中")}</div>
        </details>
      )}

      {!r.guard_tripped && !r.market_lean && r.confidence_reasons && r.confidence_reasons.length > 0 && (
        <details className="vh-audit">
          <summary>{t("为什么是「")}{t(CONF_CN[r.confidence] || r.confidence)}{t("」信心？（点开看代码怎么算的）")}</summary>
          <ul className="vh-audit-list">
            {r.confidence_reasons.map((s, i) => {
              const rc = reasonCN(s, t);
              return <li key={i}>{rc.tag && <span className="vh-audit-tag">{rc.tag}</span>}{rc.txt}</li>;
            })}
          </ul>
          <div className="vh-audit-foot">{t("↑ 代码置信度矩阵逐条算（只降不升）、AI 不改判 · 原始：")}{r.confidence_reasons.join(" · ")}</div>
        </details>
      )}

      {d.behavior && <div className="vh-whale">{t("🐳 巨鲸动态 ·")} {t(d.behavior.fact)}</div>}
      <div className="vh-disc">{t("这是对\"局势性质\"的判断(还有多少空间/风险在哪/市场认不认这个方向),不替你决定跟不跟 · 天平由你裁决")}</div>
    </div>
  );
}
