// 极简 i18n：中文原文即 key。zh = 原样返回；en = 查 locales/en.js，查不到回退中文（绝不炸）。
// AI 生成的内容（综述/推理/催化剂 reason 等）不翻——EN 模式下由使用处加 zh 小标，诚实标注。
import { createContext, useContext, useState } from "react";
import EN from "./locales/en.js";

const LangContext = createContext({ lang: "zh", t: (s) => s, setLang: () => {} });

export function LangProvider({ children }) {
  const [lang, setLangState] = useState(() => {
    try { return localStorage.getItem("smd_lang") || "zh"; } catch { return "zh"; }
  });
  const t = (s) => (lang === "en" ? (EN[s] ?? s) : s);
  const setLang = (l) => {
    setLangState(l);
    try { localStorage.setItem("smd_lang", l); } catch { /* 隐身模式等 */ }
  };
  return <LangContext.Provider value={{ lang, t, setLang }}>{children}</LangContext.Provider>;
}

export function useLang() {
  return useContext(LangContext);
}

// 右上角语言胶囊：中 | EN
export function LangToggle() {
  const { lang, setLang } = useLang();
  return (
    <div className="lang-pill" role="group" aria-label="Language">
      <button className={lang === "zh" ? "on" : ""} onClick={() => setLang("zh")}>中</button>
      <span className="lang-sep">|</span>
      <button className={lang === "en" ? "on" : ""} onClick={() => setLang("en")}>EN</button>
    </div>
  );
}

// EN 模式下给"AI 中文原文"内容区加的小标（诚实标注：AI 输出是中文、未经翻译）
export function ZhNote() {
  const { lang } = useLang();
  if (lang !== "en") return null;
  return <span className="zh-note" title="AI-generated analysis is produced in Chinese and shown as-is (translating it would cost tokens and risk drift).">AI output · 中文</span>;
}
