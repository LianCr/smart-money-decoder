// Shared formatting helpers extracted from App.jsx (pure move, no logic change).
// renderInline returns JSX → this module is .jsx.

export function price(p) {
  return typeof p === "number" ? p.toFixed(3) : "—";
}

export function money(v) {
  if (typeof v !== "number") return "—";
  const s = v < 0 ? "-" : "+";
  return s + "$" + Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 });
}

export function abbrev(addr) {
  return addr && addr.length > 12 ? `${addr.slice(0, 6)}…${addr.slice(-4)}` : addr;
}

export function fmtPnlCompact(v) {
  const s = v < 0 ? "-" : "+";
  const a = Math.abs(v);
  if (a >= 1e6) return `${s}$${(a / 1e6).toFixed(2)}M`;
  if (a >= 1e3) return `${s}$${(a / 1e3).toFixed(1)}K`;
  return `${s}$${a.toFixed(0)}`;
}

// 把第三个 AI 的人话简报做轻量渲染（**粗体** → <b>）
export function renderInline(s) {
  return s.split(/(\*\*.+?\*\*)/g).map((p, i) =>
    p.startsWith("**") && p.endsWith("**") ? <b key={i}>{p.slice(2, -2)}</b> : p);
}
