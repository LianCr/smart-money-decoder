import { useState, useEffect, useRef } from "react";
import { scaleLinear, scaleTime } from "d3-scale";
import { line as d3line, area as d3area, curveMonotoneX } from "d3-shape";
import { extent } from "d3-array";
import { useLang, LangToggle, ZhNote } from "./i18n.jsx";

// 生产构建走同源（后端托管 dist），本地开发默认打 localhost:8000
const API = import.meta.env.VITE_API_BASE ?? (import.meta.env.DEV ? "http://localhost:8000" : "");

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
  const { t } = useLang();
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
        <span className="pc-lab">{t("CUMULATIVE PnL · 该钱包历史累计盈亏")}</span>
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
  const [tab, setTab] = useState("board");   // 主页=统一看板(推荐流落地处)；Decode 降为存档，仍可经品牌 logo / 统一看板切换键到达
  // 功勋章的 W/L 取回测真值；默认 5/1（当前案例集事实），/backtest 到达后自校正、不闪
  const [wl, setWl] = useState({ w: 5, l: 1 });
  useEffect(() => {
    fetch(`${API}/backtest`).then((r) => r.json()).then((d) => {
      const s = d.summary || {};
      if (typeof s.directional_correct === "number" && typeof s.total === "number")
        setWl({ w: s.directional_correct, l: s.total - s.directional_correct });
    }).catch(() => {});
  }, []);

  const { t } = useLang();
  return (
    <div className="shell">
      <div className="topbar">
        <div className="brand" onClick={() => setTab("decode")} title={t("回到解读台")}>
          <span className="dot" />SMART MONEY DECODER
        </div>
        <div className="topnav">
          <button
            className={`navbtn primary ${tab === "board" ? "active" : ""}`}
            onClick={() => setTab(tab === "board" ? "decode" : "board")}
            title={t("v3 统一看板：身份+这一注+实时盘面+行为×催化剂+Edge 一屏看全")}
          >
            ★ {t("统一看板")}<span className="navbtn-tag">v3</span>
          </button>
          <button
            className={`navbtn ${tab === "briefing" ? "active" : ""}`}
            onClick={() => setTab(tab === "briefing" ? "decode" : "briefing")}
            title={t("完整聪明钱简报（v3）")}
          >
            {t("完整简报")}<span className="navbtn-tag">v3</span>
          </button>
          <button
            className={`navbtn ${tab === "context" ? "active" : ""}`}
            onClick={() => setTab(tab === "context" ? "decode" : "context")}
            title={t("市场 Context：实时盘面 × as-of 复盘（价格异动 + 催化剂 + 巨鲸动作）")}
          >
            {t("市场Context")}<span className="navbtn-tag">v3</span>
          </button>
          <button
            className={`medal ${tab === "track" ? "active" : ""}`}
            onClick={() => setTab(tab === "track" ? "decode" : "track")}
            title={tab === "track" ? t("返回解读台") : t("查看历史战绩")}
          >
            [ TRACK RECORD:&nbsp;<span className="m-w">{wl.w}W</span> · <span className="m-l">{wl.l}L</span>&nbsp;]
            <span className="m-arrow">↗</span>
          </button>
          <LangToggle />
        </div>
      </div>
      {tab === "decode" ? <DecodeView /> : tab === "board" ? <BoardView />
        : tab === "briefing" ? <BriefingView />
        : tab === "context" ? <ContextView /> : <TrackRecordView />}
    </div>
  );
}

function DecodeView() {
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

// 常见后端错误 reason → EN 文案（后端 message 是中文；zh 模式直接用后端原文，en 模式查这里、查不到回退原文）
const REASON_EN = {
  INVALID_ADDRESS: "Invalid wallet address — expected a 0x… address (42 chars).",
  NO_POSITIONS: "This wallet has no open positions.",
  NO_OPEN_POSITIONS: "This wallet has no open positions.",
  NO_POLITICAL_POSITIONS: "This wallet has no political-market positions — we only analyze politics markets.",
  ALL_BELOW_MIN_VALUE: "All positions are below the minimum size threshold — too small to analyze meaningfully.",
  DASHBOARD_PIPELINE_FAILED: "The analysis pipeline failed upstream (data source or AI gateway). Please retry later.",
  BRIEFING_PIPELINE_FAILED: "The briefing pipeline failed upstream (data source or AI gateway). Please retry later.",
  MARKET_CONTEXT_FAILED: "Market-context synthesis failed upstream. Please retry later.",
  RATE_LIMITED: "Upstream API rate limit hit — please wait a moment and retry.",
  NETWORK: "Cannot reach the backend — please retry later.",
};

function ErrorBox({ error }) {
  const { lang } = useLang();
  if (!error) return null;
  const msg = lang === "en" ? (REASON_EN[error.reason] || error.message) : error.message;
  return (
    <div className="error">
      <div className="r">{error.reason}</div>
      <div>{msg}</div>
    </div>
  );
}

// 流水线加载：单请求在飞，前端按节奏 currentStep 逐个点亮，居中、与首页同语言。
// 渐进式逻辑：i<step=已完成(暗青·✓静止) / i===step=进行中(亮青·脉冲) / i>step=未开始(暗灰静止)。
function LoadingStages({ stages = STAGES, sub = "定位 → 追溯 → 检索 → 判断", note }) {
  const { t } = useLang();
  const [step, setStep] = useState(0);
  const [secs, setSecs] = useState(0);          // 真实已用时长（诚实计时，不装进度）
  const timer = useRef();
  useEffect(() => {
    const t0 = Date.now();
    timer.current = setInterval(() => {
      setSecs(Math.floor((Date.now() - t0) / 1000));
      setStep((s) => {
        const target = Math.min(Math.floor((Date.now() - t0) / 3500), stages.length - 1);
        return Math.max(s, target);              // 卡在最后一步，绝不全打勾
      });
    }, 1000);
    return () => clearInterval(timer.current);
  }, [stages.length]);
  const last = stages.length - 1;

  return (
    <div className="pipe">
      <div className="pipe-lead">
        {t("AI 推演中")} <span className="pipe-sub">· {t(sub)}</span>
        <span className="pipe-timer num">{secs}s</span>
      </div>
      {note && secs >= 3 && <div className="pipe-note">{note}</div>}
      <div className="pipe-list">
        <span className="pipe-rail" />
        <span className="pipe-fill" style={{ height: `calc((100% - 28px) * ${step} / ${last})` }} />
        {stages.map((s, i) => {
          const state = i < step ? "done" : i === step ? "active" : "todo";
          return (
            <div className={`pstep ${state}`} key={i}>
              <span className="pstep-node" />
              <span className="pstep-label">{t(s)}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// 可复用解读卡：实时解读与回测快照共用。banner 存在时顶部加时间戳横幅
export function Card({ card, banner }) {
  const { t } = useLang();
  const pi = card.price_info || {};
  const followCls = FOLLOW_CLASS[card.follow_call] || "gray";
  const cash = pi.cash_pnl;
  const gain = typeof cash === "number" ? cash >= 0 : null;
  const dir = gain === null ? "" : gain ? "up" : "down";
  const resDate = card.resolution_date ? card.resolution_date.slice(0, 10) : t("未知");
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
            {t("结算")} {resDate} · {card.time_anchored ? t("新闻锚定建仓窗") : t("新闻近30天兜底")}
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
        <h4>What the bet is <ZhNote text={card.what_bet} /></h4>
        <p>{t(card.what_bet)}</p>
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
                <div className="why">{t(c.why_relevant)}</div>
              </div>
            );
          })
        ) : (
          <div className="empty-cat">{t("无可归因催化剂新闻 · 如实留空，未编造")}</div>
        )}
      </div>

      <div className="sec dim">
        <h4>Edge / Reasoning <ZhNote text={`${card.edge_analysis || ""}${card.reasoning || ""}`} /></h4>
        <p>{t(card.edge_analysis)}</p>
        <p>{t(card.reasoning)}</p>
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

      <div className="foot">{t("仅为公开数据 AI 解读，非投资建议")}</div>
    </div>
  );
}

// ── Briefing 完整简报页（v3）─────────────────────────────────────────────────
// 材质分层：硬材质(当事人直接表态/已生效硬事件)=亮+左tick / 其余软材质=暗。靠灰阶不靠颜色。
const HARD_MATERIALS = new Set(["当事人直接表态", "已生效硬事件"]);

// 原生赔率条（替代 Polymarket iframe）：Yes/No 比例条，高亮钱包押的那一侧
function OddsBar({ held, side, slug }) {
  const { t } = useLang();
  if (typeof held !== "number") return <div className="ctx-empty">{t("无价,赔率不可显")}</div>;
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
        <span>{t("他押")} <b className={yesHeld ? "ob-yes" : "ob-no"}>{S}</b> {t("· 高亮侧")}</span>
        {slug && <a className="ob-jump" href={`https://polymarket.com/market/${slug}`} target="_blank" rel="noreferrer">{t("在 Polymarket 打开 ↗")}</a>}
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
function flagsCN(raw, t = (s) => s) {
  return String(raw || "").replace(/[{}]/g, "").split(",").map((s) => s.trim())
    .filter(Boolean).map((k) => t(FLAG_CN[k] || k.replace(/_/g, " "))).join("、");
}

// 市场反应 chip：印证=暗绿、不一致(测谎)=暗陶红+⚠、微弱/不可知=灰。t=当前语言翻译函数（渲染点传入）
function reactionChip(pr, t = (s) => s) {
  if (!pr || !pr.available) return { txt: t("市场反应不可知"), cls: "rx-na" };
  const mc = pr.market_check || "";
  const arrow = pr.move_pct >= 0 ? "↑" : "↓";
  const base = `${arrow}${Math.abs(pr.move_pct)}%`;
  if (mc.includes("不一致")) return { txt: `⚠ ${base} ${t("市场不买账")}`, cls: "rx-bad" };
  if (mc.includes("印证")) return { txt: `${base} ${t("市场印证")}`, cls: "rx-good" };
  return { txt: `${base} ${t("反应微弱")}`, cls: "rx-weak" };
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
  const { t } = useLang();
  return (
    <div className={`bf-col ${side}`}>
      <div className="bf-col-h">{t(title)} <span className="bf-col-n">{items.length}</span><span className="bf-pulse pulse-dot" /></div>
      {items.length === 0 && <div className="bf-empty">{t("如实留空")}</div>}
      {items.map((c, i) => {
        const rx = reactionChip(c.price_reaction, t);
        return (
          <div className="bf-cat" key={i}>
            <div className="bf-cat-top">
              <span className={`mat ${HARD_MATERIALS.has(c.type) ? "hard" : "soft"}`}>{t(c.type)}</span>
              <span className="bf-cat-date num">{c.date}</span>
            </div>
            {c.url ? <a className="bf-cat-t" href={c.url} target="_blank" rel="noreferrer">{c.title}</a>
                   : <div className="bf-cat-t">{c.title}</div>}
            <div className="bf-cat-why">{t(c.reason)}</div>
            <span className={`rx ${rx.cls}`}>{rx.txt}</span>
            {c.price_reaction && c.price_reaction.same_window && (
              <div className="bf-samewin">{t("同窗合计 · 不可归因到单条")}</div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function BriefingBody({ d }) {
  const { t } = useLang();
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
          <div className="meta">{t(m.settle)} · {t("催化剂锚")} {m.catalyst_anchor === "entry_time" ? t("建仓时(复盘)") : t("现在(实战)")}</div>
        </div>
        <span className="outcome">{(m.analyzed_side || "").toUpperCase()}</span>
      </div>

      {/* WHO / WHAT / PRICE 三联卡 */}
      <div className="bf-grid">
        <div className="bf-mini">
          <div className="bf-mini-h">{t("WHO · 这人靠不靠谱")}</div>
          <div className="bf-kv"><span>{t("官方排名")}</span><b className="num">#{rk.rank ?? "—"}</b></div>
          <div className="bf-kv"><span>{t("胜率 / 累计盈亏")}</span><b className="num">{rk.win_rate ? (rk.win_rate * 100).toFixed(1) + "%" : "—"} · {rk.total_pnl ? money(Number(rk.total_pnl)) : "—"}</b></div>
          {pol && <div className="bf-kv"><span>{t("政治盘专长")}</span><b className="num">{(pol.win_rate * 100).toFixed(0)}% · {money(Number(pol.total_pnl))}</b></div>}
          {wrLie && <div className="bf-lie">{t("⚠ 胜率谎言:高胜率但净盈亏为负 — 看净盈亏,非胜率")}</div>}
          {q.flagged_metrics && <div className="bf-sub">{t("风险标记: ")}{flagsCN(q.flagged_metrics, t)}</div>}
        </div>

        <div className="bf-mini">
          <div className="bf-mini-h">{t("WHAT · 他做了什么")}</div>
          <div className="bf-kv"><span>{t("建仓 / 均价")}</span><b className="num">{act.entry_time?.slice(0, 10) || "—"} · {price(act.avg_entry_price)}</b></div>
          <div className="bf-kv"><span>{t("买入 / 成本")}</span><b className="num">{act.num_buys ?? "—"}{t("笔")} · {money(act.net_cost_usd)}</b></div>
          <div className="bf-kv"><span>{t("盈亏")}</span><b className={`num ${Number(un.unrealized_pnl_usd) >= 0 ? "pos" : "neg"}`}>{money(un.unrealized_pnl_usd)} {typeof upct === "number" ? `(${upct >= 0 ? "+" : ""}${upct}%)` : ""}</b></div>
          <div className="bf-note">{ts.hedged ? t("两边对冲 · 做市/非单边信念") : t("单边建仓 · 信念注")}</div>
        </div>

        <div className="bf-mini">
          <div className="bf-mini-h">{t("PRICE · 还有没有空间")}</div>
          <div className="bf-kv"><span>{t("现价 / 隐含概率")}</span><b className="num">{price(pc.current_price)} · {pc.implied_probability_pct}%</b></div>
          <div className="bf-kv"><span>{t("剩余空间(赢)")}</span><b className="num">{pc.remaining_upside_pct_if_win}%</b></div>
          <div className="bf-kv"><span>{t("赔率 / vs入场")}</span><b className="num">{pc.odds_to_one ?? "—"} · {typeof pc.price_delta_pct === "number" ? (pc.price_delta_pct >= 0 ? "+" : "") + pc.price_delta_pct + "%" : "—"}</b></div>
        </div>
      </div>

      {/* 双向催化剂 + 市场测谎 */}
      <div className="bf-dialectic">
        <CatColumn title="支持 · 正向证据" side="pos" items={cats.positive || []} />
        <CatColumn title="威胁 · 负向证据" side="neg" items={cats.negative || []} />
      </div>

      {/* 第三个 AI 诚实整理（产品魂） */}
      <div className="bf-narr-wrap">
        <h4>{t("AI 诚实整理 · 只陈列证据,不替你判断")} <ZhNote text={d.organized_text} /></h4>
        <Narrative text={t(d.organized_text)} />
      </div>

      <div className="foot">{t("仅为公开数据 AI 整理,非投资建议")}</div>
    </div>
  );
}

function BriefingView() {
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
  const { t } = useLang();
  if (!b) return null;
  const meta = FLAG_META[b.flag] || FLAG_META.STATIC;
  const w = b.windows || {};
  return (
    <div className={`ctx-flag ${meta.cls}`}>
      <div className="ctx-flag-h">
        <span className="ctx-flag-ico">{meta.icon}</span>{t(meta.label)}
        <span className="ctx-flag-src">{t("巨鲸 48h 动作流 · 556 Trades")}</span>
      </div>
      <div className="ctx-flag-fact">{t(b.fact)}</div>
      <div className="ctx-flag-win">
        {["3h", "24h", "48h"].map((k) => {
          const x = w[k] || {};
          return (
            <div className="ctx-win" key={k}>
              <span className="ctx-win-k num">{k}</span>
              <span className="ctx-win-b num">{t("买")} {x.buys || 0} · {fmtUsd(x.buy_usd)}</span>
              <span className="ctx-win-s num">{t("卖")} {x.sells || 0} · {fmtUsd(x.sell_usd)}</span>
            </div>
          );
        })}
      </div>
      {b.honest_note && <div className="ctx-flag-note">{t(b.honest_note)}</div>}
    </div>
  );
}

function Timeline({ events }) {
  const { t } = useLang();
  if (!events || !events.length)
    return <div className="ctx-empty">{t("该 as-of 窗内无可锚定的价格异动 / 催化剂 — 如实留空")}</div>;
  return (
    <div className="ctx-timeline">
      {events.map((e, i) => {
        const meta = EVT_META[e.type] || EVT_META.catalyst;
        return (
          <div className={`ctx-evt ${meta.cls}`} key={i}>
            <div className="ctx-evt-rail"><span className="ctx-evt-dot" /></div>
            <div className="ctx-evt-body">
              <div className="ctx-evt-top">
                <span className={`ctx-tag ${meta.cls}`}>{t(meta.tag)}</span>
                <span className="ctx-evt-date num">{e.timestamp}</span>
                {e.price_impact_string && <span className="ctx-impact num">{e.price_impact_string}</span>}
              </div>
              {e.title && <div className="ctx-evt-title">{t(e.title)}</div>}
              <div className="ctx-evt-fact">{t(e.fact_summary)}</div>
              <div className="ctx-evt-foot">
                {e.source && <span className="ctx-evt-src">{e.source}</span>}
                {e.temporal_note && <span className="ctx-evt-note">{t(e.temporal_note)}</span>}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ContextBody({ d }) {
  const { t } = useLang();
  const mc = d.market_context || {};
  const side = (mc.analyzed_side || "").toUpperCase();
  return (
    <div className="card bf ctx">
      <div className="c-head">
        <div>
          <div className="q">{mc.market_question}</div>
          <div className="meta">{t("市场 Context · 锁定 as-of")} {mc.as_of} · {t("钱包")} {abbrev(mc.wallet)}</div>
        </div>
        <span className="outcome">{side}</span>
      </div>

      <div className="ctx-split">
        {/* 实：实时盘面（Polymarket 直嵌） */}
        <div className="ctx-pane ctx-real">
          <div className="ctx-pane-h"><span className="ctx-live-dot" />{t("当前赔率 · 市场定价")}</div>
          <OddsBar held={mc.current_price} side={mc.analyzed_side} slug={mc.market_slug} />
          <div className="ctx-pane-foot">{t("市场当前对 Yes/No 的定价（高亮=钱包押的侧）· 与右侧 as-of 复盘相互独立")}</div>
        </div>

        {/* 虚：我们合成的 as-of 复盘 Context */}
        <div className="ctx-pane ctx-synth">
          <div className="ctx-pane-h">{t("复盘上下文 · 锁定 as-of")} {mc.as_of}{t("（防泄漏）")}</div>
          <BehaviorFlag b={mc.behavioral_flag} />
          {mc.ai_experimental_summary && (
            <div className="bf-narr-wrap ctx-summary">
              <h4>{t("宏观综述 · 只陈列事实,不替你判断")} <ZhNote text={mc.ai_experimental_summary} /></h4>
              <Narrative text={t(mc.ai_experimental_summary)} />
            </div>
          )}
          <div className="ctx-tl-h">{t("事件时间线 · 价格异动 × 催化剂 × 巨鲸动作")}</div>
          <Timeline events={mc.timeline_events} />
        </div>
      </div>

      <div className="foot">{t("价格异动窗 ≤ as-of(防泄漏) · 催化剂=GDELT 三层洗 · 因果→仅时间相关 · 巨鲸动作=事实非判断 · 仅公开数据 AI 整理,非投资建议")}</div>
    </div>
  );
}

function ContextView() {
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
const FOLLOW_LABEL_CN = { "ROOM LEFT": "还有空间", CHASED: "已追高", "NO BASIS": "没依据" };
const CONF_CN = { high: "高", medium: "中", med: "中", low: "低" };

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

// ⑤ 时间线新闻流 · 市场反应符号（统一口径:持有侧价格前后涨跌,非该新闻导致）
const REACT_SYM = {
  confirm: { sym: "↑", txt: "印证", cls: "rx-good" },
  reject:  { sym: "↓", txt: "不买账", cls: "rx-bad" },
  weak:    { sym: "·", txt: "微弱", cls: "rx-weak" },
};
function ReactionTag({ r }) {
  const { t } = useLang();
  if (!r || !r.available) return <span className="rx rx-na">{t("市场反应不可知")}</span>;
  const m = REACT_SYM[r.kind] || REACT_SYM.weak;
  const mv = `${r.move_pct > 0 ? "+" : ""}${r.move_pct}%`;
  return <span className={`rx ${m.cls}`}>{m.sym}{t(m.txt)} {mv}</span>;
}
// 方向标=dual_catalyst 已分好的正负（支持/威胁）；GDELT 未分类→不杜撰方向
const DIR_META = { support: { txt: "支持", cls: "support" }, threat: { txt: "威胁", cls: "threat" } };
function domainOf(url, fallback) {
  try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return fallback || ""; }
}
function faviconUrl(domain) { return `https://www.google.com/s2/favicons?domain=${domain}&sz=64`; }

// 新闻流 · Polymarket 风格（标题 + 段落 + 底部可点 mini 来源 logo + 市场反应）
function NewsStream({ items }) {
  const { t } = useLang();
  if (!items || !items.length)
    return <div className="bf-empty">{t("该时点窗内三源都没洗出对题新闻 — 如实留空")}</div>;
  return (
    <div className="db-stream">
      {items.map((it, i) => {
        const dir = DIR_META[it.direction];
        const dom = domainOf(it.url, it.source);
        return (
          <div className={`db-news ${it.direction || ""}`} key={i}>
            <div className="db-news-top">
              <span className="db-news-date num">{it.date || "—"}</span>
              {dir && <span className={`db-dir ${dir.cls}`}>{t(dir.txt)}</span>}
              <ReactionTag r={it.reaction} />
            </div>
            {it.url ? <a className="db-news-t" href={it.url} target="_blank" rel="noreferrer">{t(it.title)}</a>
                    : <div className="db-news-t">{t(it.title)}</div>}
            {it.summary && <div className="db-news-s">{t(it.summary)}</div>}
            {it.same_window && <div className="db-news-sw">{t("同日多条 · 前后变动为合计,不可归因到单条")}</div>}
            {dom && (
              <a className="db-news-src" href={it.url} target="_blank" rel="noreferrer" title={dom}>
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
  const { t } = useLang();
  if (!s) return <div className="bf-empty">{t("该话题暂无社媒数据（或未配置）")}</div>;
  const acc = s.acceleration;
  const heating = typeof acc === "number" && acc > 1;
  const div = s.author_diversity_pct;
  const organic = s.organic;
  return (
    <div className="soc">
      <div className="soc-metrics">
        <div className="soc-m">
          <div className="soc-m-lab">{t("情绪动量")}</div>
          <div className={`soc-m-val ${heating ? "hot" : "cold"}`}>{heating ? t("🔥 升温") : t("❄ 降温")} <span className="soc-acc num">{typeof acc === "number" ? acc.toFixed(2) : "—"}</span></div>
        </div>
        <div className="soc-m">
          <div className="soc-m-lab">{(s.tweet_count || 0).toLocaleString()} {t("条讨论")}</div>
          <div className={`soc-bot ${organic ? "ok" : "bad"}`}>{organic ? `${t("✓ 有机")} ${div}%` : `${t("🤖 疑似刷量")} ${div}%`}</div>
        </div>
      </div>
      {!organic && (
        <div className="soc-warn">{t("⚠ 作者多样性")} {div}% {t("< 20% —— 很可能是刷量/机器人，当噪音看，别当真情绪")}</div>
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
      <div className="soc-foot">🔖 {t("热帖标 = 互动热度（♥+↻），")}<b>{t("非情绪判断")}</b>{t("——社媒是情绪不是事实，方向请看新闻与 ⑥")}</div>
    </div>
  );
}

// 上帝视角时间轴：价格曲线 × 建仓点 × 新闻发光节点 × 剩余空间（D3 算数学，React 渲 SVG）
const GMT_W = 760, GMT_H = 340, GMT_M = { t: 18, r: 38, b: 28, l: 14 };
function _pdate(s) { return new Date(s + "T00:00:00Z"); }
function gmtReact(rx, t = (s) => s) {
  if (!rx || !rx.available) return { txt: t("市场反应不可知"), cls: "rx-na" };
  const m = REACT_SYM[rx.kind] || REACT_SYM.weak;
  return { txt: `${m.sym}${t(m.txt)} ${rx.move_pct > 0 ? "+" : ""}${rx.move_pct}%`, cls: m.cls };
}
function fmtMD(dt) { return `${dt.getUTCMonth() + 1}/${dt.getUTCDate()}`; }
// 滚动数字（odometer）：连续 reel（0-9 重复 8 组），用**累计绝对位置**滚动，按最短方向连续过渡——
// 9→0 向前滚(不再倒退一圈)，scrub 顺滑。挂载从 0 滚到目标。零依赖。
const ROLL_REEL = 80, ROLL_MID = 40;
function RollingDigit({ d }) {
  const posRef = useRef(ROLL_MID);          // 挂载从位置 40(显示 0)开始
  const [pos, setPos] = useState(ROLL_MID);
  useEffect(() => {
    const cur = posRef.current;
    const curMod = ((cur % 10) + 10) % 10;
    let delta = d - curMod;                  // 最短连续方向：±5 内直接走，超过则反向更近
    if (delta > 5) delta -= 10;
    else if (delta < -5) delta += 10;
    const next = cur + delta;
    posRef.current = next;
    setPos(next);
  }, [d]);
  return (
    <span className="roll-d"><span className="roll-col" style={{ transform: `translateY(${-pos}em)` }}>
      {Array.from({ length: ROLL_REEL }, (_, n) => <span key={n} className="roll-n">{n % 10}</span>)}
    </span></span>
  );
}
function RollingNumber({ value }) {
  return <span className="roll">{String(value).split("").map((c, i) => <RollingDigit key={i} d={+c} />)}</span>;
}
function GodModeTimeline({ d }) {
  const { t } = useLang();
  const [cross, setCross] = useState(null);     // 鼠标所在的 series 索引（实时光标）
  const [pinned, setPinned] = useState(null);   // 点击彩点钉住的新闻组（date 为键）
  const [range, setRange] = useState("all");    // all | 30 | 7 天窗
  const allSeries = (d.price_series || []).filter((p) => typeof p.price === "number")
    .map((p) => ({ t: _pdate(p.date), date: p.date, price: p.price }));
  if (allSeries.length < 2)
    return <div className="bf-empty">{t("该盘价格日线不足(薄盘/新盘)——按\"有多少画多少\",暂不足以绘制时间轴")}</div>;
  const rangeN = range === "30" ? 30 : range === "7" ? 7 : allSeries.length;
  const series = allSeries.slice(-Math.max(rangeN, 2));

  const pos = d.position || {}, wpa = pos.what_position_actions || {};
  const act = wpa.actions || {}, un = wpa.unrealized || {}, pc = pos.price_context || {};
  const side = ((pos.meta || {}).analyzed_side || "").toUpperCase();
  const settle = (pos.meta || {}).settle;                      // "还有约55.0天"
  const settleDays = (() => { const m = String(settle || "").match(/还有约([\d.]+)天/); return m ? Math.round(+m[1]) : null; })();
  const entryDate = act.entry_time ? act.entry_time.slice(0, 10) : null;
  const entryPrice = act.avg_entry_price, curPrice = pc.current_price;
  // 🔴 颜色按价格走势(涨绿/跌红),像 Polymarket——描述价格本身、不与"他赚没赚"混淆(后者在英雄区)
  const firstP = series[0].price, lastP = series[series.length - 1].price;
  const dirCls = lastP >= firstP ? "pos" : "neg";
  const chgPts = typeof curPrice === "number" ? Math.round((curPrice - firstP) * 100) : null;

  // ── 布局：右侧留未来区（距结算倒计时，非线性、定宽 22%，天数如实标注）──────
  const iw = GMT_W - GMT_M.l - GMT_M.r, ih = GMT_H - GMT_M.t - GMT_M.b;
  const fw = settleDays != null && settleDays > 0 ? Math.round(iw * 0.22) : 0;
  const pw = iw - fw;                                          // 价格数据绘图宽
  const x = scaleTime().domain(extent(series, (s) => s.t)).range([0, pw]);
  // 🔴 Y 轴聚焦到数据实际区间（否则 80-98% 的走势被压成顶部一条平线）
  const prices = series.map((s) => s.price).concat(typeof entryPrice === "number" ? [entryPrice] : []);
  const pMin = Math.min(...prices), pMax = Math.max(...prices);
  const pad = Math.max((pMax - pMin) * 0.18, 0.025);
  const y = scaleLinear().domain([Math.max(0, pMin - pad), Math.min(1, pMax + pad)]).range([ih, 0]);
  const lg = d3line().x((s) => x(s.t)).y((s) => y(s.price)).curve(curveMonotoneX);
  const ag = d3area().x((s) => x(s.t)).y0(ih).y1((s) => y(s.price)).curve(curveMonotoneX);
  // 成本分区：曲线与入场成本线之间的面积，高于成本=绿、低于=红（持有侧视角，纯代码数学）
  const hasEntryPx = typeof entryPrice === "number";
  const agEntry = hasEntryPx ? d3area().x((s) => x(s.t)).y0(y(entryPrice)).y1((s) => y(s.price)).curve(curveMonotoneX) : null;

  const priceAt = (date) => {
    const dt = _pdate(date); let best = series[0];
    for (const s of series) if (Math.abs(s.t - dt) < Math.abs(best.t - dt)) best = s;
    return best.price;
  };
  const [dMin, dMax] = x.domain();

  // ── 新闻聚簇：同日多条合并为一个节点（count 徽章），方向一致时用 ▲/▼ 形状 ────
  const inWin = (d.news_stream || []).filter((n) => n.date && _pdate(n.date) >= dMin && _pdate(n.date) <= dMax);
  const byDate = new Map();
  for (const n of inWin) {
    if (!byDate.has(n.date)) byDate.set(n.date, []);
    byDate.get(n.date).push(n);
  }
  const RANK = { reject: 3, confirm: 2, weak: 1 };
  const groups = [...byDate.entries()].map(([date, items]) => {
    let kind = null, best = 0;
    for (const n of items) {
      const k = n.reaction && n.reaction.available ? n.reaction.kind : null;
      if (k && (RANK[k] || 0) > best) { best = RANK[k] || 0; kind = k; }
    }
    const dirs = new Set(items.map((n) => n.direction).filter(Boolean));
    return { date, items, t: _pdate(date), px: priceAt(date), kind,
             dir: dirs.size === 1 ? [...dirs][0] : null };
  });
  const groupColor = (g) => g.kind === "confirm" ? "var(--pos)" : g.kind === "reject" ? "var(--neg)" : g.kind === "weak" ? "var(--fg-3)" : "var(--fg-4)";

  const sx = (vx) => ((GMT_M.l + vx) / GMT_W) * 100;
  const sy = (vy) => ((GMT_M.t + vy) / GMT_H) * 100;
  const yTicks = y.ticks(4), xTicks = x.ticks(Math.min(6, series.length));

  const hv = cross != null ? series[cross] : null;
  const bright = cross != null ? series.slice(0, cross + 1) : series;
  const shownPrice = hv ? hv.price : curPrice;
  // 悬停点 vs 入场成本的浮动（纯代码数学：百分点差）
  const hvVsEntry = hv && hasEntryPx ? Math.round((hv.price - entryPrice) * 100) : null;

  // 🔴 扫到彩点"附近"(≤26 viewBox 单位)就激活该新闻组 → 可发现性大增；点击则钉住
  let hoverGroup = null;
  if (hv && groups.length) {
    const cxp = x(hv.t); let bd = Infinity;
    for (const g of groups) { const dd = Math.abs(x(g.t) - cxp); if (dd < bd) { bd = dd; hoverGroup = g; } }
    if (bd > 26) hoverGroup = null;
  }
  const activeGroup = pinned ? groups.find((g) => g.date === pinned) || null : hoverGroup;

  function onMove(e) {
    const rect = e.currentTarget.getBoundingClientRect();
    const plotX = Math.max(0, Math.min(pw, ((e.clientX - rect.left) / rect.width) * GMT_W - GMT_M.l));
    const td = x.invert(plotX);
    let bi = 0;
    for (let k = 1; k < series.length; k++) if (Math.abs(series[k].t - td) < Math.abs(series[bi].t - td)) bi = k;
    setCross(bi);
  }
  function onClick() {
    if (hoverGroup) setPinned(pinned === hoverGroup.date ? null : hoverGroup.date);
    else if (pinned) setPinned(null);
  }

  // 入场标记：可能早于本图窗口 → 竖线钳到左缘并注明
  const entryT = entryDate ? _pdate(entryDate) : null;
  const entryInWin = entryT && entryT >= dMin && entryT <= dMax;
  const entryX = entryT ? Math.max(0, Math.min(pw, x(entryT))) : null;
  const asOfLabel = series[series.length - 1].date;

  // 结算日期 = as_of + 剩余天数（前端代码日期数学，供未来区旗标；AI 从不参与）
  const settleDateStr = (() => {
    if (settleDays == null) return null;
    const dt = new Date(_pdate(asOfLabel).getTime() + settleDays * 86400e3);
    return `${dt.getUTCMonth() + 1}/${dt.getUTCDate()}`;
  })();

  return (
    <div className="gmt">
      <div className="gmt-header">
        <div className={`gmt-h-side ${side === "YES" ? "yes" : "no"}`}><span className="gmt-h-side-dot" />{t("押")} {side}</div>
        <div className="gmt-h-row">
          <span className={`gmt-h-pct ${dirCls}`}>{typeof shownPrice === "number" ? <><RollingNumber value={Math.round(shownPrice * 100)} />%</> : "—"}</span>
          <span className="gmt-h-unit" title={t("市场赔率隐含的、对『会发生』的概率估计——不是胜率、不是收益（行话叫『隐含概率』）")}>{t("市场认为「")}{side}{t("」的概率")}</span>
          {hv
            ? <span className="gmt-h-date">{hv.date.slice(5)}{hvVsEntry != null && <span className={`gmt-h-vse ${hvVsEntry >= 0 ? "pos" : "neg"}`}> · {t("vs 入场")} {hvVsEntry >= 0 ? "+" : ""}{hvVsEntry}pt</span>}</span>
            : (chgPts != null && <span className={`gmt-h-delta ${dirCls}`} title={t("本图时间段内，这个概率涨/跌了多少个百分点")}>{chgPts >= 0 ? "▲ +" : "▼ "}{Math.abs(chgPts)}% <span className="gmt-h-deltalab">{t("这段时间")}</span></span>)}
          {allSeries.length > 15 && (
            <span className="gmt-range">
              {[["7", "7D"], ["30", "30D"], ["all", t("全部")]].map(([k, lab]) => (
                <button key={k} className={range === k ? "on" : ""} onClick={() => { setRange(k); setCross(null); setPinned(null); }}>{lab}</button>
              ))}
            </span>
          )}
        </div>
      </div>
      <div className="gmt-wrap">
        <svg viewBox={`0 0 ${GMT_W} ${GMT_H}`} className="gmt-svg" onMouseMove={onMove}
          onMouseLeave={() => setCross(null)} onClick={onClick}>
          <defs>
            <linearGradient id="gmt-grad-pos" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stopColor="var(--pos)" stopOpacity="0.28" />
              <stop offset="100%" stopColor="var(--pos)" stopOpacity="0" />
            </linearGradient>
            <linearGradient id="gmt-grad-neg" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stopColor="var(--neg)" stopOpacity="0.26" />
              <stop offset="100%" stopColor="var(--neg)" stopOpacity="0" />
            </linearGradient>
            {hasEntryPx && (
              <>
                <clipPath id="gmt-clip-above"><rect x="0" y={-GMT_M.t} width={pw} height={y(entryPrice) + GMT_M.t} /></clipPath>
                <clipPath id="gmt-clip-below"><rect x="0" y={y(entryPrice)} width={pw} height={ih - y(entryPrice) + GMT_M.b} /></clipPath>
              </>
            )}
          </defs>
          <g transform={`translate(${GMT_M.l},${GMT_M.t})`}>
            {xTicks.map((tk, i) => (
              <g key={"x" + i}>
                <line x1={x(tk)} x2={x(tk)} y1="0" y2={ih} className="gmt-grid v" />
                <text x={x(tk)} y={ih + 15} className="gmt-xtick">{fmtMD(tk)}</text>
              </g>
            ))}
            {yTicks.map((tk, i) => (
              <g key={"y" + i}>
                <line x1="0" x2={iw} y1={y(tk)} y2={y(tk)} className="gmt-grid" />
                <text x={iw + 6} y={y(tk)} className="gmt-ytick r" dy="0.32em">{Math.round(tk * 100)}%</text>
              </g>
            ))}

            {/* 未来区：距结算倒计时（定宽、非线性，天数如实标注） */}
            {fw > 0 && (
              <g className="gmt-future">
                <rect x={pw} y="0" width={fw} height={ih} className="gmt-future-bg" />
                <line x1={pw} x2={pw} y1="0" y2={ih} className="gmt-future-edge" />
                <text x={pw + fw / 2} y={16} className="gmt-future-lab">⏱ {t("距结算")} ≈{settleDays}{t("天")}</text>
                {settleDateStr && <text x={pw + fw / 2} y={30} className="gmt-future-date">{settleDateStr}</text>}
                <text x={pw + 4} y={ih - 6} className="gmt-future-now">{t("今天")} {asOfLabel.slice(5)}</text>
              </g>
            )}

            {/* 成本分区着色：高于入场成本=绿、低于=红；无成本价则退回走势渐变 */}
            {hasEntryPx ? (
              <>
                <path d={agEntry(series)} className="gmt-pl above" clipPath="url(#gmt-clip-above)" />
                <path d={agEntry(series)} className="gmt-pl below" clipPath="url(#gmt-clip-below)" />
              </>
            ) : (
              <path d={ag(series)} className="gmt-area" fill={`url(#gmt-grad-${dirCls})`} />
            )}

            {cross != null && <path d={lg(series)} className={`gmt-line ${dirCls} dim`} />}
            <path d={lg(bright)} className={`gmt-line ${dirCls} draw`} pathLength="1" />

            {/* 入场成本线 + 入场时点 */}
            {hasEntryPx && <line x1="0" x2={pw} y1={y(entryPrice)} y2={y(entryPrice)} className="gmt-entry-h" />}
            {entryX != null && hasEntryPx && (
              <g>
                <line x1={entryX} x2={entryX} y1="0" y2={ih} className="gmt-entry-v" />
                {entryInWin && <circle cx={entryX} cy={y(entryPrice)} r="4.5" className="gmt-entry-dot" />}
              </g>
            )}

            {/* 新闻节点：▲支持 ▼威胁 ●未分类；同日聚簇带数字徽章；点击钉住 */}
            {groups.map((g, i) => {
              const gx = x(g.t), gy = y(g.px), on = activeGroup === g;
              const r = on ? 7.5 : 5.5, c = groupColor(g);
              const pinnedThis = pinned === g.date;
              return (
                <g key={g.date} className="gmt-node-g" style={{ "--i": i }}>
                  {g.dir === "support" && <path d={`M${gx},${gy - r} L${gx + r},${gy + r * 0.9} L${gx - r},${gy + r * 0.9} Z`} fill={c} className={`gmt-node ${on ? "active" : ""}`} />}
                  {g.dir === "threat" && <path d={`M${gx},${gy + r} L${gx + r},${gy - r * 0.9} L${gx - r},${gy - r * 0.9} Z`} fill={c} className={`gmt-node ${on ? "active" : ""}`} />}
                  {!g.dir && <circle cx={gx} cy={gy} r={r} fill={c} className={`gmt-node ${on ? "active" : ""}`} />}
                  {g.items.length > 1 && (
                    <>
                      <circle cx={gx + 7} cy={gy - 8} r="6.5" className="gmt-node-badge-bg" />
                      <text x={gx + 7} y={gy - 8} dy="0.34em" className="gmt-node-badge">{g.items.length}</text>
                    </>
                  )}
                  {pinnedThis && <circle cx={gx} cy={gy} r={r + 4} className="gmt-node-pin" />}
                </g>
              );
            })}

            {/* 悬停十字光标（横+竖）*/}
            {hv && (
              <g>
                <line x1={x(hv.t)} x2={x(hv.t)} y1="0" y2={ih} className="gmt-cross-v" />
                <line x1="0" x2={iw} y1={y(hv.price)} y2={y(hv.price)} className="gmt-cross-h" />
                <circle cx={x(hv.t)} cy={y(hv.price)} r="5" className={`gmt-cross-dot ${dirCls}`} />
              </g>
            )}
            {!hv && typeof curPrice === "number" && <circle cx={pw} cy={y(curPrice)} r="4.5" className={`gmt-now-dot ${dirCls}`} />}
          </g>
        </svg>

        {/* 右缘价签：现价（彩）+ 入场成本（灰）+ 悬停价（跟随）*/}
        {typeof curPrice === "number" && !hv && (
          <div className={`gmt-pill cur ${dirCls}`} style={{ left: `${sx(pw) + 0.4}%`, top: `${sy(y(Math.max(y.domain()[0], Math.min(y.domain()[1], curPrice))))}%` }}>{Math.round(curPrice * 100)}¢</div>
        )}
        {hasEntryPx && (
          <div className="gmt-pill entry" style={{ left: `${sx(pw) + 0.4}%`, top: `${sy(y(entryPrice))}%` }}>{t("建仓")} {Math.round(entryPrice * 100)}¢</div>
        )}
        {hv && (
          <div className={`gmt-pill hover ${dirCls}`} style={{ left: `${sx(pw) + 0.4}%`, top: `${sy(y(hv.price))}%` }}>{Math.round(hv.price * 100)}¢</div>
        )}

        {hv && <div className="gmt-cross-date" style={{ left: `${sx(x(hv.t))}%` }}>{fmtMD(hv.t)}</div>}
        {hv && (
          <div className={`gmt-cross-tip ${dirCls} ${sx(x(hv.t)) > 60 ? "l" : ""}`} style={{ left: `${sx(x(hv.t))}%`, top: `${sy(y(hv.price))}%` }}>
            {t("押")} {side} {Math.round(hv.price * 100)}%{hvVsEntry != null && <span className="gmt-tip-vse"> · {hvVsEntry >= 0 ? "+" : ""}{hvVsEntry}pt {t("vs 入场")}</span>}
          </div>
        )}
        {entryX != null && hasEntryPx && !entryInWin && (
          <div className="gmt-lbl entry" style={{ left: `${sx(entryX)}%`, top: `${sy(y(entryPrice))}%` }}>
            ◂ {t("建仓")} {entryDate.slice(5)} · {Math.round(entryPrice * 100)}¢
          </div>
        )}
      </div>

      {/* 🔴 催化剂读出条：固定图下方、永不遮挡价格线；点击彩点可钉住（演示时不会因移开鼠标丢失） */}
      <div className={`gmt-readout ${activeGroup ? "on" : ""}`}
        style={activeGroup ? { borderLeftColor: groupColor(activeGroup) } : null}>
        {activeGroup ? (
          <>
            {activeGroup.items.slice(0, 3).map((n, i) => {
              const rc = gmtReact(n.reaction, t);
              return (
                <div className="gmt-ro-line" key={i}>
                  {i === 0 && <span className="gmt-ro-date num">{activeGroup.date}</span>}
                  {i === 0 && pinned === activeGroup.date && <span className="gmt-ro-pin" title={t("已钉住 · 再点一次取消")}>📌</span>}
                  {n.direction && <span className={`db-dir ${n.direction}`}>{n.direction === "support" ? t("支持") : t("威胁")}</span>}
                  <span className={`rx ${rc.cls}`}>{rc.txt}</span>
                  <span className="gmt-ro-title">{t(n.title)}</span>
                  {n.url && <a className="gmt-ro-link" href={n.url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>{t("原文 ↗")}</a>}
                </div>
              );
            })}
            {activeGroup.items.length > 3 && <div className="gmt-ro-more">+{activeGroup.items.length - 3} {t("条同日新闻，见下方新闻列")}</div>}
            {activeGroup.items.length === 1 && activeGroup.items[0].summary && <div className="gmt-ro-sum">{t(activeGroup.items[0].summary)}</div>}
            <div className="gmt-ro-foot">{activeGroup.items[0].origin} {t("· 与价格变动")}<b className="gmt-warn">{t("时间相关、非因果")}</b>{activeGroup.items.length > 1 && <span> · {t("同日多条 · 前后变动为合计,不可归因到单条")}</span>}</div>
          </>
        ) : (
          <div className="gmt-ro-hint chips">
            <span className="gmt-chip strong"><i className="gmt-foot-dot" /><b>{t("扫过彩点")}</b>{t("看催化剂")} · {t("点击可钉住")}</span>
            <span className="gmt-chip"><span className="rx-c-pos">●{t("印证")}</span> <span className="rx-c-neg">●{t("不买账")}</span> <span className="gmt-chip-dim">●{t("无反应")}</span></span>
            <span className="gmt-chip">▲{t("支持")} ▼{t("威胁")}</span>
            <span className="gmt-chip"><span className="rx-c-pos">■</span>{t("高于成本")} <span className="rx-c-neg">■</span>{t("低于成本")}</span>
            <span className="gmt-chip gmt-warn">{t("时间相关、非因果")}</span>
          </div>
        )}
      </div>
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
  const { t } = useLang();
  const nick = profile.name || profile.pseudonym || abbrev(profile.address);
  const last = pnlHistory && pnlHistory.length ? pnlHistory[pnlHistory.length - 1].p : null;
  return (
    <div className="vh-badge">
      <Avatar profile={profile} />
      <div className="vh-badge-meta">
        <div className="vh-badge-nick">{nick}</div>
        <div className="vh-badge-stats num">
          #{rk.rank ?? "—"} · {t("胜率")} {rk.win_rate ? (Number(rk.win_rate) * 100).toFixed(0) + "%" : "—"}
          {last != null ? " · " + fmtPnlCompact(last) : (rk.total_pnl ? " · " + money(Number(rk.total_pnl)) : "")}
        </div>
      </div>
      {pnlHistory && pnlHistory.length > 1 && <MiniSpark points={pnlHistory} />}
    </div>
  );
}

// 把代码降级原因（R2/底座矩阵/pnl…）翻成人话（守协作纪律#5：弱化不删，原文仍在审计脚注）
function reasonCN(s, t = (x) => x) {
  s = String(s || "");
  if (s.startsWith("底座矩阵")) {
    const m = s.match(/底座矩阵:(\w+)\(pnl=([^)]+)\)/);
    const conf = m ? t({ high: "高", medium: "中", low: "低" }[m[1]] || m[1]) : "";
    const pnl = m ? m[2] : "—";
    return { tag: t("起步"), txt: `${t("按他这注的浮盈(")}${pnl}${t(")和单边/证据情况，矩阵起步给「")}${conf}${t("」")}` };
  }
  if (s.startsWith("R1")) return { tag: t("市场测谎"), txt: s.includes("全部") ? t("他押的方向有支持新闻，但市场全程反着定价（不买账）→ 打到低") : t("他押的方向有支持新闻被市场部分反着定价 → 压到中") };
  if (s.startsWith("R2")) return { tag: t("对冲"), txt: t("他两边都压了不少（像在做市/对冲），不是单边信念 → 信心压到中") };
  if (s.startsWith("R3")) return { tag: t("退出"), txt: t("近 48 小时他在大额减仓离场 → 信心压到中") };
  if (s.startsWith("R4")) return { tag: t("证据双空"), txt: t("支持和威胁两边都没找到对题证据 → 打到低") };
  return { tag: "", txt: s };
}

// 首屏判断英雄区：结论先行，0.5 秒拿到"还能不能跟"
function VerdictHero({ d }) {
  const { t } = useLang();
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

  // ⑥ 体检 chip（纯前端代码算，不改 AI 输出、不拦截——"不加守卫≠不可观测"的界面化）
  const advisories = [];
  if (r.market_lean && r.thesis_audit) {
    const nArt = r.thesis_audit.n_articles;
    if (typeof nArt === "number" && nArt < 3) advisories.push(`${t("⚠ 证据薄：共享文章池仅")} ${nArt} ${t("篇，裁决人输入有限")}`);
    const conf = String(r.confidence || "").toLowerCase();
    if (conf === "high" && typeof r.lean_strength === "number" && r.lean_strength < 60)
      advisories.push(t("⚠ 信心与倾向强度不符：高信心但证据压倒性 <60/100，谨慎采信"));
  }

  return (
    <div className="vh">
      <div className="vh-top">
        <div className="vh-q">{m.market} <span className="vh-side">· {t("押")} {side}</span></div>
        <CredBadge profile={profile} rk={rk} pnlHistory={id.pnl_history} />
      </div>

      {(pos.what_the_bet || pos.resolution_criteria) && (
        <div className="db-whatbet vh-whatbet">
          <div className="db-whatbet-h">{t("这一注在赌什么")} <ZhNote text={pos.what_the_bet} /></div>
          {pos.what_the_bet && <div className="db-whatbet-t">{renderInline(t(pos.what_the_bet))}</div>}
          {pos.resolution_criteria && (
            <details className="db-rc">
              <summary>{t("官方结算规则原文（什么算赢）")}</summary>
              <div className="db-rc-body">{pos.resolution_criteria}</div>
            </details>
          )}
        </div>
      )}

      <div className="vh-essence">
        <div className="vh-e"><span>{t("入场成本")}</span><b className="vh-from num">{cent(act.avg_entry_price)}</b></div>
        <span className="vh-arrow">→</span>
        <div className="vh-e vh-e-main">
          <span>{t("现价 · 隐含概率")}</span>
          <div className="vh-now-row">
            <b className={`vh-now num ${dirCls}`}>{cent(pc.current_price)}</b>
            {typeof upct === "number" && (
              <span className={`vh-delta ${dirCls}`}>{upct >= 0 ? "▲" : "▼"} {upct >= 0 ? "+" : ""}{upct}%</span>
            )}
          </div>
        </div>
        <div className="vh-e vh-room"><span>{t("剩余空间(若赢)")}</span><b className="num">{pc.remaining_upside_pct_if_win != null ? pc.remaining_upside_pct_if_win + "%" : "—"}</b></div>
      </div>

      {r.guard_tripped ? (
        <div className="vh-light guard"><span className="vh-call">{t("🛡 守卫拦截")}</span>
          <span className="vh-conf">{t("该判断触发诚实守卫,不输出结论")}</span></div>
      ) : (
        <div className={`vh-light ${cls}`}>
          <span className="vh-dot" />
          <span className="vh-call">{t(FOLLOW_LABEL_CN[r.follow_call] || r.follow_call || "—")}</span>
          <span className="vh-conf">{t("信心")} <b>{t(CONF_CN[r.confidence] || r.confidence || "—")}</b></span>
        </div>
      )}

      {r.confidence_source === "fallback_v2_matrix" && !r.guard_tripped && (
        <div className="vh-fallback">{t("⚠ 市场级推理暂不可用，本次信心来自旧的代码矩阵（锚钱包盈亏），参考价值打折")}</div>
      )}

      {r.market_lean && (
        <div className="vh-edge">
          {t("市场倾向")} <b>{r.market_lean}</b>{r.lean_strength != null && <span className="vh-edge-str"> {r.lean_strength}/100</span>}
          {r.alignment && <span className={`vh-align ${r.alignment.includes("逆") ? "against" : "with"}`}> · {t("这一注")} {t(r.alignment)}</span>}
          {r.event_structure && r.event_structure.multi && (
            <span className="vh-multi" title={t("多结局事件：隐含概率是「此候选 vs 全场」，非二元 Yes/No")}>
              · {t("多结局")} {r.event_structure.n_candidates} {t("选 1（基线")} {r.event_structure.baseline_pct}%）
            </span>
          )}
        </div>
      )}

      {advisories.length > 0 && (
        <div className="vh-advisories">
          {advisories.map((a, i) => <span className="vh-advisory" key={i}>{a}</span>)}
        </div>
      )}

      <div className="vh-verdict">{r.guard_tripped ? r.guard_message : t(r.reasoning)}{!r.guard_tripped && r.reasoning && <ZhNote text={r.reasoning} />}</div>

      {!r.guard_tripped && r.pivotal_unknown && (
        <div className="vh-pivotal">{t("⚖ 胜负手：")}{t(r.pivotal_unknown)}</div>
      )}

      {!r.guard_tripped && r.market_lean && r.thesis_audit && (
        <details className="vh-audit">
          <summary>{t("信心怎么来的？（多空对抗 → 中立裁决，单一信心直出）")}</summary>
          {r.input_trust && r.input_trust.length > 0 && (
            <div className="vh-trust">
              <div className="vh-trust-h">{t("输入可信度（决定价格/证据该信几分）")}</div>
              {r.input_trust.map((l, i) => <div className="vh-trust-l" key={i}>· {t(l)}</div>)}
            </div>
          )}
          <div className="vh-audit-th"><b>{t("多头(押 YES)：")}</b>{t(r.thesis_audit.bull)}</div>
          <div className="vh-audit-th"><b>{t("空头(押 NO)：")}</b>{t(r.thesis_audit.bear)}</div>
          <div className="vh-audit-foot">{t("↑ 同一市场只算一次、两个反向钱包共享同一份市场观；信心由裁决人直出、不锚钱包盈亏 · 已记日志，待盘结算回验是否真命中")}</div>
        </details>
      )}

      {!r.guard_tripped && !r.market_lean && r.confidence_reasons && r.confidence_reasons.length > 0 && (
        <details className="vh-audit">
          <summary>{t("为什么是「")}{t(CONF_CN[r.confidence] || r.confidence)}{t("」信心？（点开看代码怎么算的）")}</summary>
          <ul className="vh-audit-list">
            {r.confidence_reasons.map((s, i) => {
              const rc = reasonCN(s, t);
              return <li key={i}>{rc.tag && <span className="vh-audit-tag">{rc.tag}</span>}{rc.txt}</li>;
            })}
          </ul>
          <div className="vh-audit-foot">{t("↑ 代码置信度矩阵逐条算（只降不升）、AI 不改判 · 原始：")}{r.confidence_reasons.join(" · ")}</div>
        </details>
      )}

      {d.behavior && <div className="vh-whale">{t("🐳 巨鲸动态 ·")} {t(d.behavior.fact)}</div>}
      <div className="vh-disc">{t("这是对\"局势性质\"的判断(还有多少空间/风险在哪/市场认不认这个方向),不替你决定跟不跟 · 天平由你裁决")}</div>
    </div>
  );
}

function BoardBody({ d }) {
  const { t } = useLang();
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
      {d.world_summary && <div className="db-wsum gmt-summary"><ZhNote text={d.world_summary} /><Narrative text={t(d.world_summary)} /></div>}

      {/* 新闻(事实) × 社媒(情绪) 并排 —— 同一问题的两面，视觉刻意分开 */}
      <div className="db-sec-tag">{t("世界发生了什么 × 在怎么议论")}</div>
      <div className="ns-split">
        <div className="ns-col news">
          <div className="ns-col-h"><span className="ns-ico">📰</span>{t("新闻 ·")} <b>{t("事实")}</b><span className="ns-sub">{t("世界发生了什么")}</span></div>
          <NewsStream items={d.news_stream} />
        </div>
        <div className="ns-col social">
          <div className="ns-col-h soc"><span className="ns-ico">💬</span>{t("社媒 ·")} <b>{t("情绪")}</b><span className="ns-sub">{t("小心是情绪、可能刷量")}</span></div>
          <SocialPulse s={d.social} />
        </div>
      </div>
      <div className="ns-diverge">{t("⚖️ 最值钱的对照：新闻在涨 + 社媒在嗨，但 ")}<b>{t("聪明钱（行为流）信不信？市场价跟没跟？")}</b>{t(" 顺风只陈列，背离才是金。")}</div>

      {/* 巨鲸 48h 行为流（折叠）*/}
      <Fold title={t("巨鲸 48h 动作流")} sub={t("加仓 / 减仓 / 没动 + 3h/24h/48h 窗口")}>
        <BehaviorFlag b={d.behavior} />
      </Fold>

      {/* ② 这一注 · 明细 */}
      <div className="db-sec-tag">{t("② 这一注 · 明细")}</div>
      <div className="c-head db-pos-head">
        <div>
          <div className="q">{m.market}</div>
          <div className="meta">{t(m.settle)} · {t("建仓")} {act.entry_time?.slice(0, 10) || "—"}</div>
        </div>
        <span className="outcome">{(m.analyzed_side || "").toUpperCase()}</span>
      </div>
      <div className="bf-grid db-grid">
        <div className="bf-mini">
          <div className="bf-mini-h">{t("动作 · 他做了什么")}</div>
          <div className="bf-kv"><span>{t("均价 / 成本")}</span><b className="num">{price(act.avg_entry_price)} · {money(act.net_cost_usd)}</b></div>
          <div className="bf-kv"><span>{t("买入笔数")}</span><b className="num">{act.num_buys ?? "—"}</b></div>
          <div className="bf-kv"><span>{t("盈亏")}</span><b className={`num ${Number(un.unrealized_pnl_usd) >= 0 ? "pos" : "neg"}`}>{money(un.unrealized_pnl_usd)} {typeof upct === "number" ? `(${upct >= 0 ? "+" : ""}${upct}%)` : ""}</b></div>
          <div className="bf-note">{ts.hedged ? t("两边对冲 · 做市/非单边信念") : t("单边建仓 · 信念注")}</div>
        </div>
        <div className="bf-mini">
          <div className="bf-mini-h">{t("价格 · Entry ↗ Current")}</div>
          <div className="bf-kv"><span>{t("入场 → 现价")}</span><b className="num">{price(act.avg_entry_price)} → {price(pc.current_price)}</b></div>
          <div className="bf-kv"><span>{t("vs 入场 / 隐含概率")}</span><b className="num">{typeof pc.price_delta_pct === "number" ? (pc.price_delta_pct >= 0 ? "+" : "") + pc.price_delta_pct + "%" : "—"} · {pc.implied_probability_pct}%</b></div>
          <div className="bf-kv"><span>{t("剩余空间(赢) / 赔率")}</span><b className="num">{pc.remaining_upside_pct_if_win}% · {pc.odds_to_one ?? "—"}</b></div>
        </div>
      </div>

      {/* ③ 当前赔率 · 原生条（替 iframe）*/}
      <div className="db-sec-tag">{t("③ 当前赔率 · 市场怎么定价")}</div>
      <OddsBar held={pc.current_price} side={(m.analyzed_side || "").toUpperCase()} slug={d.market?.slug} />

      {/* 降级：钱包历史体量（资格审查，不再霸占首屏）*/}
      <Fold title={t("钱包历史体量 · 身份背书")} sub={t("累计盈亏曲线 + 风险标记（背景调查，非本注结论）")}>
        {id.pnl_history && id.pnl_history.length > 1 && <PnlChart points={id.pnl_history} />}
        {wrLie && <div className="bf-lie">{t("⚠ 胜率谎言:高胜率但净盈亏为负 — 看净盈亏,非胜率")}</div>}
        {q.flagged_metrics && <div className="bf-sub db-flags">{t("风险标记: ")}{flagsCN(q.flagged_metrics, t)}</div>}
        <div className="db-id-stats db-id-stats-full">
          <span>{t("官方榜")} <b className="num">#{rk.rank ?? "—"}</b></span>
          <span>{t("胜率")} <b className="num">{rk.win_rate ? (Number(rk.win_rate) * 100).toFixed(1) + "%" : "—"}</b></span>
        </div>
      </Fold>

      <div className="foot">{t("结论由代码矩阵算定信心、AI 只解释不改判 · 价格为市场隐含概率(非胜率) · 公开数据整理,非投资建议")}</div>
    </div>
  );
}

// Polymarket 价格滚动栏（第三方 widget：先渲 div、再注入脚本，脚本按 id 找 div 渲染）
// 入口滚动条：本周政治盘热门交易者（hot_traders.py：579 7d 宇宙 × 581 政治 7d 盈亏）。点一个直接解码。
function HotTraders({ onPick }) {
  const { t } = useLang();
  const [data, setData] = useState(null);
  useEffect(() => { fetch(`${API}/hot-traders`).then((r) => r.json()).then(setData).catch(() => {}); }, []);
  const traders = (data && data.traders) || [];
  if (!traders.length) return null;
  const loop = [...traders, ...traders];   // 两份拼接 = 无缝循环
  return (
    <div className="hot-wrap" title={t("本周政治盘最赚的交易者 · 点击直接解码（数据来自 581 政治盘 7 天盈亏，仅地址无昵称）")}>
      <span className="hot-label">{t("🔥 本周政治盘热门")}</span>
      <div className="hot-marquee">
        <div className="hot-track">
          {loop.map((t, i) => (
            <button className="hot-item" key={i} onClick={() => onPick(t.wallet)} title={t.wallet}>
              <span className="hot-rank num">#{(i % traders.length) + 1}</span>
              <span className="hot-addr num">{abbrev(t.wallet)}</span>
              <span className="hot-pnl num">{money(t.weekly_politics_pnl)}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

// 扫榜推荐（免费扫榜层）：点一个直接 decode
const BEH_ICON = { ADD: "📈", EXIT: "📉", STATIC: "⏸" };
const CALL_CN = { "ROOM LEFT": "还有空间", CHASED: "太迟了", "NO BASIS": "没依据" };
function Recommendations({ onPick }) {
  const { t, lang } = useLang();
  const [data, setData] = useState(null);
  useEffect(() => { fetch(`${API}/recommendations`).then((r) => r.json()).then(setData).catch(() => {}); }, []);
  const cands = (data && data.candidates) || [];
  if (!cands.length) return null;
  return (
    <div className="recs">
      <div className="recs-h">{t("值得看的聪明钱 ·")} <b>{t("政治盘专家")}</b>{t("（从热门政治盘反向找的共持大户 · 政治专长筛 · ∩月榜）")}<span className="recs-sub">{t("点一个直接 decode")}</span></div>
      <div className="recs-list">
        {cands.map((c, i) => {
          const pw = c.politics_win_rate;
          const pwTxt = pw != null ? (pw <= 1 ? Math.round(pw * 100) : Math.round(pw)) + "%" : null;
          return (
            <button className={`rec ${c.ai_pick ? "pick" : ""}`} key={i} onClick={() => onPick(c.wallet)}>
              <div className="rec-top">
                {c.ai_pick && <span className="rec-aibadge">{t("AI 精选")}</span>}
                <span className="rec-addr num">{abbrev(c.wallet)}</span>
                {c.cross_ref_579 && <span className="rec-cross">{t("∩月榜")}</span>}
                {c.tier && <span className="rec-tier">{c.tier}</span>}
                {c.h_score != null && <span className="rec-h num">H{Math.round(c.h_score)}</span>}
              </div>
              {c.politics_pnl != null && (
                <div className="rec-pol">{t("政治盘")} <b className="num">{money(c.politics_pnl)}</b>{pwTxt && <span> · {t("胜率")} {pwTxt}</span>}{c.politics_trades && <span> · {c.politics_trades} {t("注")}</span>}</div>
              )}
              <div className="rec-q">{c.market_question} <span className="rec-side">· {t("押")} {c.outcome}</span></div>
              {c.disagreement && (
                <div className="rec-disagree">{t("⚠ 聪明钱在此盘分歧（正反都有人押）")}
                  {c.disagreement_lean && <span className={c.disagreement_with_edge ? "with" : "against"}> · {t("我们独立倾向")} <b>{c.disagreement_lean}</b> → {t("这注")}{t(c.disagreement_with_edge ? "顺 edge" : "逆 edge")}</span>}
                </div>
              )}
              {c.consensus_count >= 2 && (
                <div className="rec-consensus">🤝 {c.consensus_count} {t("个政治专家同押此方向（弱信号 · 技能共识非盈亏 · 仍有羊群风险）")}</div>
              )}
              {c.source_market && <div className="rec-src">{t("↳ 从「")}{c.source_market}{t("」共持发现")}</div>}
              <div className="rec-beh">{BEH_ICON[c.behavior] || "·"} {t(c.behavior_fact) || c.behavior || "—"}</div>
              {c.ai_pick && (
                <div className="rec-verdict">
                  <span className={`rec-conf ${c.ai_confidence}`}>⑥ {t(CONF_CN[c.ai_confidence] || c.ai_confidence)} {t("信心")}</span>
                  {c.ai_follow_call && <span className="rec-call">{t(CALL_CN[c.ai_follow_call] || c.ai_follow_call)}</span>}
                  {c.ai_verdict && <span className="rec-verdict-txt">{t(c.ai_verdict)}</span>}
                </div>
              )}
            </button>
          );
        })}
      </div>
      <div className="recs-foot">{t("扫榜=值得一看，")}<b>{t("不是\"该跟\"")}</b>{t(" · 高盈利 ≠ 下一注好（过去≠未来）· 这注本身好不好由点开后的 ⑥ 判 ")}{data.as_of && `· ${t("截至")} ${data.as_of}`}{data.generated_at && ` · ${t("更新于")} ${new Date(data.generated_at * 1000).toLocaleString(lang === "en" ? "en-US" : "zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })}`}</div>
    </div>
  );
}

function BoardView() {
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
      const resp = await fetch(`${API}/dashboard?wallet=${encodeURIComponent(w)}${refresh ? "&refresh=1" : ""}`);
      const j = await resp.json();
      if (!resp.ok || j.error) setError({ reason: j.error || `HTTP ${resp.status}`, message: j.message || t("请求失败") });
      else setData(j);
    } catch (e) {
      setError({ reason: "NETWORK", message: t("无法连接后端服务，请稍后重试。") });
    } finally { setLoading(false); }
  }

  function refreshCurrent() {
    const w = wallet.trim() || (data && data.wallet);
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
        <button className="cmd-refresh" onClick={refreshCurrent} disabled={loading || !(wallet.trim() || (data && data.wallet))}
          title={t("绕过缓存重建这份看板（重新拉数据 + 重跑 AI，耗时且消耗 token）")}>↻</button>
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
  const { t } = useLang();
  if (!sc || sc.error) return null;
  const rate = sc.hit_rate_pct;
  const settledRows = (sc.rows || []).filter((r) => r.status !== "nobasis");
  const nbRows = (sc.rows || []).filter((r) => r.status === "nobasis");
  return (
    <div className="sc">
      <div className="sc-head">
        <div className="sc-title">{t("诚实记分牌 · 我的判断后来被现实证明对了多少")}</div>
        <div className="sc-sub">{t("从装上往后累积的真实 decode / 看板判断 → 盘结算后回来对账。与下方历史回测是两套独立机制。")}</div>
      </div>
      <div className="sc-nums">
        <div className="sc-num"><b className="num">{sc.tested}</b><span>{t("测了")}</span></div>
        <div className="sc-num"><b className="num">{sc.settled}</b><span>{t("已结算")}</span></div>
        <div className="sc-num"><b className="num up">{sc.direction_consistent}</b><span>{t("方向一致")}</span></div>
        <div className="sc-num big"><b className="num">{rate == null ? "—" : rate + "%"}</b><span>{t("命中率")}</span></div>
        <div className="sc-num"><b className="num">{sc.nobasis_total}</b><span>NO BASIS</span></div>
      </div>
      <div className="sc-discipline">{t("命中率 = ")}<b>{t("判断方向命中")}</b>{t("，不是跟单收益率 · NO BASIS 不计入命中率 · 顶上冷数字纯代码算，不经 AI")}</div>

      {sc.tested === 0 ? (
        <div className="sc-empty">{t("还没有记录 — 去解读台 / 统一看板跑几个钱包，判断就会存进档案；等这些盘在数据世界里真结算，这里才长出命中率。第一天空是正常的。")}</div>
      ) : (
        <div className="sc-rows">
          {settledRows.map((r, i) => {
            const st = SC_STATUS[r.status] || SC_STATUS.pending;
            return (
              <div className="sc-row" key={i}>
                <span className="sc-src">{t(SC_SOURCE[r.source] || r.source)}</span>
                <span className="sc-q">{r.market_question}</span>
                <span className="sc-call num">{t("判")} {t(FOLLOW_LABEL_CN[r.follow_call] || r.follow_call)} · {t("押")} {r.outcome}</span>
                <span className={`sc-status ${st.cls}`}>{t(st.txt)}{(r.status === "hit" || r.status === "miss") && r.winner ? ` · ${t("赢家")} ${r.winner}` : ""}</span>
              </div>
            );
          })}
        </div>
      )}

      {sc.nobasis_total > 0 && (
        <div className="sc-nobasis">
          <div className="sc-nobasis-h">{t("NO BASIS 单独区 ·")} {sc.nobasis_total} {t("个（不进命中率）· 其中事后看其实有清晰方向")} <b className="down">{sc.nobasis_clear_in_hindsight}</b> {t("个（当时过谨慎、错过）")}</div>
          {nbRows.map((r, i) => (
            <div className="sc-row nb" key={i}>
              <span className="sc-src">{t(SC_SOURCE[r.source] || r.source)}</span>
              <span className="sc-q">{r.market_question}</span>
              <span className="sc-call num">{t("押")} {r.outcome}</span>
              <span className="sc-status nb">{r.winner ? (r.winner === r.outcome ? t("事后有方向") : t("正确回避")) : t("待结算")}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function TrackRecordView() {
  const { t } = useLang();
  const [data, setData] = useState(null);
  const [sc, setSc] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    fetch(`${API}/backtest`).then((r) => r.json()).then(setData)
      .catch(() => setError(t("无法连接后端 /backtest")));
    fetch(`${API}/scorecard`).then((r) => r.json()).then(setSc).catch(() => {});
  }, []);

  const s = (data && data.summary) || {};
  const wrong = (s.total || 0) - (s.directional_correct || 0);
  return (
    <>
      <LiveScorecard sc={sc} />

      <div className="sc-divider">{t("↓ 历史回测（v2 已封板·静态零 token，与上方实时记分牌相互独立）")}</div>

      {error ? <div className="error"><div className="r">NETWORK</div><div>{error}</div></div>
       : !data ? <div className="stages"><div className="lead">LOADING TRACK RECORD…</div></div>
       : !data.cases || !data.cases.length ? <div className="method">{t("案例数据缺失（backtest/cases.json 未就位）")}</div>
       : (
        <>
          <div className="tr-hero">
            <div className="tr-hero-num num">
              <span className="up">{s.directional_correct}</span><span className="tr-unit"> {t("对")}</span>
              <span className="tr-slash"> / </span>
              <span className="down">{wrong}</span><span className="tr-unit"> {t("错")}</span>
            </div>
            <div className="tr-hero-txt">
              <div className="tr-hero-h">{t("AI 判断成绩单")}</div>
              <div className="tr-hero-sub">{s.total} {t("个已结算的真实政治盘 · 每个都在结算前重放 AI 当时的判断，跟真实结果对账")}</div>
            </div>
          </div>

          <div className="bt-list">
            {data.cases.map((c, i) => <CaseRow key={i} c={c} />)}
          </div>

          {data.lift && <LiftSummary lift={data.lift} />}

          <div className="foot">{t("案例来自历史回测：结算前重放 decoder、与真实结算对照 · 静态、零 token")}</div>
        </>
      )}
    </>
  );
}

function CaseRow({ c }) {
  const { t } = useLang();
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const [h, setH] = useState(0);
  useEffect(() => { setH(open && ref.current ? ref.current.scrollHeight : 0); }, [open]);

  const verdict = t(CALL_PLAIN[c.t1.call] || c.t1.call);
  const concl = c.ai_correct ? (c.hero ? t("✓ AI 帮你躲过这笔亏损") : t("✓ AI 判断正确")) : t("✗ AI 失手");
  const tps = [["T-7", c.t7], ["T-1", c.t1]];

  return (
    <div className={`bt-item ${open ? "open" : ""} ${c.hero ? "hero" : ""}`}>
      <div className="bt-row" onClick={() => setOpen(!open)}>
        <div className="bt-left">
          <div className="bt-q">{c.hero && <span className="hero-star">★ </span>}{c.market}</div>
          <div className="bt-tags">
            <span className={`stance ${CALL_CLS[c.t1.call] || "gray"}`}>{t("AI 当时判")} <b>{verdict}</b></span>
            <span className="resolved big">{t("真实：")}{c.bet_won ? t("钱包赢了") : t("钱包赌输了")}</span>
          </div>
        </div>
        <div className="bt-right">
          <span className={c.ai_correct ? "verd hit" : "verd miss"}>{c.ai_correct ? "✓" : "✗"}</span>
          <span className={`chev ${open ? "up" : ""}`}>›</span>
        </div>
      </div>

      <div className="bt-drawer" style={{ height: h }}>
        <div className="bt-drawer-inner" ref={ref}>
          <div className="case-concl">{concl} · {t("市场结算")} {c.resolved}（{c.resolved_date}）</div>
          <div className="case-take">{t(c.takeaway)}</div>

          <div className="case-evo">
            {tps.map(([lab, pt], i) => (
              <span className="evo-step" key={lab}>
                <span className="evo-lab">{lab}</span>
                <span className={`mini-follow ${CALL_CLS[pt.call] || "gray"}`}>{t(CALL_PLAIN[pt.call] || pt.call)}</span>
                {i === 0 && <span className="evo-arrow">→</span>}
              </span>
            ))}
          </div>

          {tps.map(([lab, pt]) => (
            <div className="case-tp" key={lab}>
              <div className="case-tp-h">{lab} · {pt.date} · {t("信心")} {CONF_LABEL[pt.conf] || pt.conf}</div>
              <ul className="case-cat">{pt.catalysts.map((cat, j) => <li key={j}>{t(cat)}</li>)}</ul>
              <div className="case-reason"><span className="case-reason-lab">{t("AI 当时推理")}<ZhNote text={pt.reasoning} /></span>{t(pt.reasoning)}</div>
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
  const { t } = useLang();
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
        {t("跟着 AI 挑的注,比无脑全抄聪明钱,")}
        <span className="l2-accent">{t("方向准了")} {sign(f.lift)}</span>
      </div>

      {/* 第二层 · 双格终端窗 + 多巴胺大数字 */}
      <div className="l2-term">
        <div className="l2-cell">
          <div className="l2-big num">{sign(f.lift)}</div>
          <div className="l2-sub">
            {t("全部盘口（")}{f.n}{t("个）:跟AI挑 vs 全抄,方向胜率")} <b>{pct(f.go_wr)}</b> vs {pct(f.base_wr)}
          </div>
        </div>
        <div className="l2-cell">
          <div className="l2-big num">{sign(eb.lift)}</div>
          <div className="l2-sub">
            {t("真正难判的盘（")}{eb.n}{t("个）:跟AI挑 vs 全抄,方向胜率")} <b>{pct(eb.go_wr)}</b> vs {pct(eb.base_wr)}
          </div>
        </div>
      </div>

      {/* 第三层 · 诚实说明（承上启下，引向含金量更高的 +13%）*/}
      <div className="l2-honest">
        {t("⚠️ 诚实说明:这")} {f.n} {t("个盘里")} {pct(nm.share)} {t("是接近已定局的“送分题”,AI 在这些上面跟对不算本事。因此真正能证明模型实力的是右边难盘的")} {sign(eb.lift)}。
      </div>

      {/* 第四层 · 量化审计日志（默认折叠）*/}
      <div className="l2-audit">
        <div className="l2-audit-bar" onClick={() => setOpen(!open)}>
          <span className="l2-audit-tag">[SYSTEM AUDIT]</span> {t("展开底层统计与方法论验证")}
          <span className={`l2-arrow ${open ? "on" : ""}`}>→</span>
        </div>
        <div className="l2-audit-body" style={{ height: h }}>
          <div ref={ref} className="l2-audit-inner">
            {AUDIT_LOG.map((a, i) => (
              <div className="audit-block" key={i}>
                <div className="audit-h"><span className="audit-tag">{a.tag}</span> {t(a.title)}</div>
                <div className="audit-text">{t(a.body)}</div>
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
