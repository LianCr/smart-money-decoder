import { useLang } from "../i18n.jsx";
import { API } from "../utils/config.js";
import { useOptionalJson } from "../hooks/useOptionalJson.js";

// ── SQL 拆解面板：读 GET /analytics（analytics/views.sql 的视图，后端每次从档案重建内存库）──
// 与上方记分牌同一口径（测试断言 SQL 汇总 == compute_scorecard），这里只多给两个切面。
// 拿不到就整块不渲染：附加面板，绝不把战绩页拖成错误态。
function Table({ title, keyLabel, rows, keyField }) {
  const { t } = useLang();
  if (!rows || !rows.length) return null;
  return (
    <div className="sqlb-block">
      <div className="sqlb-h">{t(title)}</div>
      <table className="sqlb-table">
        <thead>
          <tr>
            <th scope="col">{t(keyLabel)}</th>
            <th scope="col">{t("判断数")}</th>
            <th scope="col">{t("已结算(背书)")}</th>
            <th scope="col">{t("命中")}</th>
            <th scope="col">{t("命中率")}</th>
            <th scope="col">{t("待结算")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r[keyField]}>
              <th scope="row">{r[keyField]}</th>
              <td className="num">{r.judgments}</td>
              <td className="num">{r.settled_endorsed}</td>
              <td className="num">{r.hits}</td>
              <td className="num">{r.hit_rate_pct == null ? "—" : `${r.hit_rate_pct}%`}</td>
              <td className="num">{r.pending}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function SqlBreakdown() {
  const { t } = useLang();
  const a = useOptionalJson(`${API}/analytics`);
  const v = a && a.views;
  if (!v || !v.v_scorecard_summary || !v.v_scorecard_summary.length) return null;
  if (!v.v_scorecard_summary[0].tested) return null;
  return (
    <div className="sc sqlb">
      <div className="sc-head">
        <div className="sc-title">{t("SQL 拆解 · 按信心档和判断类型")}</div>
        <div className="sc-sub">{t("同一份判断档案载入关系表，由 SQL 视图计算；口径与上方记分牌一致（测试逐项比对）。样本小时命中率不说明问题。")}</div>
      </div>
      <Table title="按信心档" keyLabel="信心" rows={v.v_hit_rate_by_confidence} keyField="confidence" />
      <Table title="按判断类型" keyLabel="判断" rows={v.v_hit_rate_by_follow_call} keyField="follow_call" />
      <div className="sc-discipline">
        {t("数据源")}: <code>GET /analytics</code> · <code>analytics/views.sql</code>
      </div>
    </div>
  );
}
