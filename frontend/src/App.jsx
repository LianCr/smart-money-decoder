import { useState } from "react";

const API = "http://localhost:8000";

// follow_call → 配色
const FOLLOW_CLASS = { "ROOM LEFT": "green", CHASED: "yellow", "NO BASIS": "red" };
// relation → 标签样式 + 中文label
const RELATION = {
  BEFORE_ENTRY: { cls: "before", label: "建仓前 · 疑似触发" },
  AFTER_ENTRY: { cls: "after", label: "建仓后 · 走势验证" },
  UNANCHORED: { cls: "unanchored", label: "未锚定 · 仅作背景" },
};
const CONF_LABEL = { high: "高", medium: "中", low: "低" };

function fmtPrice(p) {
  return typeof p === "number" ? p.toFixed(3) : "未知";
}
function fmtMoney(v) {
  return typeof v === "number"
    ? "$" + v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : "未知";
}

export default function App() {
  const [wallet, setWallet] = useState("");
  const [loading, setLoading] = useState(false);
  const [card, setCard] = useState(null);
  const [error, setError] = useState(null);

  async function analyze() {
    const w = wallet.trim();
    if (!w) return;
    setLoading(true);
    setCard(null);
    setError(null);
    try {
      const resp = await fetch(`${API}/analyze?wallet=${encodeURIComponent(w)}`);
      const data = await resp.json();
      if (!resp.ok || data.error) {
        setError({ reason: data.error || `HTTP ${resp.status}`, message: data.message || "请求失败" });
      } else {
        setCard(data);
      }
    } catch (e) {
      setError({ reason: "NETWORK", message: `无法连接后端 ${API}，请确认 uvicorn 已启动。(${e.message})` });
    } finally {
      setLoading(false);
    }
  }

  function onKey(e) {
    if (e.key === "Enter") analyze();
  }

  return (
    <div className="wrap">
      <h1>🔍 Smart Money Decoder</h1>
      <p className="sub">输入 Polymarket 钱包地址，解读其最大政治盘仓位 · 仅公开数据 AI 解读，非投资建议</p>

      <div className="searchbar">
        <input
          value={wallet}
          onChange={(e) => setWallet(e.target.value)}
          onKeyDown={onKey}
          placeholder="0x… 钱包地址"
          spellCheck={false}
        />
        <button onClick={analyze} disabled={loading || !wallet.trim()}>
          {loading ? "解读中…" : "Analyze"}
        </button>
      </div>

      {loading && (
        <div className="loading">
          <span className="spinner" />
          正在跑完整链路（持仓 → 建仓时间 → 时间窗新闻 → AI 解读），约需十几秒…
        </div>
      )}

      {error && (
        <div className="error">
          <div className="reason">⚠️ {error.reason}</div>
          <div>{error.message}</div>
        </div>
      )}

      {card && <Card card={card} />}
    </div>
  );
}

function Card({ card }) {
  const pi = card.price_info || {};
  const followCls = FOLLOW_CLASS[card.follow_call] || "gray";
  const cashPnl = pi.cash_pnl;
  const pnlPct = pi.pnl_pct;
  const resDate = card.resolution_date ? card.resolution_date.slice(0, 10) : "未知";

  return (
    <div className="card">
      <div className="head">
        <div className="q">{card.market_question}</div>
        <div className="meta">
          方向：<b>{card.outcome}</b> · 结算：{resDate} ·{" "}
          {card.time_anchored ? "新闻已锚定建仓时间窗" : "新闻未锚定（近30天兜底）"}
        </div>
      </div>

      <div className="section">
        <h3>🎯 这是在赌什么</h3>
        <p>{card.what_bet}</p>
      </div>

      <div className="section">
        <h3>📰 催化剂</h3>
        {card.catalyst && card.catalyst.length > 0 ? (
          card.catalyst.map((c, i) => {
            const rel = RELATION[c.relation] || { cls: "unanchored", label: c.relation };
            return (
              <div className="cat" key={i}>
                <a href={c.url} target="_blank" rel="noreferrer">
                  {c.title}
                </a>
                <div className="relrow">
                  <span className={`tag ${rel.cls}`}>{rel.label}</span>
                  <span className="date">{c.published_at}</span>
                </div>
                <div className="why">{c.why_relevant}</div>
              </div>
            );
          })
        ) : (
          <div className="empty-cat">未发现可归因的催化剂新闻（如实留空，未编造故事）</div>
        )}
      </div>

      <div className="section">
        <h3>💰 价格 / 盈亏（代码直填，不经 AI）</h3>
        <div className="prices">
          <div className="row">
            <span className="k">买入均价</span>
            <span>{fmtPrice(pi.entry_price)}</span>
          </div>
          <div className="row">
            <span className="k">当前市价</span>
            <span>{fmtPrice(pi.current_price)}</span>
          </div>
          <div className="row">
            <span className="k">持仓价值</span>
            <span>{fmtMoney(pi.position_value)}</span>
          </div>
          <div className="row">
            <span className="k">浮动盈亏</span>
            <span className={typeof cashPnl === "number" ? (cashPnl >= 0 ? "pos" : "neg") : ""}>
              {fmtMoney(cashPnl)}
              {typeof pnlPct === "number" ? `  (${pnlPct >= 0 ? "+" : ""}${pnlPct.toFixed(2)}%)` : ""}
            </span>
          </div>
        </div>
      </div>

      <div className="section">
        <h3>⚖️ 边际空间</h3>
        <p>{card.edge_analysis}</p>
      </div>

      <div className="section">
        <h3>🔮 跟单建议</h3>
        <div className="verdict">
          <span className={`pill ${followCls}`}>{card.follow_call}</span>
          <span className="conf">
            置信度：<b>{CONF_LABEL[card.confidence] || card.confidence}</b>
          </span>
        </div>
        <p style={{ marginTop: 12 }}>{card.reasoning}</p>
      </div>

      {card.warnings && card.warnings.length > 0 && (
        <div className="section">
          <h3>⚠️ 降级提示</h3>
          <div className="warn">
            <ul>
              {card.warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          </div>
        </div>
      )}

      <div className="disclaimer">仅为公开数据 AI 解读，非投资建议。</div>
    </div>
  );
}
