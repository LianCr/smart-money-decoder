import { useState, useEffect, useRef } from "react";
import { useLang, ZhNote } from "../i18n.jsx";
import { CONF_LABEL } from "../utils/labels.js";

// ── Track Record 回测页 ─────────────────────────────────────────────────────
const CALL_PLAIN = { "NO BASIS": "别跟", CHASED: "可跟·已追高", "ROOM LEFT": "可跟·有空间" };

const CALL_CLS = { "NO BASIS": "red", CHASED: "amber", "ROOM LEFT": "green" };

export function CaseRow({ c }) {
  const { t } = useLang();
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const [h, setH] = useState(0);
  useEffect(() => { setH(open && ref.current ? ref.current.scrollHeight : 0); }, [open]);

  const verdict = t(CALL_PLAIN[c.t1.call] || c.t1.call);
  const concl = c.ai_correct ? (c.hero ? t("✓ AI 帮你躲过这笔亏损") : t("✓ AI 判断正确")) : t("✗ AI 失手");
  const tps = [["T-7", c.t7], ["T-1", c.t1]];

  return (
    <div className={`bt-item ${open ? "open" : ""} ${c.hero ? "hero" : ""}`}>
      <div className="bt-row" onClick={() => setOpen(!open)}>
        <div className="bt-left">
          <div className="bt-q">{c.hero && <span className="hero-star">★ </span>}{c.market}</div>
          <div className="bt-tags">
            <span className={`stance ${CALL_CLS[c.t1.call] || "gray"}`}>{t("AI 当时判")} <b>{verdict}</b></span>
            <span className="resolved big">{t("真实：")}{c.bet_won ? t("钱包赢了") : t("钱包赌输了")}</span>
          </div>
        </div>
        <div className="bt-right">
          <span className={c.ai_correct ? "verd hit" : "verd miss"}>{c.ai_correct ? "✓" : "✗"}</span>
          <span className={`chev ${open ? "up" : ""}`}>›</span>
        </div>
      </div>

      <div className="bt-drawer" style={{ height: h }}>
        <div className="bt-drawer-inner" ref={ref}>
          <div className="case-concl">{concl} · {t("市场结算")} {c.resolved}（{c.resolved_date}）</div>
          <div className="case-take">{t(c.takeaway)}</div>

          <div className="case-evo">
            {tps.map(([lab, pt], i) => (
              <span className="evo-step" key={lab}>
                <span className="evo-lab">{lab}</span>
                <span className={`mini-follow ${CALL_CLS[pt.call] || "gray"}`}>{t(CALL_PLAIN[pt.call] || pt.call)}</span>
                {i === 0 && <span className="evo-arrow">→</span>}
              </span>
            ))}
          </div>

          {tps.map(([lab, pt]) => (
            <div className="case-tp" key={lab}>
              <div className="case-tp-h">{lab} · {pt.date} · {t("信心")} {CONF_LABEL[pt.conf] || pt.conf}</div>
              <ul className="case-cat">{pt.catalysts.map((cat, j) => <li key={j}>{t(cat)}</li>)}</ul>
              <div className="case-reason"><span className="case-reason-lab">{t("AI 当时推理")}<ZhNote text={pt.reasoning} /></span>{t(pt.reasoning)}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
