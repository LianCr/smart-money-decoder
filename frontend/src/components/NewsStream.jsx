import { useLang } from "../i18n.jsx";
import { ReactionTag } from "./ReactionTag.jsx";

// 方向标=dual_catalyst 已分好的正负（支持/威胁）；GDELT 未分类→不杜撰方向
const DIR_META = { support: { txt: "支持", cls: "support" }, threat: { txt: "威胁", cls: "threat" } };

function domainOf(url, fallback) {
  try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return fallback || ""; }
}

function faviconUrl(domain) { return `https://www.google.com/s2/favicons?domain=${domain}&sz=64`; }

// 新闻流 · Polymarket 风格（标题 + 段落 + 底部可点 mini 来源 logo + 市场反应）
export function NewsStream({ items }) {
  const { t } = useLang();
  if (!items || !items.length)
    return <div className="bf-empty">{t("该时点窗内三源都没洗出对题新闻 — 如实留空")}</div>;
  // 按日分组：日级价格变动本就属于"这一天"而非某一条 → 反应 chip 挂组头（诚实归因层级），
  // 组内不再逐条重复免责；"反应不可知"沉默不显示（无信号不该喊话）
  const groups = [];
  const gi = new Map();
  for (const it of items) {
    const k = it.date || "—";
    if (!gi.has(k)) { gi.set(k, groups.length); groups.push({ date: k, items: [], reaction: null }); }
    const g = groups[gi.get(k)];
    g.items.push(it);
    if (!g.reaction && it.reaction && it.reaction.available) g.reaction = it.reaction;
  }
  return (
    <div className="db-stream">
      {groups.map((g) => (
        <div className="db-day" key={g.date}>
          <div className="db-day-h">
            <span className="db-day-date num">{g.date}</span>
            {g.items.length > 1 && <span className="db-day-n num">×{g.items.length}</span>}
            {g.reaction && <ReactionTag r={g.reaction} />}
            {g.reaction && g.items.length > 1 && (
              <span className="db-day-agg" title={t("同日多条 · 前后变动为合计,不可归因到单条")}>{t("当日合计")}</span>
            )}
          </div>
          {g.items.map((it, i) => {
            const dir = DIR_META[it.direction];
            const dom = domainOf(it.url, it.source);
            return (
              <div className={`db-news ${it.direction || ""}`} key={i}>
                {it.url ? <a className="db-news-t" href={it.url} target="_blank" rel="noreferrer">{t(it.title)}</a>
                        : <div className="db-news-t">{t(it.title)}</div>}
                {it.summary && <div className="db-news-s">{t(it.summary)}</div>}
                <div className="db-news-meta">
                  {dir && <span className={`db-dir ${dir.cls}`}>{t(dir.txt)}</span>}
                  {dom && (
                    <a className="db-news-src" href={it.url} target="_blank" rel="noreferrer" title={dom}>
                      <img className="db-news-fav" src={faviconUrl(dom)} alt="" loading="lazy" onError={(e) => { e.currentTarget.style.display = "none"; }} />
                      <span className="db-news-dom">{dom}</span>
                    </a>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      ))}
      <div className="db-stream-foot">{t("反应 = 持有侧价格当日变动 · 时间相关非因果 · 同日多条共享同一变动")}</div>
    </div>
  );
}
