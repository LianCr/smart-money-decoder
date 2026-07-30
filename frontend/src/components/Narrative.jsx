import { renderInline } from "../utils/format.jsx";

export function Narrative({ text }) {
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
