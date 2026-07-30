import { useState, useEffect, useRef } from "react";

export function Fold({ title, sub, children }) {
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
