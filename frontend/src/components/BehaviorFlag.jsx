import { useLang } from "../i18n.jsx";

// ── 市场 Context 视图（一虚一实：实时盘面 × as-of 复盘）──────────────────────
const FLAG_META = {
  ADD:    { icon: "📈", label: "信念增强 · 加仓", cls: "add" },
  EXIT:   { icon: "📉", label: "主力撤退 · 减仓", cls: "exit" },
  STATIC: { icon: "⏸", label: "按兵不动 · 沉闷持仓", cls: "static" },
};

function fmtUsd(v) {
  return typeof v === "number" && v > 0 ? "$" + Math.round(v).toLocaleString("en-US") : "$0";
}

export function BehaviorFlag({ b }) {
  const { t } = useLang();
  if (!b) return null;
  const meta = FLAG_META[b.flag] || FLAG_META.STATIC;
  const w = b.windows || {};
  return (
    <div className={`ctx-flag ${meta.cls}`}>
      <div className="ctx-flag-h">
        <span className="ctx-flag-ico">{meta.icon}</span>{t(meta.label)}
        <span className="ctx-flag-src">{t("巨鲸 48h 动作流 · 556 Trades")}</span>
      </div>
      <div className="ctx-flag-fact">{t(b.fact)}</div>
      <div className="ctx-flag-win">
        {["3h", "24h", "48h"].map((k) => {
          const x = w[k] || {};
          return (
            <div className="ctx-win" key={k}>
              <span className="ctx-win-k num">{k}</span>
              <span className="ctx-win-b num">{t("买")} {x.buys || 0} · {fmtUsd(x.buy_usd)}</span>
              <span className="ctx-win-s num">{t("卖")} {x.sells || 0} · {fmtUsd(x.sell_usd)}</span>
            </div>
          );
        })}
      </div>
      {b.honest_note && <div className="ctx-flag-note">{t(b.honest_note)}</div>}
    </div>
  );
}
