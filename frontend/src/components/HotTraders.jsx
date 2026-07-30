import { useState, useEffect } from "react";
import { useLang } from "../i18n.jsx";
import { API } from "../utils/config.js";
import { money, abbrev } from "../utils/format.jsx";

// Polymarket 价格滚动栏（第三方 widget：先渲 div、再注入脚本，脚本按 id 找 div 渲染）
// 入口滚动条：本周政治盘热门交易者（hot_traders.py：579 7d 宇宙 × 581 政治 7d 盈亏）。点一个直接解码。
export function HotTraders({ onPick }) {
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
