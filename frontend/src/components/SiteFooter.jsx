import { useLang } from "../i18n.jsx";
import { money } from "../utils/format.jsx";

// 全局 footer：品牌 · 链接 · 署名（所有 tab 共用，随语言切换）
export function SiteFooter() {
  const { t } = useLang();
  const year = new Date().getFullYear();
  return (
    <footer className="site-footer">
      <div className="sf-inner">
        <div className="sf-brand">
          <span className="sf-mark"><span className="dot" />SMART MONEY DECODER</span>
          <span className="sf-tag">{t("解码 Polymarket 聪明钱的政治押注 · 只读公开数据 · 非投资建议")}</span>
        </div>
        <nav className="sf-links">
          <a href="https://github.com/LianCr/smart-money-decoder" target="_blank" rel="noreferrer">GitHub</a>
          <span className="sf-sep">/</span>
          <a href="mailto:liancr307@gmail.com">liancr307@gmail.com</a>
          <span className="sf-sep">/</span>
          <a href="https://polymarket.com/leaderboard/politics/all/profit" target="_blank" rel="noreferrer">Polymarket</a>
        </nav>
        <div className="sf-meta num">
          © {year} Chunren Lian · {t("数字归代码，AI 只做解读")}
        </div>
      </div>
    </footer>
  );
}
