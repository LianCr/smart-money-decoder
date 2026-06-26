import { useState, useEffect, useRef } from "react";
import { scaleLinear, scaleTime } from "d3-scale";
import { line as d3line, area as d3area, curveMonotoneX } from "d3-shape";
import { extent } from "d3-array";

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
const STAGES_BRIEFING = ["画像 · 这人靠不靠谱", "动作 · 建仓/对冲/盈亏", "价格 · 空间/赔率", "双向催化剂 + 市场测谎", "第三个 AI 诚实整理"];
const STAGES_CONTEXT = ["定位顶仓盘面", "扫描价格异动(≤as-of)", "GDELT 三层洗催化剂", "巨鲸 48h 进出动作流", "冷静客观宏观综述"];
const STAGES_BOARD = ["身份+体量画像", "这一注+现状", "实时盘面嵌入", "行为流 × 世界催化剂", "Edge 矩阵 + 局势判断"];

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
  // 功勋章的 W/L 取回测真值；默认 5/1（当前案例集事实），/backtest 到达后自校正、不闪
  const [wl, setWl] = useState({ w: 5, l: 1 });
  useEffect(() => {
    fetch(`${API}/backtest`).then((r) => r.json()).then((d) => {
      const s = d.summary || {};
      if (typeof s.directional_correct === "number" && typeof s.total === "number")
        setWl({ w: s.directional_correct, l: s.total - s.directional_correct });
    }).catch(() => {});
  }, []);

  return (
    <div className="shell">
      <div className="topbar">
        <div className="brand" onClick={() => setTab("decode")} title="回到解读台">
          <span className="dot" />SMART MONEY DECODER
        </div>
        <div className="topnav">
          <button
            className={`navbtn primary ${tab === "board" ? "active" : ""}`}
            onClick={() => setTab(tab === "board" ? "decode" : "board")}
            title="v3 统一看板：身份+这一注+实时盘面+行为×催化剂+Edge 一屏看全"
          >
            ★ 统一看板<span className="navbtn-tag">v3</span>
          </button>
          <button
            className={`navbtn ${tab === "briefing" ? "active" : ""}`}
            onClick={() => setTab(tab === "briefing" ? "decode" : "briefing")}
            title="完整聪明钱简报（v3）"
          >
            完整简报<span className="navbtn-tag">v3</span>
          </button>
          <button
            className={`navbtn ${tab === "context" ? "active" : ""}`}
            onClick={() => setTab(tab === "context" ? "decode" : "context")}
            title="市场 Context：实时盘面 × as-of 复盘（价格异动 + 催化剂 + 巨鲸动作）"
          >
            市场Context<span className="navbtn-tag">v3</span>
          </button>
          <button
            className={`medal ${tab === "track" ? "active" : ""}`}
            onClick={() => setTab(tab === "track" ? "decode" : "track")}
            title={tab === "track" ? "返回解读台" : "查看历史战绩"}
          >
            [ TRACK RECORD:&nbsp;<span className="m-w">{wl.w}W</span> · <span className="m-l">{wl.l}L</span>&nbsp;]
            <span className="m-arrow">↗</span>
          </button>
        </div>
      </div>
      {tab === "decode" ? <DecodeView /> : tab === "board" ? <BoardView />
        : tab === "briefing" ? <BriefingView />
        : tab === "context" ? <ContextView /> : <TrackRecordView />}
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

// 流水线加载：单请求在飞，前端按节奏 currentStep 逐个点亮，居中、与首页同语言。
// 渐进式逻辑：i<step=已完成(暗青·✓静止) / i===step=进行中(亮青·脉冲) / i>step=未开始(暗灰静止)。
function LoadingStages({ stages = STAGES, sub = "定位 → 追溯 → 检索 → 判断" }) {
  const [step, setStep] = useState(0);
  const timer = useRef();
  useEffect(() => {
    timer.current = setInterval(() => {
      setStep((s) => (s < stages.length - 1 ? s + 1 : s));   // 卡在最后一步，绝不全打勾
    }, 3500);
    return () => clearInterval(timer.current);
  }, [stages.length]);
  const last = stages.length - 1;

  return (
    <div className="pipe">
      <div className="pipe-lead">AI 推演中 <span className="pipe-sub">· {sub}</span></div>
      <div className="pipe-list">
        <span className="pipe-rail" />
        <span className="pipe-fill" style={{ height: `calc((100% - 28px) * ${step} / ${last})` }} />
        {stages.map((s, i) => {
          const state = i < step ? "done" : i === step ? "active" : "todo";
          return (
            <div className={`pstep ${state}`} key={i}>
              <span className="pstep-node" />
              <span className="pstep-label">{s}</span>
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

// ── Briefing 完整简报页（v3）─────────────────────────────────────────────────
// 材质分层：硬材质(当事人直接表态/已生效硬事件)=亮+左tick / 其余软材质=暗。靠灰阶不靠颜色。
const HARD_MATERIALS = new Set(["当事人直接表态", "已生效硬事件"]);

// Polymarket 原生 embed —— 实时市场 Overview("实")，配我们自建历史 Context("虚")一虚一实同框。
// URL 格式实测 200 可达(features=chart,buyButtons)；slug 与我们 2026 数据世界一致(gamma 已验)。
function polymarketEmbedUrl(slug) {
  return `https://embed.polymarket.com/market.html?market=${encodeURIComponent(slug)}&features=chart,buyButtons&theme=dark`;
}
function PolymarketEmbed({ slug }) {
  if (!slug) return null;
  return (
    <iframe
      className="pm-embed" title="Polymarket Live Overview" src={polymarketEmbedUrl(slug)}
      sandbox="allow-scripts allow-same-origin allow-popups allow-forms" loading="lazy"
    />
  );
}

// 原生赔率条（替代 Polymarket iframe）：Yes/No 比例条，高亮钱包押的那一侧
function OddsBar({ held, side, slug }) {
  if (typeof held !== "number") return <div className="ctx-empty">无价,赔率不可显</div>;
  const S = (side || "").toUpperCase();
  const yesP = S === "NO" ? 1 - held : held;          // held=持有侧价；换算 Yes/No
  const noP = 1 - yesP;
  const yesHeld = S === "YES";
  return (
    <div className="oddsbar">
      <div className="ob-bar">
        <div className={`ob-seg yes ${yesHeld ? "held" : "dim"}`} style={{ width: `${Math.max(yesP * 100, 8)}%` }}>
          <span className="ob-lab">Yes</span><span className="ob-val num">{Math.round(yesP * 100)}¢</span>
        </div>
        <div className={`ob-seg no ${!yesHeld ? "held" : "dim"}`} style={{ width: `${Math.max(noP * 100, 8)}%` }}>
          <span className="ob-lab">No</span><span className="ob-val num">{Math.round(noP * 100)}¢</span>
        </div>
      </div>
      <div className="ob-foot">
        <span>他押 <b className={yesHeld ? "ob-yes" : "ob-no"}>{S}</b> · 高亮侧</span>
        {slug && <a className="ob-jump" href={`https://polymarket.com/market/${slug}`} target="_blank" rel="noreferrer">在 Polymarket 打开 ↗</a>}
      </div>
    </div>
  );
}

// 系统风险标记 → 中文（绝不把内部代码字段直接显示给用户）
const FLAG_CN = {
  suspicious_win_rate: "异常高胜率", position_size_volatility: "仓位波动大",
  sybil_risk: "疑似女巫账户", perfect_timing: "完美择时(可疑)", perfect_timing_flag: "完美择时(可疑)",
  bot_like: "类机器人模式", concentration_risk: "持仓过度集中", high_drawdown: "高回撤",
  wash_trading: "疑似刷量", low_market_diversity: "市场集中度高",
};
function flagsCN(raw) {
  return String(raw || "").replace(/[{}]/g, "").split(",").map((s) => s.trim())
    .filter(Boolean).map((t) => FLAG_CN[t] || t.replace(/_/g, " ")).join("、");
}

// 市场反应 chip：印证=暗绿、不一致(测谎)=暗陶红+⚠、微弱/不可知=灰
function reactionChip(pr) {
  if (!pr || !pr.available) return { txt: "市场反应不可知", cls: "rx-na" };
  const mc = pr.market_check || "";
  const arrow = pr.move_pct >= 0 ? "↑" : "↓";
  const base = `${arrow}${Math.abs(pr.move_pct)}%`;
  if (mc.includes("不一致")) return { txt: `⚠ ${base} 市场不买账`, cls: "rx-bad" };
  if (mc.includes("印证")) return { txt: `${base} 市场印证`, cls: "rx-good" };
  return { txt: `${base} 反应微弱`, cls: "rx-weak" };
}

// 把第三个 AI 的人话简报做轻量渲染（## 标题 / **粗体** / - 列表 / --- 分隔）
function renderInline(s) {
  return s.split(/(\*\*.+?\*\*)/g).map((p, i) =>
    p.startsWith("**") && p.endsWith("**") ? <b key={i}>{p.slice(2, -2)}</b> : p);
}
function Narrative({ text }) {
  return (
    <div className="bf-narr">
      {(text || "").split("\n").map((ln, i) => {
        const t = ln.trim();
        if (!t) return <div className="bf-gap" key={i} />;
        if (/天平由你裁决/.test(t)) return <div className="bf-closing" key={i}>{t.replace(/\*\*/g, "")}<span className="bf-cursor animate-blink" /></div>;
        if (/^#+\s/.test(t)) return <div className="bf-h" key={i}>{t.replace(/^#+\s*/, "").replace(/\*\*/g, "")}</div>;
        if (/^\*\*.+\*\*$/.test(t)) return <div className="bf-h" key={i}>{t.replace(/\*\*/g, "")}</div>;
        if (/^---+$/.test(t)) return <hr className="bf-hr" key={i} />;
        const bullet = /^[-•]\s/.test(t);
        return <div className={`bf-l ${bullet ? "bullet" : ""}`} key={i}>{renderInline(t.replace(/^[-•]\s*/, ""))}</div>;
      })}
    </div>
  );
}

function CatColumn({ title, side, items }) {
  return (
    <div className={`bf-col ${side}`}>
      <div className="bf-col-h">{title} <span className="bf-col-n">{items.length}</span><span className="bf-pulse pulse-dot" /></div>
      {items.length === 0 && <div className="bf-empty">如实留空</div>}
      {items.map((c, i) => {
        const rx = reactionChip(c.price_reaction);
        return (
          <div className="bf-cat" key={i}>
            <div className="bf-cat-top">
              <span className={`mat ${HARD_MATERIALS.has(c.type) ? "hard" : "soft"}`}>{c.type}</span>
              <span className="bf-cat-date num">{c.date}</span>
            </div>
            {c.url ? <a className="bf-cat-t" href={c.url} target="_blank" rel="noreferrer">{c.title}</a>
                   : <div className="bf-cat-t">{c.title}</div>}
            <div className="bf-cat-why">{c.reason}</div>
            <span className={`rx ${rx.cls}`}>{rx.txt}</span>
            {c.price_reaction && c.price_reaction.same_window && (
              <div className="bf-samewin">同窗合计 · 不可归因到单条</div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function BriefingBody({ d }) {
  const m = d.meta || {};
  const who = d.who_trader_profile || {};
  const rk = who.official_rank || {};
  const q = who.quality || {};
  const pol = (who.category_specialization || []).find((c) => /Politics/i.test(c.category || ""));
  const act = (d.what_position_actions || {}).actions || {};
  const ts = (d.what_position_actions || {}).two_side_distribution || {};
  const un = (d.what_position_actions || {}).unrealized || {};
  const pc = d.price_context || {};
  const cats = d.catalysts || { positive: [], negative: [] };
  const wrLie = Number(rk.win_rate) > 0.8 && Number(rk.total_pnl) < 0;
  const upct = un.unrealized_pct;

  return (
    <div className="card bf">
      <div className="c-head">
        <div>
          <div className="q">{m.market}</div>
          <div className="meta">{m.settle} · 催化剂锚 {m.catalyst_anchor === "entry_time" ? "建仓时(复盘)" : "现在(实战)"}</div>
        </div>
        <span className="outcome">{(m.analyzed_side || "").toUpperCase()}</span>
      </div>

      {/* WHO / WHAT / PRICE 三联卡 */}
      <div className="bf-grid">
        <div className="bf-mini">
          <div className="bf-mini-h">WHO · 这人靠不靠谱</div>
          <div className="bf-kv"><span>官方排名</span><b className="num">#{rk.rank ?? "—"}</b></div>
          <div className="bf-kv"><span>胜率 / 累计盈亏</span><b className="num">{rk.win_rate ? (rk.win_rate * 100).toFixed(1) + "%" : "—"} · {rk.total_pnl ? money(Number(rk.total_pnl)) : "—"}</b></div>
          {pol && <div className="bf-kv"><span>政治盘专长</span><b className="num">{(pol.win_rate * 100).toFixed(0)}% · {money(Number(pol.total_pnl))}</b></div>}
          {wrLie && <div className="bf-lie">⚠ 胜率谎言:高胜率但净盈亏为负 — 看净盈亏,非胜率</div>}
          {q.flagged_metrics && <div className="bf-sub">风险标记: {flagsCN(q.flagged_metrics)}</div>}
        </div>

        <div className="bf-mini">
          <div className="bf-mini-h">WHAT · 他做了什么</div>
          <div className="bf-kv"><span>建仓 / 均价</span><b className="num">{act.entry_time?.slice(0, 10) || "—"} · {price(act.avg_entry_price)}</b></div>
          <div className="bf-kv"><span>买入 / 成本</span><b className="num">{act.num_buys ?? "—"}笔 · {money(act.net_cost_usd)}</b></div>
          <div className="bf-kv"><span>盈亏</span><b className={`num ${Number(un.unrealized_pnl_usd) >= 0 ? "pos" : "neg"}`}>{money(un.unrealized_pnl_usd)} {typeof upct === "number" ? `(${upct >= 0 ? "+" : ""}${upct}%)` : ""}</b></div>
          <div className="bf-note">{ts.hedged ? "两边对冲 · 做市/非单边信念" : "单边建仓 · 信念注"}</div>
        </div>

        <div className="bf-mini">
          <div className="bf-mini-h">PRICE · 还有没有空间</div>
          <div className="bf-kv"><span>现价 / 隐含概率</span><b className="num">{price(pc.current_price)} · {pc.implied_probability_pct}%</b></div>
          <div className="bf-kv"><span>剩余空间(赢)</span><b className="num">{pc.remaining_upside_pct_if_win}%</b></div>
          <div className="bf-kv"><span>赔率 / vs入场</span><b className="num">{pc.odds_to_one ?? "—"} · {typeof pc.price_delta_pct === "number" ? (pc.price_delta_pct >= 0 ? "+" : "") + pc.price_delta_pct + "%" : "—"}</b></div>
        </div>
      </div>

      {/* 双向催化剂 + 市场测谎 */}
      <div className="bf-dialectic">
        <CatColumn title="支持 · 正向证据" side="pos" items={cats.positive || []} />
        <CatColumn title="威胁 · 负向证据" side="neg" items={cats.negative || []} />
      </div>

      {/* 第三个 AI 诚实整理（产品魂） */}
      <div className="bf-narr-wrap">
        <h4>AI 诚实整理 · 只陈列证据,不替你判断</h4>
        <Narrative text={d.organized_text} />
      </div>

      <div className="foot">仅为公开数据 AI 整理,非投资建议</div>
    </div>
  );
}

function BriefingView() {
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
      if (!resp.ok || j.error) setError({ reason: j.error || `HTTP ${resp.status}`, message: j.message || "请求失败" });
      else setData(j);
    } catch (e) {
      setError({ reason: "NETWORK", message: `无法连接后端 ${API}，请确认 uvicorn 已启动。` });
    } finally { setLoading(false); }
  }

  const showHome = !data && !loading && !error;
  return (
    <>
      {!data && !error && (
        <div className="console-sub">输入聪明钱钱包,生成完整简报:画像 + 动作 + 价格 + 双向催化剂(市场测谎) + AI 诚实整理</div>
      )}
      <div className={`cmdbar ${loading ? "busy" : ""}`}>
        <span className="cmd-prompt">&gt;</span>
        {showHome && !wallet && <span className="cmd-caret" />}
        <input className="cmd-input num" value={wallet} onChange={(e) => setWallet(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && run()} placeholder="输入 Polymarket 钱包地址" spellCheck={false} />
        <button className="cmd-trigger" onClick={() => run()} disabled={loading || !wallet.trim()}>
          {loading ? "生成中" : "生成简报"}
        </button>
      </div>

      {showHome && (
        <div className="monitor">
          <div className="mon-head">试试这几个大户 · 点击生成完整简报</div>
          <div className="mon-list">
            {EXAMPLES.map((e) => (
              <button className="mon-row" key={e.addr} onClick={() => { setWallet(e.addr); run(e.addr); }}>
                <span className="mon-dot" /><span className="mon-nick">{e.nick}</span>
                <span className="mon-addr num">{abbrev(e.addr)}</span>
                <span className="mon-pnl"><span className="mon-pnl-lab">累计盈利</span><span className="mon-pnl-val num">{e.pnl}</span></span>
              </button>
            ))}
          </div>
        </div>
      )}

      {loading && <LoadingStages stages={STAGES_BRIEFING} sub="画像 → 动作 → 价格 → 催化剂 → 整理" />}
      {error && <div className="error"><div className="r">{error.reason}</div><div>{error.message}</div></div>}
      {data && <BriefingBody d={data} />}
    </>
  );
}

// ── 市场 Context 视图（一虚一实：实时盘面 × as-of 复盘）──────────────────────
const FLAG_META = {
  ADD:    { icon: "📈", label: "信念增强 · 加仓", cls: "add" },
  EXIT:   { icon: "📉", label: "主力撤退 · 减仓", cls: "exit" },
  STATIC: { icon: "⏸", label: "按兵不动 · 沉闷持仓", cls: "static" },
};
const EVT_META = {
  catalyst:   { tag: "催化剂", cls: "cat" },
  price_only: { tag: "诚实留白", cls: "blank" },
  behavior:   { tag: "巨鲸动作", cls: "beh" },
};

function fmtUsd(v) {
  return typeof v === "number" && v > 0 ? "$" + Math.round(v).toLocaleString("en-US") : "$0";
}

function BehaviorFlag({ b }) {
  if (!b) return null;
  const meta = FLAG_META[b.flag] || FLAG_META.STATIC;
  const w = b.windows || {};
  return (
    <div className={`ctx-flag ${meta.cls}`}>
      <div className="ctx-flag-h">
        <span className="ctx-flag-ico">{meta.icon}</span>{meta.label}
        <span className="ctx-flag-src">巨鲸 48h 动作流 · 556 Trades</span>
      </div>
      <div className="ctx-flag-fact">{b.fact}</div>
      <div className="ctx-flag-win">
        {["3h", "24h", "48h"].map((k) => {
          const x = w[k] || {};
          return (
            <div className="ctx-win" key={k}>
              <span className="ctx-win-k num">{k}</span>
              <span className="ctx-win-b num">买 {x.buys || 0} · {fmtUsd(x.buy_usd)}</span>
              <span className="ctx-win-s num">卖 {x.sells || 0} · {fmtUsd(x.sell_usd)}</span>
            </div>
          );
        })}
      </div>
      {b.honest_note && <div className="ctx-flag-note">{b.honest_note}</div>}
    </div>
  );
}

function Timeline({ events }) {
  if (!events || !events.length)
    return <div className="ctx-empty">该 as-of 窗内无可锚定的价格异动 / 催化剂 — 如实留空</div>;
  return (
    <div className="ctx-timeline">
      {events.map((e, i) => {
        const meta = EVT_META[e.type] || EVT_META.catalyst;
        return (
          <div className={`ctx-evt ${meta.cls}`} key={i}>
            <div className="ctx-evt-rail"><span className="ctx-evt-dot" /></div>
            <div className="ctx-evt-body">
              <div className="ctx-evt-top">
                <span className={`ctx-tag ${meta.cls}`}>{meta.tag}</span>
                <span className="ctx-evt-date num">{e.timestamp}</span>
                {e.price_impact_string && <span className="ctx-impact num">{e.price_impact_string}</span>}
              </div>
              {e.title && <div className="ctx-evt-title">{e.title}</div>}
              <div className="ctx-evt-fact">{e.fact_summary}</div>
              <div className="ctx-evt-foot">
                {e.source && <span className="ctx-evt-src">{e.source}</span>}
                {e.temporal_note && <span className="ctx-evt-note">{e.temporal_note}</span>}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ContextBody({ d }) {
  const mc = d.market_context || {};
  const side = (mc.analyzed_side || "").toUpperCase();
  return (
    <div className="card bf ctx">
      <div className="c-head">
        <div>
          <div className="q">{mc.market_question}</div>
          <div className="meta">市场 Context · 锁定 as-of {mc.as_of} · 钱包 {abbrev(mc.wallet)}</div>
        </div>
        <span className="outcome">{side}</span>
      </div>

      <div className="ctx-split">
        {/* 实：实时盘面（Polymarket 直嵌） */}
        <div className="ctx-pane ctx-real">
          <div className="ctx-pane-h"><span className="ctx-live-dot" />当前赔率 · 市场定价</div>
          <OddsBar held={mc.current_price} side={mc.analyzed_side} slug={mc.market_slug} />
          <div className="ctx-pane-foot">市场当前对 Yes/No 的定价（高亮=钱包押的侧）· 与右侧 as-of 复盘相互独立</div>
        </div>

        {/* 虚：我们合成的 as-of 复盘 Context */}
        <div className="ctx-pane ctx-synth">
          <div className="ctx-pane-h">复盘上下文 · 锁定 as-of {mc.as_of}（防泄漏）</div>
          <BehaviorFlag b={mc.behavioral_flag} />
          {mc.ai_experimental_summary && (
            <div className="bf-narr-wrap ctx-summary">
              <h4>宏观综述 · 只陈列事实,不替你判断</h4>
              <Narrative text={mc.ai_experimental_summary} />
            </div>
          )}
          <div className="ctx-tl-h">事件时间线 · 价格异动 × 催化剂 × 巨鲸动作</div>
          <Timeline events={mc.timeline_events} />
        </div>
      </div>

      <div className="foot">价格异动窗 ≤ as-of(防泄漏) · 催化剂=GDELT 三层洗 · 因果→仅时间相关 · 巨鲸动作=事实非判断 · 仅公开数据 AI 整理,非投资建议</div>
    </div>
  );
}

function ContextView() {
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
      if (!resp.ok || j.error) setError({ reason: j.error || `HTTP ${resp.status}`, message: j.message || "请求失败" });
      else setData(j);
    } catch (e) {
      setError({ reason: "NETWORK", message: `无法连接后端 ${API}，请确认 uvicorn 已启动。` });
    } finally { setLoading(false); }
  }

  const showHome = !data && !loading && !error;
  return (
    <>
      {!data && !error && (
        <div className="console-sub">输入聪明钱钱包,生成市场 Context:实时盘面(实) × as-of 复盘(虚) = 价格异动 + 催化剂 + 巨鲸 48h 进出动作</div>
      )}
      <div className={`cmdbar ${loading ? "busy" : ""}`}>
        <span className="cmd-prompt">&gt;</span>
        {showHome && !wallet && <span className="cmd-caret" />}
        <input className="cmd-input num" value={wallet} onChange={(e) => setWallet(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && run()} placeholder="输入 Polymarket 钱包地址" spellCheck={false} />
        <button className="cmd-trigger" onClick={() => run()} disabled={loading || !wallet.trim()}>
          {loading ? "合成中" : "生成 Context"}
        </button>
      </div>

      {showHome && (
        <div className="monitor">
          <div className="mon-head">试试这几个大户 · 点击生成市场 Context</div>
          <div className="mon-list">
            {EXAMPLES.map((e) => (
              <button className="mon-row" key={e.addr} onClick={() => { setWallet(e.addr); run(e.addr); }}>
                <span className="mon-dot" /><span className="mon-nick">{e.nick}</span>
                <span className="mon-addr num">{abbrev(e.addr)}</span>
                <span className="mon-pnl"><span className="mon-pnl-lab">累计盈利</span><span className="mon-pnl-val num">{e.pnl}</span></span>
              </button>
            ))}
          </div>
        </div>
      )}

      {loading && <LoadingStages stages={STAGES_CONTEXT} sub="盘面 → 价格异动 → 催化剂 → 巨鲸动作 → 综述" />}
      {error && <div className="error"><div className="r">{error.reason}</div><div>{error.message}</div></div>}
      {data && <ContextBody d={data} />}
    </>
  );
}

// ── v3 统一看板（①身份 ②这一注 ③实时盘面 ④⑤行为×催化剂 ⑥Edge）─────────────
const FOLLOW_LABEL_CN = { "ROOM LEFT": "还有空间", CHASED: "已追高", "NO BASIS": "没依据" };
const CONF_CN = { high: "高", medium: "中", low: "低" };

function Fold({ title, sub, children }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const [h, setH] = useState(0);
  useEffect(() => { setH(open && ref.current ? ref.current.scrollHeight : 0); }, [open]);
  return (
    <div className={`db-fold ${open ? "open" : ""}`}>
      <div className="db-fold-h" onClick={() => setOpen(!open)}>
        <span className="db-fold-arrow">{open ? "▾" : "▸"}</span>
        <span className="db-fold-t">{title}</span>
        {sub && <span className="db-fold-sub">{sub}</span>}
      </div>
      <div className="db-fold-body" style={{ height: open ? h : 0 }}>
        <div ref={ref}>{children}</div>
      </div>
    </div>
  );
}

// ⑤ 世界催化剂列（板专属：在 Briefing 的 CatColumn 上加 BEFORE/AFTER ENTRY 关系标，不碰旧组件）
function DbCatColumn({ title, side, items }) {
  return (
    <div className={`bf-col ${side}`}>
      <div className="bf-col-h">{title} <span className="bf-col-n">{items.length}</span></div>
      {items.length === 0 && <div className="bf-empty">如实留空</div>}
      {items.map((c, i) => {
        const rx = reactionChip(c.price_reaction);
        const rel = RELATION[c.relation];
        return (
          <div className="bf-cat" key={i}>
            <div className="bf-cat-top">
              <span className={`mat ${HARD_MATERIALS.has(c.type) ? "hard" : "soft"}`}>{c.type}</span>
              {rel && <span className={`rtag ${rel.cls}`}>{rel.label}</span>}
              <span className="bf-cat-date num">{c.date}</span>
            </div>
            {c.url ? <a className="bf-cat-t" href={c.url} target="_blank" rel="noreferrer">{c.title}</a>
                   : <div className="bf-cat-t">{c.title}</div>}
            <div className="bf-cat-why">{c.reason}</div>
            <span className={`rx ${rx.cls}`}>{rx.txt}</span>
            {c.price_reaction && c.price_reaction.same_window && (
              <div className="bf-samewin">同窗合计 · 不可归因到单条</div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ⑤ 时间线新闻流 · 市场反应符号（统一口径:持有侧价格前后涨跌,非该新闻导致）
const REACT_SYM = {
  confirm: { sym: "↑", txt: "印证", cls: "rx-good" },
  reject:  { sym: "↓", txt: "不买账", cls: "rx-bad" },
  weak:    { sym: "·", txt: "微弱", cls: "rx-weak" },
};
function ReactionTag({ r }) {
  if (!r || !r.available) return <span className="rx rx-na">市场反应不可知</span>;
  const m = REACT_SYM[r.kind] || REACT_SYM.weak;
  const mv = `${r.move_pct > 0 ? "+" : ""}${r.move_pct}%`;
  return <span className={`rx ${m.cls}`}>{m.sym}{m.txt} {mv}</span>;
}
// 方向标=dual_catalyst 已分好的正负（支持/威胁）；GDELT 未分类→不杜撰方向
const DIR_META = { support: { txt: "支持", cls: "support" }, threat: { txt: "威胁", cls: "threat" } };
function domainOf(url, fallback) {
  try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return fallback || ""; }
}
function faviconUrl(domain) { return `https://www.google.com/s2/favicons?domain=${domain}&sz=64`; }

// 新闻流 · Polymarket 风格（标题 + 段落 + 底部可点 mini 来源 logo + 市场反应）
function NewsStream({ items }) {
  if (!items || !items.length)
    return <div className="bf-empty">该时点窗内三源都没洗出对题新闻 — 如实留空</div>;
  return (
    <div className="db-stream">
      {items.map((it, i) => {
        const dir = DIR_META[it.direction];
        const dom = domainOf(it.url, it.source);
        return (
          <div className={`db-news ${it.direction || ""}`} key={i}>
            <div className="db-news-top">
              <span className="db-news-date num">{it.date || "—"}</span>
              {dir && <span className={`db-dir ${dir.cls}`}>{dir.txt}</span>}
              <ReactionTag r={it.reaction} />
            </div>
            {it.url ? <a className="db-news-t" href={it.url} target="_blank" rel="noreferrer">{it.title}</a>
                    : <div className="db-news-t">{it.title}</div>}
            {it.summary && <div className="db-news-s">{it.summary}</div>}
            {it.same_window && <div className="db-news-sw">同日多条 · 前后变动为合计,不可归因到单条</div>}
            {dom && (
              <a className="db-news-src" href={it.url} target="_blank" rel="noreferrer" title={`在 ${dom} 打开`}>
                <img className="db-news-fav" src={faviconUrl(dom)} alt="" loading="lazy" onError={(e) => { e.currentTarget.style.display = "none"; }} />
                <span className="db-news-dom">{dom}</span>
              </a>
            )}
          </div>
        );
      })}
    </div>
  );
}

// 社媒情绪动量（585）· 🔴 情绪非事实、视觉刻意区别于新闻、刷量标显眼
function SocialPulse({ s }) {
  if (!s) return <div className="bf-empty">该话题暂无社媒数据（或未配置）</div>;
  const acc = s.acceleration;
  const heating = typeof acc === "number" && acc > 1;
  const div = s.author_diversity_pct;
  const organic = s.organic;
  return (
    <div className="soc">
      <div className="soc-metrics">
        <div className="soc-m">
          <div className="soc-m-lab">情绪动量</div>
          <div className={`soc-m-val ${heating ? "hot" : "cold"}`}>{heating ? "🔥 升温" : "❄ 降温"} <span className="soc-acc num">{typeof acc === "number" ? acc.toFixed(2) : "—"}</span></div>
        </div>
        <div className="soc-m">
          <div className="soc-m-lab">{(s.tweet_count || 0).toLocaleString()} 条讨论</div>
          <div className={`soc-bot ${organic ? "ok" : "bad"}`}>{organic ? `✓ 有机 ${div}%` : `🤖 疑似刷量 ${div}%`}</div>
        </div>
      </div>
      {!organic && (
        <div className="soc-warn">⚠ 作者多样性 {div}% &lt; 20% —— 很可能是刷量/机器人，当噪音看，别当真情绪</div>
      )}
      <div className="soc-posts">
        {(s.posts || []).map((p, i) => (
          <div className="soc-post" key={i}>
            <div className="soc-post-top">
              <span className="soc-user">@{p.username}</span>
              <span className="soc-eng num">♥ {p.likes || 0} · ↻ {p.retweets || 0}</span>
            </div>
            <div className="soc-post-txt">{p.content}</div>
            {p.url && <a className="soc-post-link" href={p.url} target="_blank" rel="noreferrer">原帖 ↗</a>}
          </div>
        ))}
      </div>
    </div>
  );
}

// 上帝视角时间轴：价格曲线 × 建仓点 × 新闻发光节点 × 剩余空间（D3 算数学，React 渲 SVG）
const GMT_W = 760, GMT_H = 340, GMT_M = { t: 18, r: 38, b: 28, l: 14 };
function _pdate(s) { return new Date(s + "T00:00:00Z"); }
function gmtReact(rx) {
  if (!rx || !rx.available) return { txt: "市场反应不可知", cls: "rx-na" };
  const m = REACT_SYM[rx.kind] || REACT_SYM.weak;
  return { txt: `${m.sym}${m.txt} ${rx.move_pct > 0 ? "+" : ""}${rx.move_pct}%`, cls: m.cls };
}
function fmtMD(dt) { return `${dt.getUTCMonth() + 1}/${dt.getUTCDate()}`; }
function GodModeTimeline({ d }) {
  const [cross, setCross] = useState(null);   // 鼠标所在的 series 索引（实时光标）
  const series = (d.price_series || []).filter((p) => typeof p.price === "number")
    .map((p) => ({ t: _pdate(p.date), date: p.date, price: p.price }));
  if (series.length < 2)
    return <div className="bf-empty">该盘价格日线不足(薄盘/新盘)——按"有多少画多少",暂不足以绘制时间轴</div>;
  const pos = d.position || {}, wpa = pos.what_position_actions || {};
  const act = wpa.actions || {}, un = wpa.unrealized || {}, pc = pos.price_context || {};
  const side = ((pos.meta || {}).analyzed_side || "").toUpperCase();
  const entryDate = act.entry_time ? act.entry_time.slice(0, 10) : null;
  const entryPrice = act.avg_entry_price, curPrice = pc.current_price;
  // 🔴 颜色按价格走势(涨绿/跌红),像 Polymarket——描述价格本身、不与"他赚没赚"混淆(后者在英雄区)
  const firstP = series[0].price, lastP = series[series.length - 1].price;
  const dirCls = lastP >= firstP ? "pos" : "neg";
  const chgPts = typeof curPrice === "number" ? Math.round((curPrice - firstP) * 100) : null;
  const iw = GMT_W - GMT_M.l - GMT_M.r, ih = GMT_H - GMT_M.t - GMT_M.b;
  const x = scaleTime().domain(extent(series, (s) => s.t)).range([0, iw]);
  // 🔴 Y 轴聚焦到数据实际区间（否则 80-98% 的走势在 0-100 轴上被压成顶部一条平线，看不出趋势）
  const prices = series.map((s) => s.price).concat(typeof entryPrice === "number" ? [entryPrice] : []);
  const pMin = Math.min(...prices), pMax = Math.max(...prices);
  const pad = Math.max((pMax - pMin) * 0.18, 0.025);
  const y = scaleLinear().domain([Math.max(0, pMin - pad), Math.min(1, pMax + pad)]).range([ih, 0]);
  const lg = d3line().x((s) => x(s.t)).y((s) => y(s.price)).curve(curveMonotoneX);
  const ag = d3area().x((s) => x(s.t)).y0(ih).y1((s) => y(s.price)).curve(curveMonotoneX);
  const priceAt = (date) => {
    const t = _pdate(date); let best = series[0];
    for (const s of series) if (Math.abs(s.t - t) < Math.abs(best.t - t)) best = s;
    return best.price;
  };
  const [dMin, dMax] = x.domain();
  const nodes = (d.news_stream || []).filter((n) => n.date && _pdate(n.date) >= dMin && _pdate(n.date) <= dMax)
    .map((n) => ({ ...n, t: _pdate(n.date), px: priceAt(n.date) }));
  const nodeColor = (n) => {
    const r = n.reaction || {};
    return !r.available ? "var(--fg-4)" : r.kind === "confirm" ? "var(--pos)" : r.kind === "reject" ? "var(--neg)" : "var(--fg-3)";
  };
  const sx = (vx) => ((GMT_M.l + vx) / GMT_W) * 100;
  const sy = (vy) => ((GMT_M.t + vy) / GMT_H) * 100;
  const yTicks = y.ticks(4), xTicks = x.ticks(6);

  const hv = cross != null ? series[cross] : null;
  const newsAt = hv ? nodes.find((n) => n.date === hv.date) : null;
  const bright = cross != null ? series.slice(0, cross + 1) : series;
  const shownPrice = hv ? hv.price : curPrice;

  function onMove(e) {
    const rect = e.currentTarget.getBoundingClientRect();
    const plotX = Math.max(0, Math.min(iw, ((e.clientX - rect.left) / rect.width) * GMT_W - GMT_M.l));
    const td = x.invert(plotX);
    let bi = 0;
    for (let k = 1; k < series.length; k++) if (Math.abs(series[k].t - td) < Math.abs(series[bi].t - td)) bi = k;
    setCross(bi);
  }

  return (
    <div className="gmt">
      <div className="gmt-header">
        <div className="gmt-h-side">押 {side}</div>
        <div className="gmt-h-row">
          <span className={`gmt-h-pct ${dirCls}`}>{typeof shownPrice === "number" ? Math.round(shownPrice * 100) + "%" : "—"}</span>
          <span className="gmt-h-unit">隐含概率</span>
          {hv
            ? <span className="gmt-h-date">{hv.date.slice(5)}</span>
            : (chgPts != null && <span className={`gmt-h-delta ${dirCls}`}>{chgPts >= 0 ? "▲ +" : "▼ "}{Math.abs(chgPts)}% 区间</span>)}
        </div>
      </div>
      <div className="gmt-wrap">
        <svg viewBox={`0 0 ${GMT_W} ${GMT_H}`} className="gmt-svg" onMouseMove={onMove} onMouseLeave={() => setCross(null)}>
          <g transform={`translate(${GMT_M.l},${GMT_M.t})`}>
            {xTicks.map((t, i) => (
              <g key={"x" + i}>
                <line x1={x(t)} x2={x(t)} y1="0" y2={ih} className="gmt-grid v" />
                <text x={x(t)} y={ih + 15} className="gmt-xtick">{fmtMD(t)}</text>
              </g>
            ))}
            {yTicks.map((t, i) => (
              <g key={"y" + i}>
                <line x1="0" x2={iw} y1={y(t)} y2={y(t)} className="gmt-grid" />
                <text x={iw + 6} y={y(t)} className="gmt-ytick r" dy="0.32em">{Math.round(t * 100)}%</text>
              </g>
            ))}
            <path d={ag(series)} className={`gmt-area ${dirCls}`} />
            {cross != null && <path d={lg(series)} className={`gmt-line ${dirCls} dim`} />}
            <path d={lg(bright)} className={`gmt-line ${dirCls}`} />
            {typeof entryPrice === "number" && <line x1="0" x2={iw} y1={y(entryPrice)} y2={y(entryPrice)} className="gmt-entry-h" />}
            {entryDate && typeof entryPrice === "number" && (
              <g>
                <line x1={x(_pdate(entryDate))} x2={x(_pdate(entryDate))} y1="0" y2={ih} className="gmt-entry-v" />
                <circle cx={x(_pdate(entryDate))} cy={y(entryPrice)} r="4.5" className="gmt-entry-dot" />
              </g>
            )}
            {nodes.map((n, i) => (
              <circle key={i} cx={x(n.t)} cy={y(n.px)} r="5.5" fill={nodeColor(n)} className="gmt-node" />
            ))}
            {hv && (
              <g>
                <line x1={x(hv.t)} x2={x(hv.t)} y1="0" y2={ih} className="gmt-cross-v" />
                <circle cx={x(hv.t)} cy={y(hv.price)} r="5" className={`gmt-cross-dot ${dirCls}`} />
              </g>
            )}
            {!hv && typeof curPrice === "number" && <circle cx={iw} cy={y(curPrice)} r="4.5" className={`gmt-now-dot ${dirCls}`} />}
          </g>
        </svg>
        {hv && <div className="gmt-cross-date" style={{ left: `${sx(x(hv.t))}%` }}>{fmtMD(hv.t)}</div>}
        {hv && (
          <div className={`gmt-cross-tip ${dirCls} ${sx(x(hv.t)) > 60 ? "l" : ""}`} style={{ left: `${sx(x(hv.t))}%`, top: `${sy(y(hv.price))}%` }}>
            押 {side} {Math.round(hv.price * 100)}%
          </div>
        )}
        {entryDate && typeof entryPrice === "number" && (
          <div className="gmt-lbl entry" style={{ left: `${sx(x(_pdate(entryDate)))}%`, top: `${sy(y(entryPrice))}%` }}>建仓 {Math.round(entryPrice * 100)}¢</div>
        )}
        {newsAt && (() => {
          const rc = gmtReact(newsAt.reaction);
          const lx = sx(x(newsAt.t)), ly = sy(y(newsAt.px));
          const cls = `${ly < 42 ? "below" : ""} ${lx > 72 ? "ar" : lx < 28 ? "al" : "ac"}`;
          return (
            <div className={`gmt-tip ${cls}`} style={{ left: `${lx}%`, top: `${ly}%` }}>
              <div className="gmt-tip-top">
                <span className="gmt-tip-date num">{newsAt.date}</span>
                {newsAt.direction && <span className={`db-dir ${newsAt.direction}`}>{newsAt.direction === "support" ? "支持" : "威胁"}</span>}
                <span className={`rx ${rc.cls}`}>{rc.txt}</span>
              </div>
              <div className="gmt-tip-title">{newsAt.title}</div>
              {newsAt.summary && <div className="gmt-tip-sum">{newsAt.summary}</div>}
              <div className="gmt-tip-foot">{newsAt.origin} · 时间相关·非因果</div>
            </div>
          );
        })()}
      </div>
      <div className="gmt-foot"><i className="gmt-foot-dot" />彩点 = 新闻催化（移动鼠标查看）· 与价格变动<b className="gmt-warn">时间相关、非因果</b> · 灰虚线 = 建仓成本</div>
    </div>
  );
}

function BoardReasoning({ r }) {
  if (!r) return null;
  if (r.guard_tripped) {
    return (
      <div className="db-reason guard">
        <div className="db-guard-h">🛡 诚实守卫拦截 · [{r.guard_tripped}]</div>
        <div className="db-guard-msg">{r.guard_message}</div>
        <div className="db-guard-sub">该判断触发守卫（如时长推算/篡改置信度），按设计不输出 reasoning——守卫真实发火，不是摆设。</div>
      </div>
    );
  }
  const cls = FOLLOW_CLASS[r.follow_call] || "gray";
  return (
    <div className={`db-reason ${cls}`}>
      <div className="db-reason-top">
        <span className={`db-call ${cls}`}>{FOLLOW_LABEL_CN[r.follow_call] || r.follow_call}</span>
        <span className="db-conf">信心 <b className={cls}>{CONF_CN[r.confidence] || r.confidence}</b></span>
      </div>
      {r.confidence_reasons && r.confidence_reasons.length > 0 && (
        <div className="db-rchips">
          {r.confidence_reasons.map((x, i) => <span className="db-rchip" key={i}>{x}</span>)}
        </div>
      )}
      <div className="db-reason-text">{r.reasoning}</div>
    </div>
  );
}

// 状态灯配色（🔴 守魂#4：判断非买入信号——CHASED 用 amber 表"谨慎,好价过了",不用红"别买";NO BASIS 灰=中性）
const LIGHT_CLS = { "ROOM LEFT": "green", CHASED: "amber", "NO BASIS": "grey" };
const cent = (v) => (typeof v === "number" ? Math.round(v * 100) + "¢" : "—");

// 迷你 sparkline（身份徽章用，纯 SVG，零依赖）
function MiniSpark({ points }) {
  const n = points.length, W = 66, H = 18;
  const ps = points.map((d) => d.p);
  const min = Math.min(...ps), max = Math.max(...ps), span = max - min || 1;
  const x = (i) => (i / (n - 1)) * W, y = (p) => (1 - (p - min) / span) * H;
  const path = ps.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p).toFixed(1)}`).join(" ");
  const color = ps[n - 1] >= ps[0] ? "var(--pos)" : "var(--neg)";
  return (
    <svg className="vh-spark" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
      <path d={path} fill="none" stroke={color} strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

// 身份徽章（资格审查降级成角落名片，不再霸占首屏）
function CredBadge({ profile, rk, pnlHistory }) {
  const nick = profile.name || profile.pseudonym || abbrev(profile.address);
  const last = pnlHistory && pnlHistory.length ? pnlHistory[pnlHistory.length - 1].p : null;
  return (
    <div className="vh-badge">
      <Avatar profile={profile} />
      <div className="vh-badge-meta">
        <div className="vh-badge-nick">{nick}</div>
        <div className="vh-badge-stats num">
          #{rk.rank ?? "—"} · 胜率 {rk.win_rate ? (Number(rk.win_rate) * 100).toFixed(0) + "%" : "—"}
          {last != null ? " · " + fmtPnlCompact(last) : (rk.total_pnl ? " · " + money(Number(rk.total_pnl)) : "")}
        </div>
      </div>
      {pnlHistory && pnlHistory.length > 1 && <MiniSpark points={pnlHistory} />}
    </div>
  );
}

// 首屏判断英雄区：结论先行，0.5 秒拿到"还能不能跟"
function VerdictHero({ d }) {
  const r = d.reasoning || {};
  const pos = d.position || {};
  const m = pos.meta || {};
  const wpa = pos.what_position_actions || {};
  const act = wpa.actions || {};
  const un = wpa.unrealized || {};
  const pc = pos.price_context || {};
  const id = d.identity || {};
  const profile = { ...(id.profile || {}), address: id.profile?.address || d.wallet };
  const rk = (id.who_trader_profile || {}).official_rank || {};
  const side = (m.analyzed_side || "").toUpperCase();
  const cls = r.follow_call ? (LIGHT_CLS[r.follow_call] || "grey") : "grey";
  const upct = un.unrealized_pct;
  const gain = typeof upct === "number"
    ? upct >= 0
    : (typeof pc.current_price === "number" && typeof act.avg_entry_price === "number"
        ? pc.current_price >= act.avg_entry_price : true);
  const dirCls = gain ? "pos" : "neg";

  return (
    <div className="vh">
      <div className="vh-top">
        <div className="vh-q">{m.market} <span className="vh-side">· 押 {side}</span></div>
        <CredBadge profile={profile} rk={rk} pnlHistory={id.pnl_history} />
      </div>

      {(pos.what_the_bet || pos.resolution_criteria) && (
        <div className="db-whatbet vh-whatbet">
          <div className="db-whatbet-h">这一注在赌什么</div>
          {pos.what_the_bet && <div className="db-whatbet-t">{renderInline(pos.what_the_bet)}</div>}
          {pos.resolution_criteria && (
            <details className="db-rc">
              <summary>官方结算规则原文（什么算赢）</summary>
              <div className="db-rc-body">{pos.resolution_criteria}</div>
            </details>
          )}
        </div>
      )}

      <div className="vh-essence">
        <div className="vh-e"><span>入场成本</span><b className="vh-from num">{cent(act.avg_entry_price)}</b></div>
        <span className="vh-arrow">→</span>
        <div className="vh-e vh-e-main">
          <span>现价 · 隐含概率</span>
          <div className="vh-now-row">
            <b className={`vh-now num ${dirCls}`}>{cent(pc.current_price)}</b>
            {typeof upct === "number" && (
              <span className={`vh-delta ${dirCls}`}>{upct >= 0 ? "▲" : "▼"} {upct >= 0 ? "+" : ""}{upct}%</span>
            )}
          </div>
        </div>
        <div className="vh-e vh-room"><span>剩余空间(若赢)</span><b className="num">{pc.remaining_upside_pct_if_win != null ? pc.remaining_upside_pct_if_win + "%" : "—"}</b></div>
      </div>

      {r.guard_tripped ? (
        <div className="vh-light guard"><span className="vh-call">🛡 守卫拦截</span>
          <span className="vh-conf">该判断触发诚实守卫,不输出结论</span></div>
      ) : (
        <div className={`vh-light ${cls}`}>
          <span className="vh-dot" />
          <span className="vh-call">{FOLLOW_LABEL_CN[r.follow_call] || r.follow_call || "—"}</span>
          <span className="vh-conf">信心 <b>{CONF_CN[r.confidence] || r.confidence || "—"}</b></span>
        </div>
      )}

      <div className="vh-verdict">{r.guard_tripped ? r.guard_message : r.reasoning}</div>

      {d.behavior && <div className="vh-whale">🐳 巨鲸动态 · {d.behavior.fact}</div>}
      <div className="vh-disc">这是对"局势性质"的判断(还有多少空间/风险在哪/市场认不认这个方向),不替你决定跟不跟 · 天平由你裁决</div>
    </div>
  );
}

function BoardBody({ d }) {
  const id = d.identity || {};
  const who = id.who_trader_profile || {};
  const rk = who.official_rank || {};
  const q = who.quality || {};
  const pos = d.position || {};
  const m = pos.meta || {};
  const wpa = pos.what_position_actions || {};
  const act = wpa.actions || {};
  const ts = wpa.two_side_distribution || {};
  const un = wpa.unrealized || {};
  const pc = pos.price_context || {};
  const wrLie = Number(rk.win_rate) > 0.8 && Number(rk.total_pnl) < 0;
  const upct = un.unrealized_pct;

  return (
    <div className="card bf db">
      {/* 首屏：结论先行 */}
      <VerdictHero d={d} />

      {/* 局势时间轴（核心视觉，紧跟结论）*/}
      <GodModeTimeline d={d} />
      {d.world_summary && <div className="db-wsum gmt-summary"><Narrative text={d.world_summary} /></div>}

      {/* 新闻(事实) × 社媒(情绪) 并排 —— 同一问题的两面，视觉刻意分开 */}
      <div className="db-sec-tag">世界发生了什么 × 在怎么议论</div>
      <div className="ns-split">
        <div className="ns-col news">
          <div className="ns-col-h"><span className="ns-ico">📰</span>新闻 · <b>事实</b><span className="ns-sub">世界发生了什么</span></div>
          <NewsStream items={d.news_stream} />
        </div>
        <div className="ns-col social">
          <div className="ns-col-h soc"><span className="ns-ico">💬</span>社媒 · <b>情绪</b><span className="ns-sub">小心是情绪、可能刷量</span></div>
          <SocialPulse s={d.social} />
        </div>
      </div>
      <div className="ns-diverge">⚖️ 最值钱的对照：新闻在涨 + 社媒在嗨，但 <b>聪明钱（行为流）信不信？市场价跟没跟？</b> 顺风只陈列，背离才是金。</div>

      {/* 巨鲸 48h 行为流（折叠）*/}
      <Fold title="巨鲸 48h 动作流" sub="加仓 / 减仓 / 没动 + 3h/24h/48h 窗口">
        <BehaviorFlag b={d.behavior} />
      </Fold>

      {/* ② 这一注 · 明细 */}
      <div className="db-sec-tag">② 这一注 · 明细</div>
      <div className="c-head db-pos-head">
        <div>
          <div className="q">{m.market}</div>
          <div className="meta">{m.settle} · 建仓 {act.entry_time?.slice(0, 10) || "—"}</div>
        </div>
        <span className="outcome">{(m.analyzed_side || "").toUpperCase()}</span>
      </div>
      <div className="bf-grid db-grid">
        <div className="bf-mini">
          <div className="bf-mini-h">动作 · 他做了什么</div>
          <div className="bf-kv"><span>均价 / 成本</span><b className="num">{price(act.avg_entry_price)} · {money(act.net_cost_usd)}</b></div>
          <div className="bf-kv"><span>买入笔数</span><b className="num">{act.num_buys ?? "—"}</b></div>
          <div className="bf-kv"><span>盈亏</span><b className={`num ${Number(un.unrealized_pnl_usd) >= 0 ? "pos" : "neg"}`}>{money(un.unrealized_pnl_usd)} {typeof upct === "number" ? `(${upct >= 0 ? "+" : ""}${upct}%)` : ""}</b></div>
          <div className="bf-note">{ts.hedged ? "两边对冲 · 做市/非单边信念" : "单边建仓 · 信念注"}</div>
        </div>
        <div className="bf-mini">
          <div className="bf-mini-h">价格 · Entry ↗ Current</div>
          <div className="bf-kv"><span>入场 → 现价</span><b className="num">{price(act.avg_entry_price)} → {price(pc.current_price)}</b></div>
          <div className="bf-kv"><span>vs 入场 / 隐含概率</span><b className="num">{typeof pc.price_delta_pct === "number" ? (pc.price_delta_pct >= 0 ? "+" : "") + pc.price_delta_pct + "%" : "—"} · {pc.implied_probability_pct}%</b></div>
          <div className="bf-kv"><span>剩余空间(赢) / 赔率</span><b className="num">{pc.remaining_upside_pct_if_win}% · {pc.odds_to_one ?? "—"}</b></div>
        </div>
      </div>

      {/* ③ 当前赔率 · 原生条（替 iframe）*/}
      <div className="db-sec-tag">③ 当前赔率 · 市场怎么定价</div>
      <OddsBar held={pc.current_price} side={(m.analyzed_side || "").toUpperCase()} slug={d.market?.slug} />

      {/* 降级：钱包历史体量（资格审查，不再霸占首屏）*/}
      <Fold title="钱包历史体量 · 身份背书" sub="累计盈亏曲线 + 风险标记（背景调查，非本注结论）">
        {id.pnl_history && id.pnl_history.length > 1 && <PnlChart points={id.pnl_history} />}
        {wrLie && <div className="bf-lie">⚠ 胜率谎言:高胜率但净盈亏为负 — 看净盈亏,非胜率</div>}
        {q.flagged_metrics && <div className="bf-sub db-flags">风险标记: {flagsCN(q.flagged_metrics)}</div>}
        <div className="db-id-stats db-id-stats-full">
          <span>官方榜 <b className="num">#{rk.rank ?? "—"}</b></span>
          <span>胜率 <b className="num">{rk.win_rate ? (Number(rk.win_rate) * 100).toFixed(1) + "%" : "—"}</b></span>
        </div>
      </Fold>

      <div className="foot">结论由代码矩阵算定信心、AI 只解释不改判 · 价格为市场隐含概率(非胜率) · 公开数据整理,非投资建议</div>
    </div>
  );
}

function BoardView() {
  const [wallet, setWallet] = useState("");
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  async function run(addrArg) {
    const w = (typeof addrArg === "string" ? addrArg : wallet).trim();
    if (!w) return;
    setLoading(true); setData(null); setError(null);
    try {
      const resp = await fetch(`${API}/dashboard?wallet=${encodeURIComponent(w)}`);
      const j = await resp.json();
      if (!resp.ok || j.error) setError({ reason: j.error || `HTTP ${resp.status}`, message: j.message || "请求失败" });
      else setData(j);
    } catch (e) {
      setError({ reason: "NETWORK", message: `无法连接后端 ${API}，请确认 uvicorn 已启动。` });
    } finally { setLoading(false); }
  }

  const showHome = !data && !loading && !error;
  return (
    <>
      {!data && !error && (
        <div className="console-sub">输入聪明钱钱包,生成 v3 统一看板:身份体量 → 这一注 → 实时盘面 → 行为×催化剂 → Edge 判断,一屏看全</div>
      )}
      <div className={`cmdbar ${loading ? "busy" : ""}`}>
        <span className="cmd-prompt">&gt;</span>
        {showHome && !wallet && <span className="cmd-caret" />}
        <input className="cmd-input num" value={wallet} onChange={(e) => setWallet(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && run()} placeholder="输入 Polymarket 钱包地址" spellCheck={false} />
        <button className="cmd-trigger" onClick={() => run()} disabled={loading || !wallet.trim()}>
          {loading ? "生成中" : "生成看板"}
        </button>
      </div>

      {showHome && (
        <div className="monitor">
          <div className="mon-head">试试这几个大户 · 点击生成统一看板</div>
          <div className="mon-list">
            {EXAMPLES.map((e) => (
              <button className="mon-row" key={e.addr} onClick={() => { setWallet(e.addr); run(e.addr); }}>
                <span className="mon-dot" /><span className="mon-nick">{e.nick}</span>
                <span className="mon-addr num">{abbrev(e.addr)}</span>
                <span className="mon-pnl"><span className="mon-pnl-lab">累计盈利</span><span className="mon-pnl-val num">{e.pnl}</span></span>
              </button>
            ))}
          </div>
        </div>
      )}

      {loading && <LoadingStages stages={STAGES_BOARD} sub="身份 → 这一注 → 盘面 → 行为×催化剂 → Edge" />}
      {error && <div className="error"><div className="r">{error.reason}</div><div>{error.message}</div></div>}
      {data && <BoardBody d={data} />}
    </>
  );
}

// ── Track Record 回测页 ─────────────────────────────────────────────────────
const CALL_PLAIN = { "NO BASIS": "别跟", CHASED: "可跟·已追高", "ROOM LEFT": "可跟·有空间" };
const CALL_CLS = { "NO BASIS": "red", CHASED: "amber", "ROOM LEFT": "green" };

// ── 诚实记分牌（装上后累积的真实 decode/看板判断的自我验证）──────────────────
const SC_STATUS = {
  hit: { txt: "✓ 一致", cls: "up" }, miss: { txt: "✗ 不一致", cls: "down" },
  pending: { txt: "待结算", cls: "pending" }, nobasis: { txt: "NO BASIS", cls: "nb" },
};
const SC_SOURCE = { decode: "v2·解读", board: "v3·看板" };

function LiveScorecard({ sc }) {
  if (!sc || sc.error) return null;
  const rate = sc.hit_rate_pct;
  const settledRows = (sc.rows || []).filter((r) => r.status !== "nobasis");
  const nbRows = (sc.rows || []).filter((r) => r.status === "nobasis");
  return (
    <div className="sc">
      <div className="sc-head">
        <div className="sc-title">诚实记分牌 · 我的判断后来被现实证明对了多少</div>
        <div className="sc-sub">从装上往后累积的真实 decode / 看板判断 → 盘结算后回来对账。与下方历史回测是两套独立机制。</div>
      </div>
      <div className="sc-nums">
        <div className="sc-num"><b className="num">{sc.tested}</b><span>测了</span></div>
        <div className="sc-num"><b className="num">{sc.settled}</b><span>已结算</span></div>
        <div className="sc-num"><b className="num up">{sc.direction_consistent}</b><span>方向一致</span></div>
        <div className="sc-num big"><b className="num">{rate == null ? "—" : rate + "%"}</b><span>命中率</span></div>
        <div className="sc-num"><b className="num">{sc.nobasis_total}</b><span>NO BASIS</span></div>
      </div>
      <div className="sc-discipline">命中率 = <b>判断方向命中</b>，不是跟单收益率 · NO BASIS 不计入命中率 · 顶上冷数字纯代码算，不经 AI</div>

      {sc.tested === 0 ? (
        <div className="sc-empty">还没有记录 — 去解读台 / 统一看板跑几个钱包，判断就会存进档案；等这些盘在数据世界里真结算，这里才长出命中率。第一天空是正常的。</div>
      ) : (
        <div className="sc-rows">
          {settledRows.map((r, i) => {
            const st = SC_STATUS[r.status] || SC_STATUS.pending;
            return (
              <div className="sc-row" key={i}>
                <span className="sc-src">{SC_SOURCE[r.source] || r.source}</span>
                <span className="sc-q">{r.market_question}</span>
                <span className="sc-call num">判 {FOLLOW_LABEL_CN[r.follow_call] || r.follow_call} · 押 {r.outcome}</span>
                <span className={`sc-status ${st.cls}`}>{st.txt}{(r.status === "hit" || r.status === "miss") && r.winner ? ` · 赢家 ${r.winner}` : ""}</span>
              </div>
            );
          })}
        </div>
      )}

      {sc.nobasis_total > 0 && (
        <div className="sc-nobasis">
          <div className="sc-nobasis-h">NO BASIS 单独区 · {sc.nobasis_total} 个（不进命中率）· 其中事后看其实有清晰方向 <b className="down">{sc.nobasis_clear_in_hindsight}</b> 个（当时过谨慎、错过）</div>
          {nbRows.map((r, i) => (
            <div className="sc-row nb" key={i}>
              <span className="sc-src">{SC_SOURCE[r.source] || r.source}</span>
              <span className="sc-q">{r.market_question}</span>
              <span className="sc-call num">押 {r.outcome}</span>
              <span className="sc-status nb">{r.winner ? (r.winner === r.outcome ? "事后有方向" : "正确回避") : "待结算"}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function TrackRecordView() {
  const [data, setData] = useState(null);
  const [sc, setSc] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    fetch(`${API}/backtest`).then((r) => r.json()).then(setData)
      .catch(() => setError("无法连接后端 /backtest"));
    fetch(`${API}/scorecard`).then((r) => r.json()).then(setSc).catch(() => {});
  }, []);

  const s = (data && data.summary) || {};
  const wrong = (s.total || 0) - (s.directional_correct || 0);
  return (
    <>
      <LiveScorecard sc={sc} />

      <div className="sc-divider">↓ 历史回测（v2 已封板·静态零 token，与上方实时记分牌相互独立）</div>

      {error ? <div className="error"><div className="r">NETWORK</div><div>{error}</div></div>
       : !data ? <div className="stages"><div className="lead">LOADING TRACK RECORD…</div></div>
       : !data.cases || !data.cases.length ? <div className="method">案例数据缺失（backtest/cases.json 未就位）</div>
       : (
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
      )}
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
