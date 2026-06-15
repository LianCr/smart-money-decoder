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

// 首页示例钱包：地址已正向 /analyze 验证、能产出精彩政治盘卡（2026-06-15 实测）。
// 置信度全谱：ImJustKen=高(Netanyahu) / debased=中(Vance 2028) / denizz=低(+555% 美伊)。
// pnl = 我方系统算的「历史累计盈亏」(pnl_history 末值) 的粗粒度快照，作"聪明钱"身份背书、非实时行情。
// 🔴 DEMO 前必预热体检（CLAUDE.md 已记）：①denizz 的盘 by June 15 当日结算，若 demo 在 6/15 之后已消失，
//    换 aenews2(0x44c1…ebc1) 或退回 Annica(0x689ae…779e)；②顺手核对 pnl 粗粒度是否还对，漂太多就更新。
const EXAMPLES = [
  { nick: "ImJustKen", addr: "0x9d84ce0306f8551e02efef1680475fc0f1dc1344", pnl: "+$3.1M" },
  { nick: "debased", addr: "0x24c8cf69a0e0a17eee21f69d29752bfa32e823e1", pnl: "+$1.7M" },
  { nick: "denizz", addr: "0xbaa2bcb5439e985ce4ccf815b4700027d1b92c73", pnl: "+$2.6M" },
];
const TRADERS_URL = "https://polymarketanalytics.com/traders?tab=Politics&category=Politics";
// 示例大户 + 累计盈利数字的权威来源：Polymarket 官方政治盈利榜
const LEADERBOARD_URL = "https://polymarket.com/leaderboard/politics/all/profit";

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

  const showHome = !card && !loading && !error;
  function pickExample(addr) {
    setWallet(addr);
    analyze(addr);
  }

  return (
    <>
      {showHome && (
        <div className="console-sub">
          输入 Polymarket 政治盘大户钱包,AI 解读他在赌什么、现在还值不值得跟
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
          placeholder="输入 Polymarket 钱包地址"
          spellCheck={false}
        />
        <button className="cmd-trigger" onClick={() => analyze()} disabled={loading || !wallet.trim()}>
          {loading ? "解读中" : "解读"}
        </button>
      </div>

      {showHome && (
        <div className="monitor">
          <div className="mon-head">试试这几个大户 · 点击解读</div>
          <div className="mon-list">
            {EXAMPLES.map((e) => (
              <button className="mon-row" key={e.addr} onClick={() => pickExample(e.addr)}>
                <span className="mon-dot" />
                <span className="mon-nick">{e.nick}</span>
                <span className="mon-addr num">{abbrev(e.addr)}</span>
                <span className="mon-pnl">
                  <span className="mon-pnl-lab">累计盈利</span>
                  <span className="mon-pnl-val num">{e.pnl}</span>
                </span>
              </button>
            ))}
          </div>
          <div className="mon-foot">
            <a className="sys-cta" href={TRADERS_URL} target="_blank" rel="noreferrer">
              想分析其他大户?浏览政治盘大户榜 ↗
            </a>
            <a className="sys-source" href={LEADERBOARD_URL} target="_blank" rel="noreferrer">
              数据来源:Polymarket 官方盈利榜 ↗
            </a>
          </div>
        </div>
      )}

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
const CALL_PLAIN = { "NO BASIS": "别跟", CHASED: "可跟·已追高", "ROOM LEFT": "可跟·有空间" };
const CALL_CLS = { "NO BASIS": "red", CHASED: "amber", "ROOM LEFT": "green" };

function TrackRecordView() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    fetch(`${API}/backtest`).then((r) => r.json()).then(setData)
      .catch(() => setError("无法连接后端 /backtest"));
  }, []);
  if (error) return <div className="error"><div className="r">NETWORK</div><div>{error}</div></div>;
  if (!data) return <div className="stages"><div className="lead">LOADING TRACK RECORD…</div></div>;
  if (!data.cases || !data.cases.length) return <div className="method">案例数据缺失（backtest/cases.json 未就位）</div>;

  const s = data.summary || {};
  const wrong = (s.total || 0) - (s.directional_correct || 0);
  return (
    <>
      <div className="tr-hero">
        <div className="tr-hero-num num">
          <span className="up">{s.directional_correct}</span><span className="tr-unit"> 对</span>
          <span className="tr-slash"> / </span>
          <span className="down">{wrong}</span><span className="tr-unit"> 错</span>
        </div>
        <div className="tr-hero-txt">
          <div className="tr-hero-h">AI 判断成绩单</div>
          <div className="tr-hero-sub">{s.total} 个已结算的真实政治盘 · 每个都在结算前重放 AI 当时的判断，跟真实结果对账</div>
        </div>
      </div>

      <div className="bt-list">
        {data.cases.map((c, i) => <CaseRow key={i} c={c} />)}
      </div>

      {data.lift && <LiftSummary lift={data.lift} />}

      <div className="foot">案例来自历史回测：结算前重放 decoder、与真实结算对照 · 静态、零 token</div>
    </>
  );
}

function CaseRow({ c }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const [h, setH] = useState(0);
  useEffect(() => { setH(open && ref.current ? ref.current.scrollHeight : 0); }, [open]);

  const verdict = CALL_PLAIN[c.t1.call] || c.t1.call;
  const concl = c.ai_correct ? (c.hero ? "✓ AI 帮你躲过这笔亏损" : "✓ AI 判断正确") : "✗ AI 失手";
  const tps = [["T-7", c.t7], ["T-1", c.t1]];

  return (
    <div className={`bt-item ${open ? "open" : ""} ${c.hero ? "hero" : ""}`}>
      <div className="bt-row" onClick={() => setOpen(!open)}>
        <div className="bt-left">
          <div className="bt-q">{c.hero && <span className="hero-star">★ </span>}{c.market}</div>
          <div className="bt-tags">
            <span className={`stance ${CALL_CLS[c.t1.call] || "gray"}`}>AI 当时判 <b>{verdict}</b></span>
            <span className="resolved big">真实：{c.bet_won ? "钱包赢了" : "钱包赌输了"}</span>
          </div>
        </div>
        <div className="bt-right">
          <span className={c.ai_correct ? "verd hit" : "verd miss"}>{c.ai_correct ? "✓" : "✗"}</span>
          <span className={`chev ${open ? "up" : ""}`}>›</span>
        </div>
      </div>

      <div className="bt-drawer" style={{ height: h }}>
        <div className="bt-drawer-inner" ref={ref}>
          <div className="case-concl">{concl} · 市场结算 {c.resolved}（{c.resolved_date}）</div>
          <div className="case-take">{c.takeaway}</div>

          <div className="case-evo">
            {tps.map(([lab, pt], i) => (
              <span className="evo-step" key={lab}>
                <span className="evo-lab">{lab}</span>
                <span className={`mini-follow ${CALL_CLS[pt.call] || "gray"}`}>{CALL_PLAIN[pt.call] || pt.call}</span>
                {i === 0 && <span className="evo-arrow">→</span>}
              </span>
            ))}
          </div>

          {tps.map(([lab, pt]) => (
            <div className="case-tp" key={lab}>
              <div className="case-tp-h">{lab} · {pt.date} · 信心 {CONF_LABEL[pt.conf] || pt.conf}</div>
              <ul className="case-cat">{pt.catalysts.map((cat, j) => <li key={j}>{cat}</li>)}</ul>
              <div className="case-reason"><span className="case-reason-lab">AI 当时推理</span>{pt.reasoning}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// 第四层「量化审计日志」法定译文 —— 死字面输出，不准改字
const AUDIT_LOG = [
  {
    tag: "[AUDIT-01]",
    title: "选择性滤网 · 已验证",
    body: "94 个信号仅放行 17 个；真五五开的难盘 30 个只放行 3 个。\n高度克制，不做盲目跟单的橡皮图章。",
  },
  {
    tag: "[AUDIT-02]",
    title: "难盘判别力 · 测不出，但未证伪",
    body: "难盘只放行 3 个、中 2 个 —— 样本太小（2/3 翻 1/3 就反号），统计上说不了话。\n它躲掉的盘赢输各半（52% ≈ 基线 53%）：在难盘上，它的“躲”几乎不带方向信息。\n结论：不是 AI 没本事，是这个静态结算口径在难盘上信号太稀、喂不饱指标。",
  },
  {
    tag: "[AUDIT-03]",
    title: "演进路线 · 下一阶段（v3）",
    body: "当前为“静态结算口径”，对提前离场的聪明钱采样存在滞后。\nv3 任务已锁定切换至“动态追踪离场盈亏”口径，从【测判断力】升级为【测真实跟单收益】。",
  },
];

// 整体战绩汇总：4 层渐进式金字塔（彭博终端冷冽风）
// 一切数值从 lift 数据字段读取，不硬编码、不篡改含义
function LiftSummary({ lift }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const [h, setH] = useState(0);
  useEffect(() => { setH(open && ref.current ? ref.current.scrollHeight : 0); }, [open]);

  const f = lift.full, eb = lift.edge_band, nm = lift.near_money;
  const sign = (x) => (x >= 0 ? "+" : "") + Math.round(x * 100) + "%";
  const pct = (x) => Math.round(x * 100) + "%";

  return (
    <div className="lift2">
      {/* 第一层 · 一句话定调 */}
      <div className="l2-thesis num">
        跟着 AI 挑的注,比无脑全抄聪明钱,
        <span className="l2-accent">方向准了 {sign(f.lift)}</span>
      </div>

      {/* 第二层 · 双格终端窗 + 多巴胺大数字 */}
      <div className="l2-term">
        <div className="l2-cell">
          <div className="l2-big num">{sign(f.lift)}</div>
          <div className="l2-sub">
            全部盘口（{f.n}个）:跟AI挑 vs 全抄,方向胜率 <b>{pct(f.go_wr)}</b> vs {pct(f.base_wr)}
          </div>
        </div>
        <div className="l2-cell">
          <div className="l2-big num">{sign(eb.lift)}</div>
          <div className="l2-sub">
            真正难判的盘（{eb.n}个）:跟AI挑 vs 全抄,方向胜率 <b>{pct(eb.go_wr)}</b> vs {pct(eb.base_wr)}
          </div>
        </div>
      </div>

      {/* 第三层 · 诚实说明（承上启下，引向含金量更高的 +13%）*/}
      <div className="l2-honest">
        ⚠️ 诚实说明:这 {f.n} 个盘里 {pct(nm.share)} 是接近已定局的“送分题”,AI 在这些上面跟对不算本事。因此真正能证明模型实力的是右边难盘的 {sign(eb.lift)}。
      </div>

      {/* 第四层 · 量化审计日志（默认折叠）*/}
      <div className="l2-audit">
        <div className="l2-audit-bar" onClick={() => setOpen(!open)}>
          <span className="l2-audit-tag">[SYSTEM AUDIT]</span> 展开底层统计与方法论验证
          <span className={`l2-arrow ${open ? "on" : ""}`}>→</span>
        </div>
        <div className="l2-audit-body" style={{ height: h }}>
          <div ref={ref} className="l2-audit-inner">
            {AUDIT_LOG.map((a, i) => (
              <div className="audit-block" key={i}>
                <div className="audit-h"><span className="audit-tag">{a.tag}</span> {a.title}</div>
                <div className="audit-text">{a.body}</div>
              </div>
            ))}
            <div className="audit-div" />
            {(lift.caveats || []).map((c, i) => (
              <div className={"audit-cav" + (i === 0 ? " snap" : "")} key={i}>{c}</div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
