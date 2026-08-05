import { useLang } from "../i18n.jsx";

// ── 信心校准（T2.5 回验闭环：⑥ 的信心档 × 实际方向命中率，喂自 /confidence-replay）──
// 复用记分牌的 .sc 样式，不新增 CSS；样本不足的档诚实显示"样本不足"、不给误导百分比。
const BUCKET_LABEL = { high: "高信心", med: "中信心", low: "低信心", other: "异常值" };

export function ConfidenceCalibration({ cr }) {
  const { t } = useLang();
  if (!cr || cr.error || !cr.buckets) return null;
  const fmt = (b) =>
    !b || b.n === 0 ? "—"
    : b.insufficient ? `${b.hits}/${b.n} · ${t("样本不足")}`
    : `${b.hit_rate_pct}% (${b.hits}/${b.n})`;
  const keys = ["high", "med", "low", ...(cr.buckets.other && cr.buckets.other.n > 0 ? ["other"] : [])];
  return (
    <div className="sc">
      <div className="sc-head">
        <div className="sc-title">{t("信心校准 · 我说高信心的时候，到底有多准")}</div>
        <div className="sc-sub">{t("⑥ 每次信心判断自动记档，盘结算后按方向对账。同盘重建折叠为一条；方向未定进 NO BASIS 单列。")}</div>
      </div>
      <div className="sc-nums">
        {keys.map((k) => (
          <div className="sc-num" key={k}><b className="num">{fmt(cr.buckets[k])}</b><span>{t(BUCKET_LABEL[k])}</span></div>
        ))}
        <div className="sc-num"><b className="num">{cr.pending_n}</b><span>{t("待结算")}</span></div>
        <div className="sc-num"><b className="num">{cr.nobasis_n}</b><span>NO BASIS</span></div>
      </div>
      <div className="sc-discipline">
        {t("守卫触发过：")}{fmt(cr.guard_cross && cr.guard_cross.flagged)}{t(" · 干净判断：")}{fmt(cr.guard_cross && cr.guard_cross.clean)}
        {t(" · 命中=判断方向，不算收益 · 原判断绝不回填")}
      </div>
      {cr.total === 0 && (
        <div className="sc-empty">{t("还没有可回验的信心判断——看板每出一次 ⑥ 就会记一条；等盘真结算，各档命中率才长出来。")}</div>
      )}
    </div>
  );
}
