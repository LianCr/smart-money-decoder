import { useState, useEffect, useRef } from "react";

const API = "http://localhost:8000";

const FOLLOW_CLASS = { "ROOM LEFT": "green", CHASED: "amber", "NO BASIS": "red" };
const RELATION = {
  BEFORE_ENTRY: { cls: "before", label: "BEFORE ENTRY" },
  AFTER_ENTRY: { cls: "after", label: "AFTER ENTRY" },
  UNANCHORED: { cls: "unanchored", label: "UNANCHORED" },
};
const CONF_LABEL = { high: "HIGH", medium: "MED", low: "LOW" };
const CONF_COLOR = { high: "var(--green)", medium: "var(--amber)", low: "var(--red)" };

const STAGES = ["定位最大政治仓位", "追溯链上建仓时间", "检索时间窗新闻", "AI 解读 / 置信度矩阵"];

function price(p) {
  return typeof p === "number" ? p.toFixed(3) : "—";
}
function money(v) {
  if (typeof v !== "number") return "—";
  const s = v < 0 ? "-" : "+";
  return s + "$" + Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 });
}

export default function App() {
  const [tab, setTab] = useState("decode");
  return (
    <div className="shell">
      <div className="topbar">
        <div className="brand"><span className="dot" />SMART MONEY DECODER</div>
        <button className={`tab ${tab === "decode" ? "active" : ""}`} onClick={() => setTab("decode")}>
          Decode
        </button>
        <button className={`tab ${tab === "track" ? "active" : ""}`} onClick={() => setTab("track")}>
          Track Record
        </button>
      </div>
      {tab === "decode" ? <DecodeView /> : <TrackRecordView />}
    </div>
  );
}

function DecodeView() {
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
      setError({ reason: "NETWORK", message: `无法连接后端 ${API}，请确认 uvicorn 已启动。` });
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <div className="searchbar">
        <input
          value={wallet}
          onChange={(e) => setWallet(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && analyze()}
          placeholder="0x… Polymarket 钱包地址"
          spellCheck={false}
        />
        <button onClick={analyze} disabled={loading || !wallet.trim()}>
          {loading ? "解读中" : "Analyze"}
        </button>
      </div>

      {loading && <LoadingStages />}
      {error && (
        <div className="error">
          <div className="r">{error.reason}</div>
          <div>{error.message}</div>
        </div>
      )}
      {card && <Card card={card} />}
    </>
  );
}

// 阶段式进度：单请求在飞，前端按节奏点亮各阶段，营造"情报系统工作"的张力
function LoadingStages() {
  const [active, setActive] = useState(0);
  const timer = useRef();
  useEffect(() => {
    timer.current = setInterval(() => {
      setActive((a) => (a < STAGES.length - 1 ? a + 1 : a));
    }, 3600);
    return () => clearInterval(timer.current);
  }, []);
  const fill = (active / (STAGES.length - 1)) * 100;
  return (
    <div className="stages">
      <div className="lead">PIPELINE RUNNING · 约需十几秒</div>
      <div className="stage-track">
        <div className="track-line" />
        <div className="track-fill" style={{ height: `${fill}%` }} />
        {STAGES.map((s, i) => {
          const cls = i < active ? "done" : i === active ? "active" : "";
          return (
            <div className={`stage ${cls}`} key={i}>
              <span className="pip" />
              {s}
              <span className="tick">✓</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// 可复用解读卡：实时解读与回测快照共用。banner 存在时顶部加时间戳横幅
export function Card({ card, banner }) {
  const pi = card.price_info || {};
  const followCls = FOLLOW_CLASS[card.follow_call] || "gray";
  const cash = pi.cash_pnl;
  const gain = typeof cash === "number" ? cash >= 0 : null;
  const dir = gain === null ? "" : gain ? "up" : "down";
  const resDate = card.resolution_date ? card.resolution_date.slice(0, 10) : "未知";
  const entry = pi.entry_price, curr = pi.current_price;
  const hasEntry = typeof entry === "number";
  const upArrow = hasEntry && typeof curr === "number" ? curr >= entry : null;

  return (
    <div className="card">
      {banner && <div className="snapbanner">{banner}</div>}

      <div className="c-head">
        <div>
          <div className="q">{card.market_question}</div>
          <div className="meta">
            结算 {resDate} · {card.time_anchored ? "新闻锚定建仓窗" : "新闻近30天兜底"}
          </div>
        </div>
        <span className="outcome">{(card.outcome || "").toUpperCase()}</span>
      </div>

      {/* ① 价格对比区 */}
      <div className="pricezone">
        <div className="pblock">
          <span className="lab">Entry</span>
          <span className="val num">{price(entry)}</span>
        </div>
        <span className={`arrow ${dir}`}>{upArrow === null ? "→" : upArrow ? "↗" : "↘"}</span>
        <div className="pblock">
          <span className="lab">Current</span>
          <span className={`val num ${dir}`}>{price(curr)}</span>
        </div>
        <div className="pnl">
          <span className="lab">Unrealized P&L</span>
          <span className={`val num ${dir}`}>{money(cash)}</span>
          {typeof pi.pnl_pct === "number" && (
            <span className={`pct num ${dir}`}>
              {pi.pnl_pct >= 0 ? "+" : ""}{pi.pnl_pct.toFixed(2)}%
            </span>
          )}
        </div>
      </div>

      <div className="sec">
        <h4>What the bet is</h4>
        <p>{card.what_bet}</p>
      </div>

      <div className="sec">
        <h4>Catalyst</h4>
        {card.catalyst && card.catalyst.length > 0 ? (
          card.catalyst.map((c, i) => {
            const rel = RELATION[c.relation] || { cls: "unanchored", label: c.relation };
            return (
              <div className="cat" key={i}>
                <div className="row1">
                  <span className={`rtag ${rel.cls}`}>{rel.label}</span>
                  <span className="date num">{c.published_at}</span>
                </div>
                <a href={c.url} target="_blank" rel="noreferrer">{c.title}</a>
                <div className="why">{c.why_relevant}</div>
              </div>
            );
          })
        ) : (
          <div className="empty-cat">无可归因催化剂新闻 · 如实留空，未编造</div>
        )}
      </div>

      <div className="sec dim">
        <h4>Edge / Reasoning</h4>
        <p>{card.edge_analysis}</p>
        <p>{card.reasoning}</p>
      </div>

      {/* ② follow_call 大徽章 */}
      <div className="verdict">
        <span className={`followbadge ${followCls}`}>{card.follow_call}</span>
        <div className="confbox">
          <span className="lab">Confidence</span>
          <span className="val" style={{ color: CONF_COLOR[card.confidence] || "var(--text-2)" }}>
            {CONF_LABEL[card.confidence] || card.confidence}
          </span>
        </div>
      </div>

      {card.warnings && card.warnings.length > 0 && (
        <div className="warns">
          {card.warnings.map((w, i) => (
            <div className="wline" key={i}><span className="wmark">!</span><span>{w}</span></div>
          ))}
        </div>
      )}

      <div className="foot">仅为公开数据 AI 解读，非投资建议</div>
    </div>
  );
}

// ── Track Record 回测页 ─────────────────────────────────────────────────────
function pct(o) {
  return o.total ? Math.round((o.hits / o.total) * 100) : 0;
}

function TrackRecordView() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetch(`${API}/backtest`)
      .then((r) => r.json())
      .then(setData)
      .catch(() => setError("无法连接后端 /backtest"));
  }, []);

  if (error) return <div className="error"><div className="r">NETWORK</div><div>{error}</div></div>;
  if (!data) return <div className="stages"><div className="lead">LOADING TRACK RECORD…</div></div>;

  const o = data.overview;
  const hi = pct(o.high_conf), lo = pct(o.low_conf);
  const calibrated = hi > lo; // 高信心确实更准 → 给高的那个强调色

  return (
    <>
      {data._mock && (
        <div className="mocktag">MOCK · 回测 pipeline 待接入，以下为占位样本</div>
      )}

      {/* 战绩总览条：整页唯一大数字区 */}
      <div className="overview">
        <div className="ov-block">
          <div className="ov-num num">{o.directional.hits}<span className="slash">/</span>{o.directional.total}</div>
          <div className="ov-lab">方向命中 · DIRECTIONAL</div>
        </div>
        <div className="ov-sep" />
        <div className="ov-block">
          <div className="ov-num num calib">
            <span className={calibrated ? "accent" : ""}>{hi}%</span>
            <span className="vs">/</span>
            <span className="muted">{lo}%</span>
          </div>
          <div className="ov-lab">信心校准 · HIGH / LOW CONF</div>
        </div>
        <div className="ov-sep" />
        <div className="ov-block">
          <div className="ov-num num">
            <span className="up">{o.composition.profitable}</span>
            <span className="slash">+</span>
            <span className="down">{o.composition.loss}</span>
          </div>
          <div className="ov-lab">样本构成 · WIN / LOSS</div>
        </div>
      </div>

      {/* 逐场复盘 */}
      <div className="bt-list">
        {data.samples.map((s, i) => <BacktestRow key={i} s={s} />)}
      </div>
      <div className="foot">回测在历史时点重放 decoder，与真实结算对照 · 失手案例如实展示</div>
    </>
  );
}

function MiniFollow({ card }) {
  const cls = FOLLOW_CLASS[card.follow_call] || "gray";
  return (
    <span className={`mini-follow ${cls}`}>
      {card.follow_call}
      <span className="mini-conf">{CONF_LABEL[card.confidence] || card.confidence}</span>
    </span>
  );
}

function BacktestRow({ s }) {
  const [open, setOpen] = useState(false);
  const [tp, setTp] = useState("t7"); // 展开后看哪个时点
  const card = tp === "t7" ? s.t7_card : s.t1_card;
  const snapDate = tp === "t7" ? s.t7_date : s.t1_date;
  const banner = `Snapshot as of ${snapDate} — market resolved ${s.resolved_outcome} on ${s.resolved_date}`;

  return (
    <div className={`bt-item ${open ? "open" : ""}`}>
      <div className="bt-row" onClick={() => setOpen(!open)}>
        <div className="bt-left">
          <div className="bt-q">{s.market_question}</div>
          <span className="resolved">RESOLVED {s.resolved_outcome}</span>
        </div>
        <div className="bt-mid">
          <div className="tp"><span className="tp-lab">T-7</span><MiniFollow card={s.t7_card} /></div>
          <span className="evo" />
          <div className="tp"><span className="tp-lab">T-1</span><MiniFollow card={s.t1_card} /></div>
        </div>
        <div className="bt-right">
          <span className={s.hit ? "verd hit" : "verd miss"}>{s.hit ? "✓" : "✗"}</span>
          <span className={`chev ${open ? "up" : ""}`}>›</span>
        </div>
      </div>

      {open && (
        <div className="bt-expand">
          <div className="tp-toggle">
            <button className={tp === "t7" ? "on" : ""} onClick={() => setTp("t7")}>T-7 · {s.t7_date}</button>
            <button className={tp === "t1" ? "on" : ""} onClick={() => setTp("t1")}>T-1 · {s.t1_date}</button>
          </div>
          <Card card={card} banner={banner} />
        </div>
      )}
    </div>
  );
}
