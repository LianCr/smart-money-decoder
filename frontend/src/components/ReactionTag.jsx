import { useLang } from "../i18n.jsx";
import { REACT_SYM } from "../utils/labels.js";

export function ReactionTag({ r }) {
  const { t } = useLang();
  if (!r || !r.available) return <span className="rx rx-na">{t("市场反应不可知")}</span>;
  const m = REACT_SYM[r.kind] || REACT_SYM.weak;
  const mv = `${r.move_pct > 0 ? "+" : ""}${r.move_pct}%`;
  return <span className={`rx ${m.cls}`}>{m.sym}{t(m.txt)} {mv}{r.thin ? ` ·${t("薄量")}` : ""}</span>;
}
