// 极简 i18n：中文原文即 key。zh = 原样返回；en = 三层查表（UI 词典 → AI 精确词典 → 模式引擎），
// 全部 miss 才回退中文（绝不炸）。AI 词典由 tools/build_ai_en.py 从缓存离线生成（零 token）；
// 模式引擎翻代码模板串（带数字，刷新出新数据也能翻）。未来新 AI 产出查不到 → 回退中文 + ZhNote 诚实标注。
import { createContext, useContext, useState } from "react";
import EN from "./locales/en.js";
import AI_MAP from "./locales/ai_en.js";
import { patternTranslate } from "./locales/ai_patterns.js";

const CJK_RE = /[一-鿿]/;
const toEN = (s) => EN[s] ?? AI_MAP.get(s) ?? patternTranslate(s) ?? s;

const LangContext = createContext({ lang: "zh", t: (s) => s, setLang: () => {} });

export function LangProvider({ children }) {
  const [lang, setLangState] = useState(() => {
    try { return localStorage.getItem("smd_lang") || "zh"; } catch { return "zh"; }
  });
  const t = (s) => {
    if (lang !== "en" || s == null) return s;
    return typeof s === "string" ? toEN(s) : s;
  };
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

// EN 模式下 AI 内容的诚实标注：只有当该内容**确实还翻不出来**（新产出、词典未收录）时才显示。
// 传 text = 该区块的原文；有译文 → 不标（内容已是英文）。不传 text → 恒不显示。
export function ZhNote({ text }) {
  const { lang } = useLang();
  if (lang !== "en" || text == null) return null;
  const out = typeof text === "string" ? toEN(text) : String(text);
  if (!CJK_RE.test(out)) return null;
  return <span className="zh-note" title="This AI-generated content is newer than the offline translation layer — shown in original Chinese rather than machine-mangled.">AI output · 中文</span>;
}
