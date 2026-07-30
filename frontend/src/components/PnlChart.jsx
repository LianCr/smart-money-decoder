import { useLang } from "../i18n.jsx";
import { fmtPnlCompact } from "../utils/format.jsx";

// unix 秒 → "YYYY-MM"
function fmtMonth(t) {
  const d = new Date(t * 1000);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

// 极简 PnL 折线：纯 SVG，无图表库、无交互、无 tooltip
// 把曲线按零线拆成 green/red 子段（水下=红）；全为正时返回单段
function pnlSegments(points, x, y) {
  const segs = [];
  let cur = [], curNeg = points[0].p < 0;
  for (let i = 0; i < points.length; i++) {
    const p = points[i].p, neg = p < 0;
    if (i > 0 && neg !== curNeg) {
      const p0 = points[i - 1].p, t = p0 / (p0 - p);          // 线性插值零交叉点
      const xc = x(i - 1) + (x(i) - x(i - 1)) * t, yc = y(0);
      cur.push([xc, yc]); segs.push({ neg: curNeg, pts: cur });
      cur = [[xc, yc]]; curNeg = neg;
    }
    cur.push([x(i), y(points[i].p)]);
  }
  if (cur.length) segs.push({ neg: curNeg, pts: cur });
  return segs.map((s) => ({
    neg: s.neg,
    d: s.pts.map((c, j) => `${j ? "L" : "M"}${c[0].toFixed(1)},${c[1].toFixed(1)}`).join(" "),
  }));
}

export function PnlChart({ points }) {
  const { t } = useLang();
  const n = points.length;
  const W = 600, H = 84, pad = 10;
  const ps = points.map((d) => d.p);
  const min = Math.min(...ps), max = Math.max(...ps), span = max - min || 1;
  const x = (i) => (i / (n - 1)) * W;
  const y = (p) => pad + (1 - (p - min) / span) * (H - 2 * pad);
  const last = ps[n - 1], first = ps[0];
  const underwater = min < 0;
  const color = last >= first ? "var(--green)" : "var(--red)";
  const segs = pnlSegments(points, x, y);
  const area = `M0,${y(first)} ${points.map((d, i) => `L${x(i).toFixed(1)},${y(d.p).toFixed(1)}`).join(" ")} L${W},${H} L0,${H} Z`;
  // 当前值端点 + 峰值点（百分比定位，HTML 圆点不被 SVG 拉伸）
  const lastTop = (y(last) / H) * 100;
  const peakIdx = ps.indexOf(max);
  const peakLeft = Math.min(Math.max((peakIdx / (n - 1)) * 100, 6), 82);
  const peakTop = (y(max) / H) * 100;

  return (
    <div className="pnlchart">
      <div className="pc-top">
        <span className="pc-lab">{t("CUMULATIVE PnL · 该钱包历史累计盈亏")}</span>
        <span className="pc-val" style={{ color }}>{fmtPnlCompact(last)}</span>
      </div>
      <div className="pc-chart">
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
          <path d={area} fill={color} opacity="0.08" />
          {underwater && <line x1="0" x2={W} y1={y(0)} y2={y(0)} className="pc-zero" />}
          {segs.map((s, i) => (
            <path key={i} className="pc-line" d={s.d} fill="none" pathLength="1"
              stroke={s.neg ? "var(--red)" : "var(--green)"} strokeWidth="2" vectorEffect="non-scaling-stroke" />
          ))}
        </svg>
        <span className="pc-dot" style={{ left: "calc(100% - 4px)", top: `calc(${lastTop}% - 4px)`, background: color }} />
        <span className="pc-peak" style={{ left: `${peakLeft}%`, top: `${peakTop}%` }}>peak {fmtPnlCompact(max)}</span>
      </div>
      <div className="pc-axis">
        <span>{fmtMonth(points[0].t)}</span>
        <span>{fmtMonth(points[n - 1].t)}</span>
      </div>
    </div>
  );
}
