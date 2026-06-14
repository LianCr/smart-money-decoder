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

function abbrev(addr) {
  return addr && addr.length > 12 ? `${addr.slice(0, 6)}…${addr.slice(-4)}` : addr;
}
function avatarColor(addr) {
  let h = 0;
  for (let i = 2; i < (addr || "").length; i++) h = (h * 31 + addr.charCodeAt(i)) % 360;
  return `hsl(${h}, 42%, 42%)`;
}
function avatarInitials(addr) {
  return (addr || "0x").slice(2, 4).toUpperCase();
}
function fmtPnlCompact(v) {
  const s = v < 0 ? "-" : "+";
  const a = Math.abs(v);
  if (a >= 1e6) return `${s}$${(a / 1e6).toFixed(2)}M`;
  if (a >= 1e3) return `${s}$${(a / 1e3).toFixed(1)}K`;
  return `${s}$${a.toFixed(0)}`;
}
// unix 秒 → "YYYY-MM"
function fmtMonth(t) {
  const d = new Date(t * 1000);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}
// decoder 的"跟/躲"：ROOM LEFT/CHASED=跟（背书），NO BASIS=躲（不背书）
function decoderStance(fc) {
  const follow = fc === "ROOM LEFT" || fc === "CHASED";
  return { word: follow ? "跟" : "躲", cls: follow ? "stance-follow" : "stance-avoid" };
}
// 难度系数 → 三档标签（建仓价距 0.5 越近越难）
function difficultyTier(d) {
  if (typeof d !== "number") return { label: "难度不可得", cls: "diff-na", pct: "—" };
  const pct = `${Math.round(d * 100)}%`;
  if (d >= 0.7) return { label: "迷雾博弈 Coin-Flip", cls: "diff-hard", pct };
  if (d >= 0.4) return { label: "倾斜中 Leaning", cls: "diff-mid", pct };
  return { label: "近明牌 Near-Settled", cls: "diff-easy", pct };
}

function Avatar({ profile }) {
  const [err, setErr] = useState(false);
  const addr = profile.address || "";
  if (profile.profile_image && !err) {
    return <img className="avatar" src={profile.profile_image} onError={() => setErr(true)} alt="" />;
  }
  return <div className="avatar" style={{ background: avatarColor(addr) }}>{avatarInitials(addr)}</div>;
}

function WalletHeader({ profile }) {
  const addr = profile.address || "";
  const nick = profile.name || profile.pseudonym || abbrev(addr);
  return (
    <div className="wallet-head">
      <Avatar profile={profile} />
      <div className="wmeta">
        <div className="wnick">{nick}</div>
        <div className="waddr num">{addr}</div>
      </div>
    </div>
  );
}

// 极简 PnL 折线：纯 SVG，无图表库、无交互、无 tooltip
// 把曲线按零线拆成 green/red 子段（水下=红）；全为正时返回单段
function pnlSegments(points, x, y) {
  const segs = [];
  let cur = [], curNeg = points[0].p < 0;
  for (let i = 0; i < points.length; i++) {
    const p = points[i].p, neg = p < 0;
    if (i > 0 && neg !== curNeg) {
      const p0 = points[i - 1].p, t = p0 / (p0 - p);          // 线性插值零交叉点
      const xc = x(i - 1) + (x(i) - x(i - 1)) * t, yc = y(0);
      cur.push([xc, yc]); segs.push({ neg: curNeg, pts: cur });
      cur = [[xc, yc]]; curNeg = neg;
    }
    cur.push([x(i), y(points[i].p)]);
  }
  if (cur.length) segs.push({ neg: curNeg, pts: cur });
  return segs.map((s) => ({
    neg: s.neg,
    d: s.pts.map((c, j) => `${j ? "L" : "M"}${c[0].toFixed(1)},${c[1].toFixed(1)}`).join(" "),
  }));
}

function PnlChart({ points }) {
  const n = points.length;
  const W = 600, H = 84, pad = 10;
  const ps = points.map((d) => d.p);
  const min = Math.min(...ps), max = Math.max(...ps), span = max - min || 1;
  const x = (i) => (i / (n - 1)) * W;
  const y = (p) => pad + (1 - (p - min) / span) * (H - 2 * pad);
  const last = ps[n - 1], first = ps[0];
  const underwater = min < 0;
  const color = last >= first ? "var(--green)" : "var(--red)";
  const segs = pnlSegments(points, x, y);
  const area = `M0,${y(first)} ${points.map((d, i) => `L${x(i).toFixed(1)},${y(d.p).toFixed(1)}`).join(" ")} L${W},${H} L0,${H} Z`;
  // 当前值端点 + 峰值点（百分比定位，HTML 圆点不被 SVG 拉伸）
  const lastTop = (y(last) / H) * 100;
  const peakIdx = ps.indexOf(max);
  const peakLeft = Math.min(Math.max((peakIdx / (n - 1)) * 100, 6), 82);
  const peakTop = (y(max) / H) * 100;

  return (
    <div className="pnlchart">
      <div className="pc-top">
        <span className="pc-lab">CUMULATIVE PnL · 该钱包历史累计盈亏</span>
        <span className="pc-val" style={{ color }}>{fmtPnlCompact(last)}</span>
      </div>
      <div className="pc-chart">
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
          <path d={area} fill={color} opacity="0.08" />
          {underwater && <line x1="0" x2={W} y1={y(0)} y2={y(0)} className="pc-zero" />}
          {segs.map((s, i) => (
            <path key={i} className="pc-line" d={s.d} fill="none" pathLength="1"
              stroke={s.neg ? "var(--red)" : "var(--green)"} strokeWidth="2" vectorEffect="non-scaling-stroke" />
          ))}
        </svg>
        <span className="pc-dot" style={{ left: "calc(100% - 4px)", top: `calc(${lastTop}% - 4px)`, background: color }} />
        <span className="pc-peak" style={{ left: `${peakLeft}%`, top: `${peakTop}%` }}>peak {fmtPnlCompact(max)}</span>
      </div>
      <div className="pc-axis">
        <span>{fmtMonth(points[0].t)}</span>
        <span>{fmtMonth(points[n - 1].t)}</span>
      </div>
    </div>
  );
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
      {card.profile && <WalletHeader profile={card.profile} />}
      {card.pnl_history && card.pnl_history.length > 1 && <PnlChart points={card.pnl_history} />}

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
  // 无样本的桶显示 "—" 而非 "0%"（0/0 不是 0% 命中率，避免误导）
  const rate = (b) => (b.total ? `${pct(b)}%` : "—");
  const hiStr = rate(o.high_conf), loStr = rate(o.low_conf);
  // 仅当两桶都有样本、且高信心确实更准时，才给高的那个强调色
  const calibrated = o.high_conf.total > 0 && o.low_conf.total > 0 && pct(o.high_conf) > pct(o.low_conf);

  return (
    <>
      {data._mock && (
        <div className="mocktag">MOCK · 回测 pipeline 待接入，以下为占位样本</div>
      )}

      {/* 方法论说明：老实告诉用户这测的是什么 */}
      <div className="method">
        <b>这页测什么</b>：对每个已结算的政治盘，在它结算前的 <b>T-7 / T-1</b> 两个历史时点
        重放 decoder，用它<b>当时</b>的判断（跟 / 躲）对照<b>真实结算结果</b>，统计命中率。
        <b>难度系数</b>按建仓价距 0.5 的远近衡量——越靠 0.5 越是迷雾博弈，越靠 0/1 越是近明牌。
      </div>

      {/* 战绩总览条：整页唯一大数字区 */}
      <div className="overview">
        <div className="ov-block">
          <div className="ov-num num">{o.directional.hits}<span className="slash">/</span>{o.directional.total}</div>
          <div className="ov-lab">方向命中 · DIRECTIONAL</div>
        </div>
        <div className="ov-sep" />
        <div className="ov-block">
          <div className="ov-num num calib">
            <span className={calibrated ? "accent" : ""}>{hiStr}</span>
            <span className="vs">/</span>
            <span className="muted">{loStr}</span>
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
  const [tp, setTp] = useState("t1"); // 展开后看哪个时点（默认 T-1，与默认行判断一致）
  const ref = useRef(null);
  const [h, setH] = useState(0);
  // 抽屉平滑展开：量内容 scrollHeight，对 height 做 transition（纯 CSS，无库）
  useEffect(() => {
    setH(open && ref.current ? ref.current.scrollHeight : 0);
  }, [open, tp]);

  const card = tp === "t7" ? s.t7_card : s.t1_card;
  const snapDate = tp === "t7" ? s.t7_date : s.t1_date;
  const banner = `Snapshot as of ${snapDate} — market resolved ${s.resolved_outcome} on ${s.resolved_date}`;

  // 默认行：decoder 当时判断按 T-1（hit 即按 T-1 算）
  const stance = decoderStance(s.t1_card.follow_call);
  const diff = difficultyTier(s.difficulty);
  const fcls = FOLLOW_CLASS[s.t1_card.follow_call] || "gray";

  return (
    <div className={`bt-item ${open ? "open" : ""}`}>
      <div className="bt-row" onClick={() => setOpen(!open)}>
        <div className="bt-left">
          <div className="bt-q">{s.market_question}</div>
          <div className="bt-tags">
            <span className={`stance ${fcls}`}>
              Decoder <b className={stance.cls}>{stance.word}</b> · {s.t1_card.follow_call} · {CONF_LABEL[s.t1_card.confidence] || s.t1_card.confidence}
            </span>
            <span className="resolved big">RESOLVED {s.resolved_outcome}</span>
            <span className={`difftag ${diff.cls}`}>{diff.label} · {diff.pct}</span>
          </div>
        </div>
        <div className="bt-right">
          <span className={s.hit ? "verd hit" : "verd miss"}>{s.hit ? "✓" : "✗"}</span>
          <span className={`chev ${open ? "up" : ""}`}>›</span>
        </div>
      </div>

      <div className="bt-drawer" style={{ height: h }}>
        <div className="bt-drawer-inner" ref={ref}>
          {/* T-7→T-1 判断演变（移入抽屉） */}
          <div className="bt-evo">
            <div className="tp"><span className="tp-lab">T-7</span><MiniFollow card={s.t7_card} /></div>
            <span className="evo" />
            <div className="tp"><span className="tp-lab">T-1</span><MiniFollow card={s.t1_card} /></div>
          </div>
          <div className="tp-toggle">
            <button className={tp === "t7" ? "on" : ""} onClick={() => setTp("t7")}>T-7 · {s.t7_date}</button>
            <button className={tp === "t1" ? "on" : ""} onClick={() => setTp("t1")}>T-1 · {s.t1_date}</button>
          </div>
          <Card card={card} banner={banner} />
        </div>
      </div>
    </div>
  );
}
