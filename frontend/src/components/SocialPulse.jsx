import { useLang } from "../i18n.jsx";

// 社媒情绪动量（585）· 🔴 情绪非事实、视觉刻意区别于新闻、刷量标显眼
export function SocialPulse({ s }) {
  const { t } = useLang();
  if (!s) return <div className="bf-empty">{t("该话题暂无社媒数据（或未配置）")}</div>;
  const acc = s.acceleration;
  const heating = typeof acc === "number" && acc > 1;
  const div = s.author_diversity_pct;          // 语义：每 100 条讨论来自约 N 个不同账号
  const organic = s.organic;
  const per100 = typeof div === "number" ? Math.max(1, Math.round(div)) : null;
  return (
    <div className="soc">
      <div className="soc-metrics">
        <div className="soc-m">
          <div className="soc-m-lab">{t("讨论热度")}</div>
          <div className={`soc-m-val ${heating ? "hot" : "cold"}`}>
            {typeof acc !== "number" ? "—"
              : acc < 0.1 ? `❄ ${t("讨论几乎停了")}`
              : heating ? `🔥 ${t("升温中")}` : `❄ ${t("降温中")}`}
          </div>
          {typeof acc === "number" && acc >= 0.1 && (
            <div className="soc-m-sub"><span className="num">{acc.toFixed(1)}×</span> {t("平时讨论量")}</div>
          )}
        </div>
        <div className="soc-m">
          <div className="soc-m-lab">{(s.tweet_count || 0).toLocaleString()} {t("条讨论")}</div>
          <div className={`soc-bot ${organic ? "ok" : "bad"}`} title={organic ? t("✓ 账号分散 · 像真人讨论") : t("🤖 账号集中 · 像刷量")}>{organic ? t("✓ 像真人讨论") : t("🤖 像刷量")}</div>
        </div>
      </div>
      {!organic && per100 != null && (
        <div className="soc-warn">{t("⚠ 每 100 条讨论只来自约")} {per100} {t("个账号——这种热闹很可能是刷出来的：当氛围看，别当民意")}</div>
      )}
      <div className="soc-posts">
        {(s.posts || []).map((p, i) => {
          const eng = (p.likes || 0) + (p.retweets || 0);
          const badge = eng >= 50 ? { txt: t("🔥 热帖"), cls: "hot" } : eng >= 10 ? { txt: t("💬 有讨论"), cls: "mid" } : null;
          const u = (p.username || "?").replace(/^@/, "");
          return (
            <div className="soc-post" key={i}>
              <div className="soc-post-top">
                <span className="soc-av">
                  <span className="soc-av-init">{u[0] ? u[0].toUpperCase() : "?"}</span>
                  <img className="soc-av-img" src={`https://unavatar.io/x/${encodeURIComponent(u)}`}
                    loading="lazy" alt="" onError={(e) => { e.currentTarget.style.display = "none"; }} />
                </span>
                <span className="soc-user">@{u}</span>
                {badge && <span className={`soc-badge ${badge.cls}`}>{badge.txt}</span>}
                <span className="soc-eng num">♥ {p.likes || 0} · ↻ {p.retweets || 0}</span>
              </div>
              <div className="soc-post-txt">{p.content}</div>
              {p.url && <a className="soc-post-link" href={p.url} target="_blank" rel="noreferrer">{t("原帖 ↗")}</a>}
            </div>
          );
        })}
      </div>
      <div className="soc-foot">{t("社媒反映的是情绪和声量、不是事实——方向判断请看左列新闻与顶部结论")}</div>
    </div>
  );
}
