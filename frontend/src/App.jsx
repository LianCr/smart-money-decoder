import { useState, useEffect } from "react";
import { useLang, LangToggle } from "./i18n.jsx";
import { API } from "./utils/config.js";
import { SiteFooter } from "./components/SiteFooter.jsx";
import { BoardView } from "./views/BoardView.jsx";
import { TrackRecordView } from "./views/TrackRecordView.jsx";

export default function App() {
  // 两个面：统一看板(home) + Track Record。旧 Decode/Briefing/Context 已存档、不再入导航。
  const [tab, setTab] = useState("board");
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
        <div className="brand" onClick={() => setTab("board")} title={t("回到统一看板")}>
          <span className="dot" />SMART MONEY DECODER
        </div>
        <div className="topnav">
          <button
            className={`navbtn primary ${tab === "board" ? "active" : ""}`}
            onClick={() => setTab("board")}
            title={t("v3 统一看板：身份+这一注+实时盘面+行为×催化剂+Edge 一屏看全")}
          >
            ★ {t("统一看板")}<span className="navbtn-tag">v3</span>
          </button>
          <button
            className={`medal ${tab === "track" ? "active" : ""}`}
            onClick={() => setTab(tab === "track" ? "board" : "track")}
            title={tab === "track" ? t("返回统一看板") : t("查看历史战绩")}
          >
            [ TRACK RECORD:&nbsp;<span className="m-w">{wl.w}W</span> · <span className="m-l">{wl.l}L</span>&nbsp;]
            <span className="m-arrow">↗</span>
          </button>
          <LangToggle />
        </div>
      </div>
      {tab === "track" ? <TrackRecordView /> : <BoardView />}
      <SiteFooter />
    </div>
  );
}
