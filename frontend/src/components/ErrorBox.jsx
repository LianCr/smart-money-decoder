import { useLang } from "../i18n.jsx";
import { API } from "../utils/config.js";

// 常见后端错误 reason → EN 文案（后端 message 是中文；zh 模式直接用后端原文，en 模式查这里、查不到回退原文）
const REASON_EN = {
  INVALID_ADDRESS: "Invalid wallet address — expected a 0x… address (42 chars).",
  NO_POSITIONS: "This wallet has no open positions.",
  NO_OPEN_POSITIONS: "This wallet has no open positions.",
  NO_POLITICAL_POSITIONS: "This wallet has no political-market positions — we only analyze politics markets.",
  ALL_BELOW_MIN_VALUE: "All positions are below the minimum size threshold — too small to analyze meaningfully.",
  DASHBOARD_PIPELINE_FAILED: "The analysis pipeline failed upstream (data source or AI gateway). Please retry later.",
  DASHBOARD_BUILD_IN_PROGRESS: "This wallet dashboard is already being built. Waiting for the result…",
  BRIEFING_PIPELINE_FAILED: "The briefing pipeline failed upstream (data source or AI gateway). Please retry later.",
  MARKET_CONTEXT_FAILED: "Market-context synthesis failed upstream. Please retry later.",
  RATE_LIMITED: "Upstream API rate limit hit — please wait a moment and retry.",
  NETWORK: "Cannot reach the backend — please retry later.",
};

export function ErrorBox({ error }) {
  const { lang } = useLang();
  if (!error) return null;
  const msg = lang === "en" ? (REASON_EN[error.reason] || error.message) : error.message;
  return (
    <div className="error">
      <div className="r">{error.reason}</div>
      <div>{msg}</div>
    </div>
  );
}
