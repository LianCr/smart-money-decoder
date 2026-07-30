import { useLang } from "../i18n.jsx";

// ── Briefing 完整简报页（v3）─────────────────────────────────────────────────
// 材质分层：硬材质(当事人直接表态/已生效硬事件)=亮+左tick / 其余软材质=暗。靠灰阶不靠颜色。
const HARD_MATERIALS = new Set(["当事人直接表态", "已生效硬事件"]);

// 市场反应 chip：印证=暗绿、不一致(测谎)=暗陶红+⚠、微弱/不可知=灰。t=当前语言翻译函数（渲染点传入）
function reactionChip(pr, t = (s) => s) {
  if (!pr || !pr.available) return { txt: t("市场反应不可知"), cls: "rx-na" };
  const mc = pr.market_check || "";
  const arrow = pr.move_pct >= 0 ? "↑" : "↓";
  const base = `${arrow}${Math.abs(pr.move_pct)}%`;
  if (mc.includes("不一致")) return { txt: `⚠ ${base} ${t("市场不买账")}`, cls: "rx-bad" };
  if (mc.includes("印证")) return { txt: `${base} ${t("市场印证")}`, cls: "rx-good" };
  return { txt: `${base} ${t("反应微弱")}`, cls: "rx-weak" };
}

export function CatColumn({ title, side, items }) {
  const { t } = useLang();
  return (
    <div className={`bf-col ${side}`}>
      <div className="bf-col-h">{t(title)} <span className="bf-col-n">{items.length}</span><span className="bf-pulse pulse-dot" /></div>
      {items.length === 0 && <div className="bf-empty">{t("如实留空")}</div>}
      {items.map((c, i) => {
        const rx = reactionChip(c.price_reaction, t);
        return (
          <div className="bf-cat" key={i}>
            <div className="bf-cat-top">
              <span className={`mat ${HARD_MATERIALS.has(c.type) ? "hard" : "soft"}`}>{t(c.type)}</span>
              <span className="bf-cat-date num">{c.date}</span>
            </div>
            {c.url ? <a className="bf-cat-t" href={c.url} target="_blank" rel="noreferrer">{c.title}</a>
                   : <div className="bf-cat-t">{c.title}</div>}
            <div className="bf-cat-why">{t(c.reason)}</div>
            <span className={`rx ${rx.cls}`}>{rx.txt}</span>
            {c.price_reaction && c.price_reaction.same_window && (
              <div className="bf-samewin">{t("同窗合计 · 不可归因到单条")}</div>
            )}
          </div>
        );
      })}
    </div>
  );
}
