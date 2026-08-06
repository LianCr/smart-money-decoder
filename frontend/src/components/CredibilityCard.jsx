import { useLang } from "../i18n.jsx";

// ── F4 可信度卡：这个盘的价格值不值得信（纯代码硬指标，deterministic:true）──
// payload 只带数字+枚举（credibility.subs[].raw），中英文案全在前端 t() 查表——
// 省后端翻译预算，旧缓存/数据层降级场景 EN 照常工作。复用 bf-mini/bf-kv 样式零新 CSS。
// 旧缓存板没有 credibility key → 整卡安静缺席（guard_flags 先例）；score:null → 诚实"暂缺"态。
const LABEL = {
  liquidity: "流动性", concentration: "大户集中度", participants: "独立参与",
  volume: "量能", volatility: "市场犹豫度", age: "市场年龄", self_check: "判断层自检",
};
const NOTE = {
  liquidity: "盘越深，价格越难被单笔砸出假信号",
  concentration: "头部越重，价格越像少数人的意见而非共识",
  participants: "人太少，价格是几个人的赌局不是人群的判断",
  volume: "没人交易的价格是上次成交的遗迹",
  volatility: "市场自己没拿定主意，当下价位不值得当锚",
  age: "新盘价格发现未完成，价位还没被人群消化",
  self_check: "本次触发守卫的情况 × 历史上守卫判断的命中率",
};
const MARK = { ok: ["✓", "pos"], warn: ["⚠", ""], bad: ["✗", "neg"], missing: ["—", ""], info: ["·", ""] };

function valText(s, t) {
  const r = s.raw || {};
  if (s.verdict === "missing") return t("暂缺");
  switch (s.key) {
    case "liquidity": return `${r.tier ? r.tier + " · " : ""}${r.pct}${t(" 百分位")}`;
    case "concentration": return `top1 ${r.top1 ?? "—"}% · top10 ${r.top10 ?? "—"}%`;
    case "participants": return `${r.uniq}${t(" 人 / 近7天")}`;
    case "volume": return `${r.trend ?? "—"}${r.collapse ? " · " + t("⚠塌缩") : ""}`;
    case "volatility": return `${t("日波动 ")}${r.vol}`;
    case "age": return `${r.age_days}${t(" 天")}`;
    case "self_check": {
      const base = r.insufficient
        ? `${t("本次守卫 ")}${r.guard_flags_n}${t(" 项 · 历史样本不足")}`
        : `${t("本次守卫 ")}${r.guard_flags_n}${t(" 项 · 守卫过 ")}${r.flagged ?? "—"}% vs ${t("干净 ")}${r.clean ?? "—"}%`;
      const wf = r.wallet_anomaly_flags || [];
      return wf.length ? `${base} · ⚠${t("钱包旗标 ")}${wf.length}${t(" 项")}` : base;
    }
    default: return "";
  }
}

export function CredibilityCard({ c }) {
  const { t } = useLang();
  if (!c || !c.subs) return null;
  return (
    <>
      <div className="db-sec-tag">{t("③b 这个价格值不值得信 · 可信度分")}</div>
      <div className="bf-mini cred-card">
        <div className="bf-kv">
          <span>{t("可信度")}</span>
          <b className="num">
            {c.score == null ? t("数据暂缺 · 不硬给分") : `${c.tier} · ${c.score}/100`}
            {c.partial && c.score != null ? ` · ${t("部分信号缺失")}` : ""}
          </b>
        </div>
        {c.subs.map((s) => {
          const [mark, cls] = MARK[s.verdict] || MARK.info;
          return (
            <div className="bf-kv" key={s.key} title={t(NOTE[s.key] || "")}>
              <span>{mark} {t(LABEL[s.key] || s.key)}</span>
              <b className={`num ${cls}`}>{valText(s, t)}{s.delta < 0 ? ` (${s.delta})` : ""}</b>
            </div>
          );
        })}
        {c.risk_flags && c.risk_flags.length > 0 && (
          <div className="bf-sub">⚠ {c.risk_flags.join(" · ")}</div>
        )}
        <div className="bf-note">{t("纯代码硬指标，不经 AI · 评价盘的价格质量，不修改任何 AI 判断 · 样本不足如实标注")}</div>
      </div>
    </>
  );
}
