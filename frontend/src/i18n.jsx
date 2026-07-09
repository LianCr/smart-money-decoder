// 极简 i18n：中文原文即 key。zh = 原样返回；en = 四层查表（UI 词典 → 运行时词典 → AI 离线词典 → 模式引擎），
// 全部 miss 才回退中文（绝不炸）。
// 运行时词典（2026-07-08 新增，实时世界的正解）：后端构建看板/简报/推荐时把 AI 产出的中文
// 批量翻好、随 payload 下发 i18n_en 映射，前端 fetch 后 registerAiTranslations() 注册进来——
// 所有既有 t() 渲染点零改动自动翻译。离线词典 ai_en.js 降级为历史兜底（6-25 冻结世界的内容）；
// 极端情况（翻译调用失败）才回退中文 + ZhNote 诚实标注。
import { createContext, useContext, useState } from "react";
import EN from "./locales/en.js";
import AI_MAP from "./locales/ai_en.js";
import { patternTranslate } from "./locales/ai_patterns.js";

const CJK_RE = /[一-鿿]/;
const RUNTIME_AI = new Map();          // 后端随 payload 下发的 {中文: 英文}，会话内累积
export function registerAiTranslations(map) {
  if (!map || typeof map !== "object") return;
  for (const [zh, en] of Object.entries(map)) {
    if (typeof zh === "string" && typeof en === "string" && en) RUNTIME_AI.set(zh, en);
  }
}
const toEN = (s) => EN[s] ?? RUNTIME_AI.get(s) ?? AI_MAP.get(s) ?? patternTranslate(s) ?? s;

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
