// hooks/useDashboard.js — 看板轮询的显式状态机（P2-22，替掉 BoardView 里改写入参的隐式循环）
//
// 状态 → 用户看到什么：
//   idle       未选钱包            → 首页入口（推荐流 + demo 列表）
//   loading    首次构建、手上无板   → LoadingStages（约 1-3 分钟文案）
//   polling    202 且无旧板可垫    → LoadingStages + "同一钱包正在构建中（复用、不重复烧）"
//   ready      拿到板             → 看板（notice 可能带旧板/刷新失败横幅）
//   refreshing 用户↻ / 板带 refresh_in_progress → 🔴 旧板原样保留 + "刷新中"徽章，后台继续轮询
//   error      真错误且无板可展示   → ErrorBox
//
// 转移规则（与后端契约逐条对齐）：
//   - 轮询预算 = 墙钟 POLL_BUDGET_MS（=后端单飞锁 TTL 600s，core/dashboard_jobs.py）——
//     替掉旧的 80×3s=240s：后端 240-600s 区间还在正常构建时，旧实现会给用户看"失败"。
//   - 202 按 retry_after 退避；429 在预算内同样按 retry_after 退避继续（限流不是失败）。
//   - refresh=1 只在第一发带上；后续轮询全部裸查（绝不触发第二次强制重建）。
//   - 🔴 真错误/超时时：有旧板一律 留板+notice、绝不进 error 态；预算耗尽的措辞是
//     "等待超时"而非"失败"（后端可能仍在构建，稍后重试会命中缓存）。
import { useEffect, useRef, useState } from "react";
import { registerAiTranslations } from "../i18n.jsx";
import { API, POLL_BUDGET_MS } from "../utils/config.js";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export function useDashboard() {
  const [status, setStatus] = useState("idle");   // idle|loading|polling|ready|refreshing|error
  const [board, setBoard] = useState(null);
  const [error, setError] = useState(null);       // {reason,message}，仅无板可展示时
  const [notice, setNotice] = useState(null);     // {kind,message}，有板时的非致命横幅
  const boardRef = useRef(null);                  // drive 循环里读最新板，避开闭包过期
  const seqRef = useRef(0);                       // 竞态/卸载防护：序号变了就停手

  useEffect(() => () => { seqRef.current += 1; }, []);   // 卸载：作废在飞的循环

  const show = (b) => { boardRef.current = b; setBoard(b); };

  async function drive(wallet, wantRefresh) {
    const seq = ++seqRef.current;
    const alive = () => seqRef.current === seq;
    const startedAt = Date.now();
    let sendRefresh = wantRefresh;

    // 入口态：刷新且有旧板 → refreshing（板不动）；否则 loading（无板可垫）
    if (wantRefresh && boardRef.current) setStatus("refreshing");
    else { show(null); setStatus("loading"); }
    setError(null); setNotice(null);

    try {
      while (Date.now() - startedAt < POLL_BUDGET_MS) {
        const resp = await fetch(`${API}/dashboard?wallet=${encodeURIComponent(wallet)}${sendRefresh ? "&refresh=1" : ""}`);
        const j = await resp.json().catch(() => ({}));
        if (!alive()) return;
        sendRefresh = false;   // refresh=1 只发第一枪

        if (resp.status === 202 && j.error === "DASHBOARD_BUILD_IN_PROGRESS") {
          setStatus(boardRef.current ? "refreshing" : "polling");   // 构建中≠失败
          await sleep((j.retry_after || 3) * 1000);
          continue;
        }
        if (resp.status === 429) {
          setStatus(boardRef.current ? "refreshing" : "polling");   // 限流≠失败，按后端节奏退避
          await sleep((j.retry_after || 30) * 1000);
          continue;
        }
        if (resp.ok && !j.error) {
          registerAiTranslations(j.i18n_en);
          if (j.refresh_in_progress) {
            // 占位旧板（自己或别的访客在重建）：展示它 + 保持 refreshing，后台等真板
            show(j);
            setStatus("refreshing");
            await sleep(3000);
            continue;
          }
          show(j);
          setNotice(j.refresh_error ? { kind: "refresh_error", message: j.refresh_error } : null);
          setStatus("ready");
          return;
        }
        // 真错误（400/404/502）：有旧板留板+横幅，无板才进 error 态
        const reason = j.error || `HTTP ${resp.status}`;
        const message = j.message || "请求失败";
        if (boardRef.current) {
          setNotice({ kind: "refresh_failed", message: `${reason}: ${message}` });
          setStatus("ready");
        } else {
          setError({ reason, message });
          setStatus("error");
        }
        return;
      }
      // 预算耗尽（=后端单飞 TTL）：成败未知——诚实措辞，绝不说"失败"
      if (!alive()) return;
      if (boardRef.current) {
        setNotice({ kind: "timeout", message: "刷新等待超时（>10 分钟）；仍显示当前看板，稍后重试通常会直接命中新缓存。" });
        setStatus("ready");
      } else {
        setError({ reason: "BUILD_TIMEOUT",
                   message: "构建等待已超过后端上限（10 分钟）——后端可能仍在继续，稍后重试通常会秒回缓存结果。" });
        setStatus("error");
      }
    } catch (e) {
      if (!alive()) return;
      if (boardRef.current) {
        setNotice({ kind: "network", message: "网络中断；仍显示当前看板，稍后重试。" });
        setStatus("ready");
      } else {
        setError({ reason: "NETWORK", message: "无法连接后端服务，请稍后重试。" });
        setStatus("error");
      }
    }
  }

  return {
    status, board, error, notice,
    busy: status === "loading" || status === "polling" || status === "refreshing",
    load: (wallet) => drive(wallet, false),
    refresh: (wallet) => drive(wallet, true),
    reset: () => { seqRef.current += 1; show(null); setError(null); setNotice(null); setStatus("idle"); },
  };
}
