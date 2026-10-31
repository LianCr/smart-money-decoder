import { useLang } from "../i18n.jsx";
import { API } from "../utils/config.js";
import { abbrev } from "../utils/format.jsx";
import { useOptionalJson } from "../hooks/useOptionalJson.js";
import { pct, compactUsd } from "../utils/election.js";

// 首页：科技 & 移民相关的实盘（H-1B / F-1 / OPT 关心的那一类）。只读 GET /tech-immigration。
// 后端 note 原样展示（诚实说明"没有直接以 H-1B/F-1/OPT 命名的盘，这些是最接近的"）。
// 端点失败或无盘 → 整块不渲染。最大持有人可选；点它直接生成该钱包的统一看板。
export function TechImmigration({ onPick }) {
  const { t } = useLang();
  const data = useOptionalJson(`${API}/tech-immigration`);
  const markets = Array.isArray(data?.markets) ? data.markets.filter((m) => m && m.title).slice(0, 6) : [];
  if (!markets.length) return null;

  return (
    <section className="ti" aria-labelledby="ti-title">
      <div className="ti-head">
        <h2 className="ti-title" id="ti-title">{t("科技与移民")}</h2>
        <p className="ti-sub">{t("H-1B、F-1、OPT 等签证与科技人才政策相关的实盘")}</p>
      </div>
      {data.note && <p className="ti-note">{t(data.note)}</p>}
      <ul className="ti-list">
        {markets.map((m) => <TiCard key={m.url || m.title} m={m} t={t} onPick={onPick} />)}
      </ul>
    </section>
  );
}

function TiCard({ m, t, onPick }) {
  const top = m.top_outcome && typeof m.top_outcome.price === "number" ? m.top_outcome : null;
  const h = m.top_holder && m.top_holder.wallet ? m.top_holder : null;
  const Title = m.url ? "a" : "span";
  return (
    <li className="ti-card">
      <Title className="ti-q" {...(m.url ? { href: m.url, target: "_blank", rel: "noreferrer" } : {})}>{m.title}</Title>
      <div className="ti-odds">
        {top ? (
          <>
            <span className="ti-out">{top.name}</span>
            <b className="ti-pct num">{pct(top.price)}</b>
          </>
        ) : <span className="ti-out">—</span>}
        {m.volume24hr != null && <span className="ti-vol num">{compactUsd(m.volume24hr)} <span>{t("24h 成交")}</span></span>}
      </div>
      {h && (
        <button type="button" className="ti-holder" onClick={() => onPick && onPick(h.wallet)}
          title={t("最大持有人 · 点击生成该钱包的统一看板")}>
          <span className="ti-holder-lab">{t("最大持有人")}</span>
          <span className="ti-holder-name">{h.name || <span className="num">{abbrev(h.wallet)}</span>}</span>
          {typeof h.amount === "number" && <span className="ti-holder-amt num">{compactUsd(h.amount).replace("$", "")} {t("份")}</span>}
        </button>
      )}
    </li>
  );
}
