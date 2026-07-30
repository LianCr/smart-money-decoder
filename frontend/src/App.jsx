import { useState, useEffect } from "react";
import { useLang, LangToggle } from "./i18n.jsx";
import { API } from "./utils/config.js";
import { SiteFooter } from "./components/SiteFooter.jsx";
import { BoardView } from "./views/BoardView.jsx";
import { BriefingView } from "./views/BriefingView.jsx";
import { ContextView } from "./views/ContextView.jsx";
import { DecodeView } from "./views/DecodeView.jsx";
import { TrackRecordView } from "./views/TrackRecordView.jsx";

export default function App() {
  const [tab, setTab] = useState("board");   // 主页=统一看板(推荐流落地处)；Decode 降为存档，仍可经品牌 logo / 统一看板切换键到达
  // 功勋章的 W/L 取回测真值；默认 5/1（当前案例集事实），/backtest 到达后自校正、不闪
  const [wl, setWl] = useState({ w: 5, l: 1 });
  useEffect(() => {
    fetch(`${API}/backtest`).then((r) => r.json()).then((d) => {
      const s = d.summary || {};
      if (typeof s.directional_correct === "number" && typeof s.total === "number")
        setWl({ w: s.directional_correct, l: s.total - s.directional_correct });
    }).catch(() => {});
  }, []);

  const { t } = useLang();
  return (
    <div className="shell">
      <div className="topbar">
        <div className="brand" onClick={() => setTab("decode")} title={t("回到解读台")}>
          <span className="dot" />SMART MONEY DECODER
        </div>
        <div className="topnav">
          <button
            className={`navbtn primary ${tab === "board" ? "active" : ""}`}
            onClick={() => setTab(tab === "board" ? "decode" : "board")}
            title={t("v3 统一看板：身份+这一注+实时盘面+行为×催化剂+Edge 一屏看全")}
          >
            ★ {t("统一看板")}<span className="navbtn-tag">v3</span>
          </button>
          <button
            className={`navbtn ${tab === "briefing" ? "active" : ""}`}
            onClick={() => setTab(tab === "briefing" ? "decode" : "briefing")}
            title={t("完整聪明钱简报（v3）")}
          >
            {t("完整简报")}<span className="navbtn-tag">v3</span>
          </button>
          <button
            className={`navbtn ${tab === "context" ? "active" : ""}`}
            onClick={() => setTab(tab === "context" ? "decode" : "context")}
            title={t("市场 Context：实时盘面 × as-of 复盘（价格异动 + 催化剂 + 巨鲸动作）")}
          >
            {t("市场Context")}<span className="navbtn-tag">v3</span>
          </button>
          <button
            className={`medal ${tab === "track" ? "active" : ""}`}
            onClick={() => setTab(tab === "track" ? "decode" : "track")}
            title={tab === "track" ? t("返回解读台") : t("查看历史战绩")}
          >
            [ TRACK RECORD:&nbsp;<span className="m-w">{wl.w}W</span> · <span className="m-l">{wl.l}L</span>&nbsp;]
            <span className="m-arrow">↗</span>
          </button>
          <LangToggle />
        </div>
      </div>
      {tab === "decode" ? <DecodeView /> : tab === "board" ? <BoardView />
        : tab === "briefing" ? <BriefingView />
        : tab === "context" ? <ContextView /> : <TrackRecordView />}
      <SiteFooter />
    </div>
  );
}
