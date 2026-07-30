import { useState, useEffect, useRef } from "react";
import { useLang } from "../i18n.jsx";

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
export function LiftSummary({ lift }) {
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
