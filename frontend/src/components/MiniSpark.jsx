// 迷你 sparkline（身份徽章用，纯 SVG，零依赖）
export function MiniSpark({ points }) {
  const n = points.length, W = 66, H = 18;
  const ps = points.map((d) => d.p);
  const min = Math.min(...ps), max = Math.max(...ps), span = max - min || 1;
  const x = (i) => (i / (n - 1)) * W, y = (p) => (1 - (p - min) / span) * H;
  const path = ps.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p).toFixed(1)}`).join(" ");
  const color = ps[n - 1] >= ps[0] ? "var(--pos)" : "var(--neg)";
  return (
    <svg className="vh-spark" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
      <path d={path} fill="none" stroke={color} strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
