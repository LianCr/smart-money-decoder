import { useState } from "react";
import { useLang } from "../i18n.jsx";
import { API, EXAMPLES, STAGES_CONTEXT } from "../utils/config.js";
import { abbrev } from "../utils/format.jsx";
import { ContextBody } from "../components/ContextBody.jsx";
import { ErrorBox } from "../components/ErrorBox.jsx";
import { LoadingStages } from "../components/LoadingStages.jsx";

export function ContextView() {
  const { t } = useLang();
  const [wallet, setWallet] = useState("");
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  async function run(addrArg) {
    const w = (typeof addrArg === "string" ? addrArg : wallet).trim();
    if (!w) return;
    setLoading(true); setData(null); setError(null);
    try {
      const resp = await fetch(`${API}/market-context?wallet=${encodeURIComponent(w)}`);
      const j = await resp.json();
      if (!resp.ok || j.error) setError({ reason: j.error || `HTTP ${resp.status}`, message: j.message || t("请求失败") });
      else setData(j);
    } catch (e) {
      setError({ reason: "NETWORK", message: t("无法连接后端服务，请稍后重试。") });
    } finally { setLoading(false); }
  }

  const showHome = !data && !loading && !error;
  return (
    <>
      {!data && !error && (
        <div className="console-sub">{t("输入聪明钱钱包,生成市场 Context:实时盘面(实) × as-of 复盘(虚) = 价格异动 + 催化剂 + 巨鲸 48h 进出动作")}</div>
      )}
      <div className={`cmdbar ${loading ? "busy" : ""}`}>
        <span className="cmd-prompt">&gt;</span>
        {showHome && !wallet && <span className="cmd-caret" />}
        <input className="cmd-input num" value={wallet} onChange={(e) => setWallet(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && run()} placeholder={t("输入 Polymarket 钱包地址")} spellCheck={false} />
        <button className="cmd-trigger" onClick={() => run()} disabled={loading || !wallet.trim()}>
          {loading ? t("合成中") : t("生成 Context")}
        </button>
      </div>

      {showHome && (
        <div className="monitor">
          <div className="mon-head">{t("试试这几个大户 · 点击生成市场 Context")}</div>
          <div className="mon-list">
            {EXAMPLES.map((e) => (
              <button className="mon-row" key={e.addr} onClick={() => { setWallet(e.addr); run(e.addr); }}>
                <span className="mon-dot" /><span className="mon-nick">{e.nick}</span>
                <span className="mon-addr num">{abbrev(e.addr)}</span>
                <span className="mon-pnl"><span className="mon-pnl-lab">{t("累计盈利")}</span><span className="mon-pnl-val num">{e.pnl}</span></span>
              </button>
            ))}
          </div>
        </div>
      )}

      {loading && <LoadingStages stages={STAGES_CONTEXT} sub="盘面 → 价格异动 → 催化剂 → 巨鲸动作 → 综述" note={t("未缓存的钱包要真跑全链（数据层 → 双向催化剂 → 多空对抗三连调），约 1-3 分钟；已缓存钱包会秒回。")} />}
      {error && <ErrorBox error={error} />}
      {data && <ContextBody d={data} />}
    </>
  );
}

// ── v3 统一看板（①身份 ②这一注 ③实时盘面 ④⑤行为×催化剂 ⑥Edge）─────────────
