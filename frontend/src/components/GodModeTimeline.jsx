import { useState } from "react";
import { scaleLinear, scaleTime } from "d3-scale";
import { line as d3line, area as d3area, curveMonotoneX } from "d3-shape";
import { extent } from "d3-array";
import { useLang } from "../i18n.jsx";
import { price } from "../utils/format.jsx";
import { REACT_SYM } from "../utils/labels.js";
import { RollingNumber } from "./RollingNumber.jsx";

// 上帝视角时间轴：价格曲线 × 建仓点 × 新闻发光节点 × 剩余空间（D3 算数学，React 渲 SVG）
const GMT_W = 760, GMT_H = 340, GMT_M = { t: 18, r: 38, b: 28, l: 14 };

function _pdate(s) { return new Date(s + "T00:00:00Z"); }

function gmtReact(rx, t = (s) => s) {
  if (!rx || !rx.available) return { txt: t("市场反应不可知"), cls: "rx-na" };
  const m = REACT_SYM[rx.kind] || REACT_SYM.weak;
  return { txt: `${m.sym}${t(m.txt)} ${rx.move_pct > 0 ? "+" : ""}${rx.move_pct}%`, cls: m.cls };
}

function fmtMD(dt) { return `${dt.getUTCMonth() + 1}/${dt.getUTCDate()}`; }

export function GodModeTimeline({ d }) {
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
