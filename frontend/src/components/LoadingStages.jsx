import { useState, useEffect, useRef } from "react";
import { useLang } from "../i18n.jsx";
import { STAGES } from "../utils/config.js";

// 流水线加载：单请求在飞，前端按节奏 currentStep 逐个点亮，居中、与首页同语言。
// 渐进式逻辑：i<step=已完成(暗青·✓静止) / i===step=进行中(亮青·脉冲) / i>step=未开始(暗灰静止)。
export function LoadingStages({ stages = STAGES, sub = "定位 → 追溯 → 检索 → 判断", note }) {
  const { t } = useLang();
  const [step, setStep] = useState(0);
  const [secs, setSecs] = useState(0);          // 真实已用时长（诚实计时，不装进度）
  const timer = useRef();
  useEffect(() => {
    const t0 = Date.now();
    timer.current = setInterval(() => {
      setSecs(Math.floor((Date.now() - t0) / 1000));
      setStep((s) => {
        const target = Math.min(Math.floor((Date.now() - t0) / 3500), stages.length - 1);
        return Math.max(s, target);              // 卡在最后一步，绝不全打勾
      });
    }, 1000);
    return () => clearInterval(timer.current);
  }, [stages.length]);
  const last = stages.length - 1;

  return (
    <div className="pipe">
      <div className="pipe-lead">
        {t("AI 推演中")} <span className="pipe-sub">· {t(sub)}</span>
        <span className="pipe-timer num">{secs}s</span>
      </div>
      {note && secs >= 3 && <div className="pipe-note">{note}</div>}
      <div className="pipe-list">
        <span className="pipe-rail" />
        <span className="pipe-fill" style={{ height: `calc((100% - 28px) * ${step} / ${last})` }} />
        {stages.map((s, i) => {
          const state = i < step ? "done" : i === step ? "active" : "todo";
          return (
            <div className={`pstep ${state}`} key={i}>
              <span className="pstep-node" />
              <span className="pstep-label">{t(s)}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
