import { useState, useEffect } from "react";
import { useLang, registerAiTranslations } from "../i18n.jsx";
import { API, EXAMPLES, TRADERS_URL, LEADERBOARD_URL, STAGES_BOARD } from "../utils/config.js";
import { abbrev } from "../utils/format.jsx";
import { BoardBody } from "../components/BoardBody.jsx";
import { ErrorBox } from "../components/ErrorBox.jsx";
import { Fold } from "../components/Fold.jsx";
import { HotTraders } from "../components/HotTraders.jsx";
import { LoadingStages } from "../components/LoadingStages.jsx";
import { Recommendations } from "../components/Recommendations.jsx";

export function BoardView() {
  const { t } = useLang();
  const [wallet, setWallet] = useState("");
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [demoWallets, setDemoWallets] = useState([]);
  useEffect(() => {
    fetch(`${API}/demo-wallets`).then((r) => r.json())
      .then((j) => setDemoWallets(j.wallets || [])).catch(() => {});
  }, []);

  async function run(addrArg, refresh = false) {
    const w = (typeof addrArg === "string" ? addrArg : wallet).trim();
    if (!w) return;
    setLoading(true); setData(null); setError(null);
    try {
      for (let attempt = 0; attempt < 80; attempt += 1) {
        const resp = await fetch(`${API}/dashboard?wallet=${encodeURIComponent(w)}${refresh ? "&refresh=1" : ""}`);
        const j = await resp.json();
        if (resp.status === 202 && j.error === "DASHBOARD_BUILD_IN_PROGRESS") {
          await new Promise((resolve) => setTimeout(resolve, (j.retry_after || 3) * 1000));
          refresh = false; // poll the completed cache; never request a second forced rebuild
          continue;
        }
        registerAiTranslations(j.i18n_en);   // EN 运行时词典：后端翻好的 AI 文案，注册后 t() 直接命中
        if (!resp.ok || j.error) setError({ reason: j.error || `HTTP ${resp.status}`, message: j.message || t("请求失败") });
        else setData(j);
        return;
      }
      setError({ reason: "DASHBOARD_BUILD_IN_PROGRESS", message: t("看板仍在生成，请稍后重试。") });
    } catch (e) {
      setError({ reason: "NETWORK", message: t("无法连接后端服务，请稍后重试。") });
    } finally { setLoading(false); }
  }

  function refreshCurrent() {
    const w = (data && data.wallet) || wallet.trim();
    if (!w || loading) return;
    if (!window.confirm(t("强制刷新会绕过缓存、重新调用数据源与 AI（耗时 1-3 分钟、消耗 token 额度）。确定重建吗？"))) return;
    run(w, true);
  }

  const showHome = !data && !loading && !error;
  return (
    <>
      <HotTraders onPick={(w) => { setWallet(w); run(w); }} />
      {!data && !error && (
        <div className="console-sub">{t("输入聪明钱钱包,生成 v3 统一看板:身份体量 → 这一注 → 实时盘面 → 行为×催化剂 → Edge 判断,一屏看全")}</div>
      )}
      <div className={`cmdbar ${loading ? "busy" : ""}`}>
        <span className="cmd-prompt">&gt;</span>
        {showHome && !wallet && <span className="cmd-caret" />}
        <input className="cmd-input num" value={wallet} onChange={(e) => setWallet(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && run()} placeholder={t("输入 Polymarket 钱包地址")} spellCheck={false} />
        <button className="cmd-trigger" onClick={() => run()} disabled={loading || !wallet.trim()}>
          {loading ? t("生成中") : t("生成看板")}
        </button>
      </div>

      {showHome && <Recommendations onPick={(w) => { setWallet(w); run(w); }} />}

      {showHome && (
        <div className="monitor">
          <div className="mon-head">{t("或试试这几个 demo 钱包 · 点击生成统一看板")}</div>
          <div className="mon-list">
            {EXAMPLES.map((e) => (
              <button className="mon-row" key={e.addr} onClick={() => { setWallet(e.addr); run(e.addr); }}>
                <span className="mon-dot" /><span className="mon-nick">{e.nick}</span>
                <span className="mon-addr num">{abbrev(e.addr)}</span>
                <span className="mon-pnl"><span className="mon-pnl-lab">{t("累计盈利")}</span><span className="mon-pnl-val num">{e.pnl}</span></span>
              </button>
            ))}
          </div>
          <div className="mon-foot">
            <a className="sys-cta" href={TRADERS_URL} target="_blank" rel="noreferrer">{t("想分析其他大户?浏览政治盘大户榜 ↗")}</a>
            <a className="sys-source" href={LEADERBOARD_URL} target="_blank" rel="noreferrer">{t("数据来源:Polymarket 官方盈利榜 ↗")}</a>
          </div>
        </div>
      )}

      {showHome && demoWallets.length > 0 && (
        <div className="monitor">
          <div className="mon-head">{t("⚡ 已缓存 · 秒开（不消耗额度）")}</div>
          <div className="mon-list">
            {demoWallets
              .filter((d) => !EXAMPLES.some((e) => e.addr.toLowerCase() === (d.wallet || "").toLowerCase()))
              .slice(0, 10)
              .map((d) => (
                <button className="mon-row" key={d.wallet} onClick={() => { setWallet(d.wallet); run(d.wallet); }}>
                  <span className="mon-dot" /><span className="mon-nick">{d.name || abbrev(d.wallet)}</span>
                  <span className="mon-addr num">{abbrev(d.wallet)}</span>
                  {d.market_question && <span className="mon-q">{d.market_question}</span>}
                </button>
              ))}
          </div>
        </div>
      )}

      {showHome && (
        <div className="method-fold">
          <Fold title={t("🔒 这里的 AI 被怎么圈养（方法论）")} sub={t("AI 原生 ≠ AI 说了算——六条纪律")}>
            <ul className="method-list">
              <li><b>{t("数字归代码。")}</b>{t("价格差、剩余空间、时长、日期数学 100% 由代码预算好，AI 禁止做任何算术。")}</li>
              <li><b>{t("AI 只做解读。")}</b>{t("全站共七个被严格圈定的 AI 调用点，只负责把硬数字翻译成人话。")}</li>
              <li><b>{t("信心可溯源。")}</b>{t("⑥ 的信心来自市场级多空对抗 → 中立裁决，来源系统标注在结果里，降级会明示。")}</li>
              <li><b>{t("守卫会真发火。")}</b>{t("编造催化剂、篡改置信度、替你拍板、贩卖恐惧——命中即拦截、不输出。")}</li>
              <li><b>{t("没证据就留空。")}</b>{t("空栏目是诚实不是 bug，绝不用幻觉填充。")}</li>
              <li><b>{t("判断进记分牌。")}</b>{t("每个判断存档，等市场真结算后与现实对账（Track Record 页可查）。")}</li>
            </ul>
          </Fold>
        </div>
      )}

      {loading && <LoadingStages stages={STAGES_BOARD} sub="身份 → 这一注 → 盘面 → 行为×催化剂 → Edge" note={t("未缓存的钱包要真跑全链（数据层 → 双向催化剂 → 多空对抗三连调），约 1-3 分钟；已缓存钱包会秒回。")} />}
      {error && <ErrorBox error={error} />}
      {data && (
        <>
          {data.refresh_error && (
            <div className="db-stale-warn">⚠ {t("刷新失败，已回退到上次成功的看板（数据仍是旧的）")} · <span className="num">{data.refresh_error}</span></div>
          )}
          {data.refresh_in_progress && (
            <div className="db-stale-warn">↻ {t("另一位访客正在刷新这份看板；先展示上次成功结果，避免重复消耗 AI 额度。")}</div>
          )}
          <div className="db-refresh-bar">
            <span className="db-refresh-asof num">as-of {data.as_of}</span>
            <button className="db-refresh" onClick={refreshCurrent} disabled={loading}
              title={t("绕过缓存重建这份看板（重新拉数据 + 重跑 AI，耗时且消耗 token）")}>
              ↻ {t("强制刷新")}
            </button>
          </div>
          <BoardBody d={data} />
        </>
      )}
    </>
  );
}
