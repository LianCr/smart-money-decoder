// 选举面板的纯展示工具（零网络、零状态）：倒计时、党派归类、紧凑金额、概率格式。

export const ELECTION_DAY = "2026-11-03";

// 只比"日历日"（本地今天 vs 选举日），避免时区把 1 天算成 0 或 2。
// 返回 { phase: "before" | "today" | "after", days }
export function electionCountdown(dateStr = ELECTION_DAY, now = new Date()) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(dateStr || "");
  if (!m) return null;
  const target = Date.UTC(+m[1], +m[2] - 1, +m[3]);
  const today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
  const days = Math.round((target - today) / 86400000);
  const date = m[0];
  if (days > 0) return { phase: "before", days, date };
  if (days === 0) return { phase: "today", days: 0, date };
  return { phase: "after", days: -days, date };
}

// 党派色只按 outcome 名字判断；其余（"D House, R Senate"、候选人名…）一律中性，绝不硬套。
export function partyOf(name) {
  const s = String(name || "").toLowerCase();
  if (/\bdemocrat(ic|s)?\b|^d$|^dem\b/.test(s)) return "dem";
  if (/\brepublican(s)?\b|^r$|^gop\b/.test(s)) return "gop";
  return null;
}

export function pct(p) {
  return typeof p === "number" && isFinite(p) ? `${Math.round(p * 100)}%` : "—";
}

export function compactUsd(v) {
  const n = Number(v);
  if (!isFinite(n)) return "—";
  const a = Math.abs(n);
  if (a >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
  if (a >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
  if (a >= 1e3) return `$${(n / 1e3).toFixed(1)}K`;
  return `$${Math.round(n)}`;
}

export function asOfUtc(iso, lang) {
  const d = new Date(iso);
  if (isNaN(d)) return null;
  return d.toLocaleString(lang === "zh" ? "zh-CN" : "en-US", {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "UTC",
  }) + " UTC";
}

// "Tue, Nov 3" / "11月3日周二"（按 UTC 解析日期串，不受本地时区影响）
export function dateLabel(dateStr, lang) {
  const d = new Date(`${dateStr}T00:00:00Z`);
  if (isNaN(d)) return dateStr || "";
  return d.toLocaleDateString(lang === "zh" ? "zh-CN" : "en-US", {
    weekday: "short", month: "short", day: "numeric", timeZone: "UTC",
  });
}
