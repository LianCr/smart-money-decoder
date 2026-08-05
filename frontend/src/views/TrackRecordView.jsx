import { useState, useEffect } from "react";
import { useLang } from "../i18n.jsx";
import { API } from "../utils/config.js";
import { CaseRow } from "../components/CaseRow.jsx";
import { LiftSummary } from "../components/LiftSummary.jsx";
import { LiveScorecard } from "../components/LiveScorecard.jsx";
import { ConfidenceCalibration } from "../components/ConfidenceCalibration.jsx";

export function TrackRecordView() {
  const { t } = useLang();
  const [data, setData] = useState(null);
  const [sc, setSc] = useState(null);
  const [crp, setCrp] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    fetch(`${API}/backtest`).then((r) => r.json()).then(setData)
      .catch(() => setError(t("无法连接后端 /backtest")));
    fetch(`${API}/scorecard`).then((r) => r.json()).then(setSc).catch(() => {});
    fetch(`${API}/confidence-replay`).then((r) => r.json()).then(setCrp).catch(() => {});
  }, []);

  const s = (data && data.summary) || {};
  const wrong = (s.total || 0) - (s.directional_correct || 0);
  return (
    <>
      <LiveScorecard sc={sc} />

      <ConfidenceCalibration cr={crp} />

      <div className="sc-divider">{t("↓ 历史回测（v2 已封板·静态零 token，与上方实时记分牌相互独立）")}</div>

      {error ? <div className="error"><div className="r">NETWORK</div><div>{error}</div></div>
       : !data ? <div className="stages"><div className="lead">LOADING TRACK RECORD…</div></div>
       : !data.cases || !data.cases.length ? <div className="method">{t("案例数据缺失（backtest/cases.json 未就位）")}</div>
       : (
        <>
          <div className="tr-hero">
            <div className="tr-hero-num num">
              <span className="up">{s.directional_correct}</span><span className="tr-unit"> {t("对")}</span>
              <span className="tr-slash"> / </span>
              <span className="down">{wrong}</span><span className="tr-unit"> {t("错")}</span>
            </div>
            <div className="tr-hero-txt">
              <div className="tr-hero-h">{t("AI 判断成绩单")}</div>
              <div className="tr-hero-sub">{s.total} {t("个已结算的真实政治盘 · 每个都在结算前重放 AI 当时的判断，跟真实结果对账")}</div>
            </div>
          </div>

          <div className="bt-list">
            {data.cases.map((c, i) => <CaseRow key={i} c={c} />)}
          </div>

          {data.lift && <LiftSummary lift={data.lift} />}

          <div className="foot">{t("案例来自历史回测：结算前重放 decoder、与真实结算对照 · 静态、零 token")}</div>
        </>
      )}
    </>
  );
}
