import { useLang } from "../i18n.jsx";

const EVT_META = {
  catalyst:   { tag: "催化剂", cls: "cat" },
  price_only: { tag: "诚实留白", cls: "blank" },
  behavior:   { tag: "巨鲸动作", cls: "beh" },
};

export function Timeline({ events }) {
  const { t } = useLang();
  if (!events || !events.length)
    return <div className="ctx-empty">{t("该 as-of 窗内无可锚定的价格异动 / 催化剂 — 如实留空")}</div>;
  return (
    <div className="ctx-timeline">
      {events.map((e, i) => {
        const meta = EVT_META[e.type] || EVT_META.catalyst;
        return (
          <div className={`ctx-evt ${meta.cls}`} key={i}>
            <div className="ctx-evt-rail"><span className="ctx-evt-dot" /></div>
            <div className="ctx-evt-body">
              <div className="ctx-evt-top">
                <span className={`ctx-tag ${meta.cls}`}>{t(meta.tag)}</span>
                <span className="ctx-evt-date num">{e.timestamp}</span>
                {e.price_impact_string && <span className="ctx-impact num">{e.price_impact_string}</span>}
              </div>
              {e.title && <div className="ctx-evt-title">{t(e.title)}</div>}
              <div className="ctx-evt-fact">{t(e.fact_summary)}</div>
              <div className="ctx-evt-foot">
                {e.source && <span className="ctx-evt-src">{e.source}</span>}
                {e.temporal_note && <span className="ctx-evt-note">{t(e.temporal_note)}</span>}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
