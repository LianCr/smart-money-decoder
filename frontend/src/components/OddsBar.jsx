import { useLang } from "../i18n.jsx";

// 原生赔率条（替代 Polymarket iframe）：Yes/No 比例条，高亮钱包押的那一侧
export function OddsBar({ held, side, slug }) {
  const { t } = useLang();
  if (typeof held !== "number") return <div className="ctx-empty">{t("无价,赔率不可显")}</div>;
  const S = (side || "").toUpperCase();
  const yesP = S === "NO" ? 1 - held : held;          // held=持有侧价；换算 Yes/No
  const noP = 1 - yesP;
  const yesHeld = S === "YES";
  return (
    <div className="oddsbar">
      <div className="ob-bar">
        <div className={`ob-seg yes ${yesHeld ? "held" : "dim"}`} style={{ width: `${Math.max(yesP * 100, 8)}%` }}>
          <span className="ob-lab">Yes</span><span className="ob-val num">{Math.round(yesP * 100)}¢</span>
        </div>
        <div className={`ob-seg no ${!yesHeld ? "held" : "dim"}`} style={{ width: `${Math.max(noP * 100, 8)}%` }}>
          <span className="ob-lab">No</span><span className="ob-val num">{Math.round(noP * 100)}¢</span>
        </div>
      </div>
      <div className="ob-foot">
        <span>{t("他押")} <b className={yesHeld ? "ob-yes" : "ob-no"}>{S}</b> {t("· 高亮侧")}</span>
        {slug && <a className="ob-jump" href={`https://polymarket.com/market/${slug}`} target="_blank" rel="noreferrer">{t("在 Polymarket 打开 ↗")}</a>}
      </div>
    </div>
  );
}
