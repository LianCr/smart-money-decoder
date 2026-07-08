// AI/动态内容的"模式翻译"层：代码生成的带数字模板串（数字会随数据变化，
// 精确词典必然 miss）→ 用正则捕获数字、翻译框架。刷新出新数据也能翻。
// 🔴 只翻框架、数字原样透传（数字归代码的红线在翻译层同样成立）。
const HESI = { "高(市场自己没拿定)": "high (market itself undecided)", "低(共识已稳)": "low (consensus settled)", "中": "medium" };

export const AI_PATTERNS = [
  [/^还有约(\d+(?:\.\d+)?)天$/, (m) => `≈${m[1]} days left`],
  [/^距结算 (\d+) 天$/, (m) => `${m[1]} days to resolution`],
  [/^(Yes|No) 价格变动 ([+-]\d+(?:\.\d+)?)%（(\d+)% → (\d+)%）$/,
    (m) => `${m[1]} price moved ${m[2]}% (${m[3]}% → ${m[4]}%)`],
  [/^近 48h 仅 (\d+) 买 \/ (\d+) 卖，无显著动作（沉闷持仓）$/,
    (m) => `Last 48h: only ${m[1]} buys / ${m[2]} sells — no significant move (quiet holding)`],
  [/^过去 3h (\d+) 笔 BUY\(\$([\d,]+)\) \/ 24h (\d+) 笔 BUY\(\$([\d,]+)\)，长期持仓刚被新一轮加仓激活$/,
    (m) => `Past 3h: ${m[1]} BUYs ($${m[2]}) / 24h: ${m[3]} BUYs ($${m[4]}) — long-held position just re-activated by fresh adds`],
  [/^市场自身犹豫度=(高\(市场自己没拿定\)|低\(共识已稳\)|中)：近(\d+)日已实现波动 ([\d.]+)，收盘 (\[.*\])$/,
    (m) => `Market's own hesitation = ${HESI[m[1]] || m[1]}: realized vol ${m[3]} over last ${m[2]} days, closes ${m[4]}`],
  [/^价格可信度=(HIGH|MED|LOW)：流动性 (.+?)\(([\d.]+)百分位\) · 头部集中 top1=([\d.]+)% top10=([\d.]+)% · 近7天 (\d+) 人参与 · 成交量 (.+)$/,
    (m) => `Price credibility = ${m[1]}: liquidity ${m[2]} (${m[3]} pctile) · concentration top1=${m[4]}% top10=${m[5]}% · ${m[6]} traders in 7d · volume ${m[7]}`],
  [/^\[入场后\] ([\s\S]*)$/, (m) => `[post-entry] ${m[1]}`],
  [/^\[入场前\] ([\s\S]*)$/, (m) => `[pre-entry] ${m[1]}`],
];

export function patternTranslate(s) {
  for (const [re, fn] of AI_PATTERNS) {
    const m = s.match(re);
    if (m) return fn(m);
  }
  return null;
}
