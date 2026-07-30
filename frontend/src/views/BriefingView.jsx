import { useState } from "react";
import { useLang, registerAiTranslations } from "../i18n.jsx";
import { API, EXAMPLES, STAGES_BRIEFING } from "../utils/config.js";
import { abbrev } from "../utils/format.jsx";
import { BriefingBody } from "../components/BriefingBody.jsx";
import { ErrorBox } from "../components/ErrorBox.jsx";
import { LoadingStages } from "../components/LoadingStages.jsx";

export function BriefingView() {
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
      const resp = await fetch(`${API}/briefing?wallet=${encodeURIComponent(w)}`);
      const j = await resp.json();
      registerAiTranslations(j.i18n_en);
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
        <div className="console-sub">{t("输入聪明钱钱包,生成完整简报:画像 + 动作 + 价格 + 双向催化剂(市场测谎) + AI 诚实整理")}</div>
      )}
      <div className={`cmdbar ${loading ? "busy" : ""}`}>
        <span className="cmd-prompt">&gt;</span>
        {showHome && !wallet && <span className="cmd-caret" />}
        <input className="cmd-input num" value={wallet} onChange={(e) => setWallet(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && run()} placeholder={t("输入 Polymarket 钱包地址")} spellCheck={false} />
        <button className="cmd-trigger" onClick={() => run()} disabled={loading || !wallet.trim()}>
          {loading ? t("生成中") : t("生成简报")}
        </button>
      </div>

      {showHome && (
        <div className="monitor">
          <div className="mon-head">{t("试试这几个大户 · 点击生成完整简报")}</div>
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

      {loading && <LoadingStages stages={STAGES_BRIEFING} sub="画像 → 动作 → 价格 → 催化剂 → 整理" note={t("未缓存的钱包要真跑全链（数据层 → 双向催化剂 → 多空对抗三连调），约 1-3 分钟；已缓存钱包会秒回。")} />}
      {error && <ErrorBox error={error} />}
      {data && <BriefingBody d={data} />}
    </>
  );
}
