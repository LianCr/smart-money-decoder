import { useLang } from "../i18n.jsx";
import { FOLLOW_LABEL_CN } from "../utils/labels.js";

// ── 诚实记分牌（装上后累积的真实 decode/看板判断的自我验证）──────────────────
const SC_STATUS = {
  hit: { txt: "✓ 一致", cls: "up" }, miss: { txt: "✗ 不一致", cls: "down" },
  pending: { txt: "待结算", cls: "pending" }, nobasis: { txt: "NO BASIS", cls: "nb" },
};

const SC_SOURCE = { decode: "v2·解读", board: "v3·看板" };

export function LiveScorecard({ sc }) {
  const { t } = useLang();
  if (!sc || sc.error) return null;
  const rate = sc.hit_rate_pct;
  const settledRows = (sc.rows || []).filter((r) => r.status !== "nobasis");
  const nbRows = (sc.rows || []).filter((r) => r.status === "nobasis");
  return (
    <div className="sc">
      <div className="sc-head">
        <div className="sc-title">{t("诚实记分牌 · 我的判断后来被现实证明对了多少")}</div>
        <div className="sc-sub">{t("从装上往后累积的真实 decode / 看板判断 → 盘结算后回来对账。与下方历史回测是两套独立机制。")}</div>
      </div>
      <div className="sc-nums">
        <div className="sc-num"><b className="num">{sc.tested}</b><span>{t("测了")}</span></div>
        <div className="sc-num"><b className="num">{sc.settled}</b><span>{t("已结算")}</span></div>
        <div className="sc-num"><b className="num up">{sc.direction_consistent}</b><span>{t("方向一致")}</span></div>
        <div className="sc-num big"><b className="num">{rate == null ? "—" : rate + "%"}</b><span>{t("命中率")}</span></div>
        <div className="sc-num"><b className="num">{sc.nobasis_total}</b><span>NO BASIS</span></div>
      </div>
      <div className="sc-discipline">{t("命中率 = ")}<b>{t("判断方向命中")}</b>{t("，不是跟单收益率 · NO BASIS 不计入命中率 · 顶上冷数字纯代码算，不经 AI")}</div>

      {sc.tested === 0 ? (
        <div className="sc-empty">{t("还没有记录 — 去解读台 / 统一看板跑几个钱包，判断就会存进档案；等这些盘在数据世界里真结算，这里才长出命中率。第一天空是正常的。")}</div>
      ) : (
        <div className="sc-rows">
          {settledRows.map((r, i) => {
            const st = SC_STATUS[r.status] || SC_STATUS.pending;
            return (
              <div className="sc-row" key={i}>
                <span className="sc-src">{t(SC_SOURCE[r.source] || r.source)}</span>
                <span className="sc-q">{r.market_question}</span>
                <span className="sc-call num">{t("判")} {t(FOLLOW_LABEL_CN[r.follow_call] || r.follow_call)} · {t("押")} {r.outcome}</span>
                <span className={`sc-status ${st.cls}`}>{t(st.txt)}{(r.status === "hit" || r.status === "miss") && r.winner ? ` · ${t("赢家")} ${r.winner}` : ""}</span>
              </div>
            );
          })}
        </div>
      )}

      {sc.nobasis_total > 0 && (
        <div className="sc-nobasis">
          <div className="sc-nobasis-h">{t("NO BASIS 单独区 ·")} {sc.nobasis_total} {t("个（不进命中率）· 其中事后看其实有清晰方向")} <b className="down">{sc.nobasis_clear_in_hindsight}</b> {t("个（当时过谨慎、错过）")}</div>
          {nbRows.map((r, i) => (
            <div className="sc-row nb" key={i}>
              <span className="sc-src">{t(SC_SOURCE[r.source] || r.source)}</span>
              <span className="sc-q">{r.market_question}</span>
              <span className="sc-call num">{t("押")} {r.outcome}</span>
              <span className="sc-status nb">{r.winner ? (r.winner === r.outcome ? t("事后有方向") : t("正确回避")) : t("待结算")}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
