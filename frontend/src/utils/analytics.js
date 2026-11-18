// 来源统计（2026-10-30）：sendBeacon 打后端 POST /visit，一行日志进 Render Logs。
// 零第三方、零 cookie；?src= 记一次存 sessionStorage，本次会话后续事件都带上。
import { API } from "./config.js";

const SRC_KEY = "smd_src";

function source() {
  try {
    const fromUrl = new URLSearchParams(window.location.search).get("src");
    if (fromUrl) sessionStorage.setItem(SRC_KEY, fromUrl.slice(0, 40));
    return sessionStorage.getItem(SRC_KEY) || "";
  } catch {
    return "";
  }
}

export function track(event, detail = "") {
  try {
    const body = JSON.stringify({
      event,
      detail: String(detail).slice(0, 80),
      src: source(),
      ref: document.referrer || "",
      path: window.location.pathname + window.location.search,
      lang: (() => { try { return localStorage.getItem("smd_lang") || ""; } catch { return ""; } })(),
    });
    const url = `${API}/visit`;
    if (navigator.sendBeacon) navigator.sendBeacon(url, new Blob([body], { type: "application/json" }));
    else fetch(url, { method: "POST", body, headers: { "Content-Type": "application/json" }, keepalive: true });
  } catch {
    /* 统计永不影响主流程 */
  }
}
