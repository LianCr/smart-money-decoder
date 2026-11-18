import { useLang } from "../i18n.jsx";
import { API } from "../utils/config.js";
import { useOptionalJson } from "../hooks/useOptionalJson.js";
import { ELECTION_DAY, electionCountdown, partyOf, pct, compactUsd, asOfUtc, dateLabel } from "../utils/election.js";

// 首页顶部：2026 中期选举倒计时 + Polymarket 头条赔率。
// 纯展示 + 只读 GET /election-pulse；端点失败或无盘 → 整块不渲染（不出错误态、不占位）。
// 党派色走 --dem/--gop，刻意不复用盈亏绿/红（红线：数字含义不许被配色篡改）。
export function ElectionBanner() {
  const { t, lang } = useLang();
  const data = useOptionalJson(`${API}/election-pulse`);
  const markets = Array.isArray(data?.markets) ? data.markets.filter((m) => m && m.title).slice(0, 6) : [];
  if (!markets.length) return null;

  const cd = electionCountdown(data.election_date || ELECTION_DAY);
  const asOf = data.as_of ? asOfUtc(data.as_of, lang) : null;

  return (
    <section className="eb" aria-labelledby="eb-title">
      <div className="eb-head">
        <div className="eb-title-wrap">
          <h2 className="eb-title" id="eb-title">{t("2026 美国中期选举")}</h2>
          <p className="eb-sub">{t("Polymarket 此刻的定价 · 概率 = 市场隐含价格，不是预测")}</p>
        </div>
        {cd && <Countdown cd={cd} t={t} lang={lang} />}
      </div>

      <ul className="eb-list">
        {markets.map((m) => <MarketRow key={m.slug || m.title} m={m} t={t} />)}
      </ul>

      {asOf && <div className="eb-foot num">{t("数据截至")} {asOf}</div>}
    </section>
  );
}

function Countdown({ cd, t, lang }) {
  if (cd.phase === "before") {
    // 中文无单复数；英文 1 天用单数（词典只收复数形）
    const unit = cd.days === 1 && lang === "en" ? "day to Election Day" : t("天后选举日");
    return (
      <div className="eb-count">
        <span className="eb-count-n num" aria-hidden="true">{cd.days}</span>
        <span className="eb-count-l">
          <span className="sr-only">{cd.days} </span>{unit}<br />
          <span className="eb-date">{dateLabel(cd.date, lang)}</span>
        </span>
      </div>
    );
  }
  return (
    <div className={`eb-count live ${cd.phase}`}>
      <span className="eb-live-dot" aria-hidden="true" />
      <span className="eb-count-l">
        <b>{t(cd.phase === "today" ? "今天是选举日" : "选举日已过")}</b><br />
        {t(cd.phase === "today" ? "投票进行中 · 盘口实时变动" : "结果待定 · 以市场结算为准")}
      </span>
    </div>
  );
}

function MarketRow({ m, t }) {
  const outs = (Array.isArray(m.outcomes) ? m.outcomes : [])
    .filter((o) => o && typeof o.price === "number" && isFinite(o.price))
    .sort((a, b) => b.price - a.price)
    .slice(0, 2);
  if (!outs.length) return null;
  const [a, b] = outs;
  const rest = Math.max(0, 1 - a.price - (b ? b.price : 0));
  const label = outs.map((o) => `${o.name} ${pct(o.price)}`).join(", ");
  const Title = m.url ? "a" : "span";
  return (
    <li className="eb-row">
      <div className="eb-row-top">
        <Title className="eb-q" {...(m.url ? { href: m.url, target: "_blank", rel: "noreferrer" } : {})}>{m.title}</Title>
        {m.volume24hr != null && <span className="eb-vol num">{compactUsd(m.volume24hr)} <span>{t("24h 成交")}</span></span>}
      </div>
      <div className="eb-bar" role="img" aria-label={label}>
        <span className={`eb-seg ${partyOf(a.name) || "n1"}`} style={{ width: `${a.price * 100}%` }} />
        {b && <span className={`eb-seg ${partyOf(b.name) || "n2"}`} style={{ width: `${b.price * 100}%` }} />}
        {rest > 0.005 && <span className="eb-seg rest" style={{ width: `${rest * 100}%` }} />}
      </div>
      <div className="eb-legend">
        <span className={`eb-out ${partyOf(a.name) || "n1"}`}><i aria-hidden="true" />{a.name} <b className="num">{pct(a.price)}</b></span>
        {b && <span className={`eb-out right ${partyOf(b.name) || "n2"}`}>{b.name} <b className="num">{pct(b.price)}</b><i aria-hidden="true" /></span>}
      </div>
    </li>
  );
}
