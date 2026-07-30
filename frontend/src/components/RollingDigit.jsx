import { useState, useEffect, useRef } from "react";

// 滚动数字（odometer）：连续 reel（0-9 重复 8 组），用**累计绝对位置**滚动，按最短方向连续过渡——
// 9→0 向前滚(不再倒退一圈)，scrub 顺滑。挂载从 0 滚到目标。零依赖。
const ROLL_REEL = 80, ROLL_MID = 40;

export function RollingDigit({ d }) {
  const posRef = useRef(ROLL_MID);          // 挂载从位置 40(显示 0)开始
  const [pos, setPos] = useState(ROLL_MID);
  useEffect(() => {
    const cur = posRef.current;
    const curMod = ((cur % 10) + 10) % 10;
    let delta = d - curMod;                  // 最短连续方向：±5 内直接走，超过则反向更近
    if (delta > 5) delta -= 10;
    else if (delta < -5) delta += 10;
    const next = cur + delta;
    posRef.current = next;
    setPos(next);
  }, [d]);
  return (
    <span className="roll-d"><span className="roll-col" style={{ transform: `translateY(${-pos}em)` }}>
      {Array.from({ length: ROLL_REEL }, (_, n) => <span key={n} className="roll-n">{n % 10}</span>)}
    </span></span>
  );
}
