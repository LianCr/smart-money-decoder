import { useState } from "react";
import { useLang } from "../i18n.jsx";
import { API, EXAMPLES, TRADERS_URL, LEADERBOARD_URL } from "../utils/config.js";
import { abbrev } from "../utils/format.jsx";
import { Card } from "../components/Card.jsx";
import { ErrorBox } from "../components/ErrorBox.jsx";
import { LoadingStages } from "../components/LoadingStages.jsx";

export function DecodeView() {
  const { t } = useLang();
  const [wallet, setWallet] = useState("");
  const [loading, setLoading] = useState(false);
  const [card, setCard] = useState(null);
  const [error, setError] = useState(null);

  async function analyze(addrArg) {
    const w = (typeof addrArg === "string" ? addrArg : wallet).trim();
    if (!w) return;
    setLoading(true);
    setCard(null);
    setError(null);
    try {
      const resp = await fetch(`${API}/analyze?wallet=${encodeURIComponent(w)}`);
      const data = await resp.json();
      if (!resp.ok || data.error) {
        setError({ reason: data.error || `HTTP ${resp.status}`, message: data.message || t("请求失败") });
      } else {
        setCard(data);
      }
    } catch (e) {
      setError({ reason: "NETWORK", message: t("无法连接后端服务，请稍后重试。") });
    } finally {
      setLoading(false);
    }
  }

  const showHome = !card && !loading && !error;     // 示例流：仅空态
  const showIntro = !card && !error;                // 副标题：空态 + loading 都留，锁住 cmdbar 位置防跳动
  function pickExample(addr) {
    setWallet(addr);
    analyze(addr);
  }

  return (
    <>
      {showIntro && (
        <div className="console-sub">
          {t("输入 Polymarket 政治盘大户钱包,AI 解读他在赌什么、现在还值不值得跟")}
        </div>
      )}

      {/* 输入区：左侧青色 > 光标 + 输入框 + 解读按钮 */}
      <div className={`cmdbar ${loading ? "busy" : ""}`}>
        <span className="cmd-prompt">&gt;</span>
        {showHome && !wallet && <span className="cmd-caret" />}
        <input
          className="cmd-input num"
          value={wallet}
          onChange={(e) => setWallet(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && analyze()}
          placeholder={t("输入 Polymarket 钱包地址")}
          spellCheck={false}
        />
        <button className="cmd-trigger" onClick={() => analyze()} disabled={loading || !wallet.trim()}>
          {loading ? t("解读中") : t("解读")}
        </button>
      </div>

      {showHome && (
        <div className="monitor">
          <div className="mon-head">{t("试试这几个大户 · 点击解读")}</div>
          <div className="mon-list">
            {EXAMPLES.map((e) => (
              <button className="mon-row" key={e.addr} onClick={() => pickExample(e.addr)}>
                <span className="mon-dot" />
                <span className="mon-nick">{e.nick}</span>
                <span className="mon-addr num">{abbrev(e.addr)}</span>
                <span className="mon-pnl">
                  <span className="mon-pnl-lab">{t("累计盈利")}</span>
                  <span className="mon-pnl-val num">{e.pnl}</span>
                </span>
              </button>
            ))}
          </div>
          <div className="mon-foot">
            <a className="sys-cta" href={TRADERS_URL} target="_blank" rel="noreferrer">
              {t("想分析其他大户?浏览政治盘大户榜 ↗")}
            </a>
            <a className="sys-source" href={LEADERBOARD_URL} target="_blank" rel="noreferrer">
              {t("数据来源:Polymarket 官方盈利榜 ↗")}
            </a>
          </div>
        </div>
      )}

      {loading && <LoadingStages note={t("未缓存的钱包要真跑全链（数据层 → 双向催化剂 → 多空对抗三连调），约 1-3 分钟；已缓存钱包会秒回。")} />}
      {error && <ErrorBox error={error} />}
      {card && <Card card={card} />}
    </>
  );
}
