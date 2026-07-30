import { useState, useEffect, useRef } from "react";
import { useLang, registerAiTranslations } from "../i18n.jsx";
import { API } from "../utils/config.js";
import { money, abbrev } from "../utils/format.jsx";
import { CONF_CN } from "../utils/labels.js";

// 扫榜推荐（免费扫榜层）：点一个直接 decode
const BEH_ICON = { ADD: "📈", EXIT: "📉", STATIC: "⏸" };

const CALL_CN = { "ROOM LEFT": "还有空间", CHASED: "太迟了", "NO BASIS": "没依据" };

// 信心值 → CSS 变体类。⑥ 输出既有 "med"(market_thesis 归一) 也有 "medium"(v2/v3 矩阵)，
// 之前直接把原始值当 class 用 → "med" 无样式命中、文字回落到按钮默认深色 = 深底上看不见。
const CONF_CLS = { high: "high", medium: "medium", med: "medium", low: "low" };

export function Recommendations({ onPick }) {
  const { t, lang } = useLang();
  const [data, setData] = useState(null);
  const [scanSecs, setScanSecs] = useState(0);
  const pollRef = useRef(null);
  useEffect(() => {
    fetch(`${API}/recommendations`).then((r) => r.json())
      .then((j) => { registerAiTranslations(j.i18n_en); setData(j); }).catch(() => {});
    return () => clearInterval(pollRef.current);
  }, []);
  const refreshing = !!(data && data.refreshing);
  useEffect(() => {                                   // 扫榜期间：10s 轮询 + 计时
    clearInterval(pollRef.current);
    if (!refreshing) return;
    const t0 = Date.now();
    pollRef.current = setInterval(() => {
      setScanSecs(Math.floor((Date.now() - t0) / 1000));
      fetch(`${API}/recommendations`).then((r) => r.json())
        .then((j) => { registerAiTranslations(j.i18n_en); setData(j); }).catch(() => {});
    }, 10000);
    return () => clearInterval(pollRef.current);
  }, [refreshing]);
  function rescan() {
    if (refreshing) return;
    if (!window.confirm(t("重新扫榜会重跑全流程找最新推荐（几分钟、AI 验证消耗 token 额度）。确定？"))) return;
    setScanSecs(0);
    fetch(`${API}/recommendations?refresh=1`).then((r) => r.json())
      .then((j) => { registerAiTranslations(j.i18n_en); setData(j); }).catch(() => {});
  }
  const cands = (data && data.candidates) || [];
  if (!cands.length && !refreshing) return null;
  return (
    <div className="recs">
      <div className="recs-h">{t("值得看的聪明钱 ·")} <b>{t("政治盘专家")}</b>{t("（从热门政治盘反向找的共持大户 · 政治专长筛 · ∩月榜）")}<span className="recs-sub">{t("点一个直接 decode")}</span>
        {data.generated_at && !refreshing && (
          <span className="recs-updated num">{t("更新于")} {new Date(data.generated_at * 1000).toLocaleString(lang === "en" ? "en-US" : "zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })}</span>
        )}
        <button className="recs-refresh" onClick={rescan} disabled={refreshing}
          title={t("重扫热门政治盘找最新的值得看钱包（几分钟 + AI 验证烧 token）")}>
          {refreshing ? `⟳ ${t("扫榜中")}… ${scanSecs}s` : `↻ ${t("刷新推荐榜")}`}
        </button>
      </div>
      {data && data.refresh_error && <div className="recs-err">⚠ {t("上次刷新失败：")}{data.refresh_error}</div>}
      <div className="recs-list">
        {cands.map((c, i) => {
          const pw = c.politics_win_rate;
          const pwTxt = pw != null ? (pw <= 1 ? Math.round(pw * 100) : Math.round(pw)) + "%" : null;
          return (
            <button className={`rec ${c.ai_pick ? "pick" : ""}`} key={i} onClick={() => onPick(c.wallet)}>
              <div className="rec-top">
                {c.ai_pick && <span className="rec-aibadge">{t("AI 精选")}</span>}
                <span className="rec-addr num">{abbrev(c.wallet)}</span>
                {c.cross_ref_579 && <span className="rec-cross">{t("∩月榜")}</span>}
                {c.tier && <span className="rec-tier">{c.tier}</span>}
                {c.h_score != null && <span className="rec-h num">H{Math.round(c.h_score)}</span>}
              </div>
              {c.politics_pnl != null && (
                <div className="rec-pol">{t("政治盘")} <b className="num">{money(c.politics_pnl)}</b>{pwTxt && <span> · {t("胜率")} {pwTxt}</span>}{c.politics_trades && <span> · {c.politics_trades} {t("注")}</span>}</div>
              )}
              <div className="rec-q">{c.market_question} <span className="rec-side">· {t("押")} {c.outcome}</span></div>
              {c.disagreement && (
                <div className="rec-disagree">{t("⚠ 聪明钱在此盘分歧（正反都有人押）")}
                  {c.disagreement_lean && <span className={c.disagreement_with_edge ? "with" : "against"}> · {t("我们独立倾向")} <b>{c.disagreement_lean}</b> → {t("这注")}{t(c.disagreement_with_edge ? "顺 edge" : "逆 edge")}</span>}
                </div>
              )}
              {c.consensus_count >= 2 && (
                <div className="rec-consensus">🤝 {c.consensus_count} {t("个政治专家同押此方向（弱信号 · 技能共识非盈亏 · 仍有羊群风险）")}</div>
              )}
              {c.source_market && <div className="rec-src">{t("↳ 从「")}{c.source_market}{t("」共持发现")}</div>}
              <div className="rec-beh">{BEH_ICON[c.behavior] || "·"} {t(c.behavior_fact) || c.behavior || "—"}</div>
              {c.ai_pick && (c.ai_confidence || c.ai_follow_call || c.ai_verdict) && (
                <div className="rec-verdict">
                  {c.ai_confidence && (
                    <span className={`rec-conf ${CONF_CLS[c.ai_confidence] || ""}`}>⑥ {t(CONF_CN[c.ai_confidence] || c.ai_confidence)} {t("信心")}</span>
                  )}
                  {c.ai_follow_call && <span className="rec-call">{t(CALL_CN[c.ai_follow_call] || c.ai_follow_call)}</span>}
                  {c.ai_verdict && <span className="rec-verdict-txt">{t(c.ai_verdict)}</span>}
                </div>
              )}
            </button>
          );
        })}
      </div>
      <div className="recs-foot">{t("扫榜=值得一看，")}<b>{t("不是\"该跟\"")}</b>{t(" · 高盈利 ≠ 下一注好（过去≠未来）· 这注本身好不好由点开后的 ⑥ 判 ")}{data.as_of && `· ${t("截至")} ${data.as_of}`}</div>
    </div>
  );
}
