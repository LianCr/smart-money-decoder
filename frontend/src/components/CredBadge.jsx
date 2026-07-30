import { useLang } from "../i18n.jsx";
import { money, abbrev, fmtPnlCompact } from "../utils/format.jsx";
import { Avatar } from "./Avatar.jsx";
import { MiniSpark } from "./MiniSpark.jsx";

// 身份徽章（资格审查降级成角落名片，不再霸占首屏）
export function CredBadge({ profile, rk, pnlHistory }) {
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
