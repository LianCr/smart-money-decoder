import { RollingDigit } from "./RollingDigit.jsx";

export function RollingNumber({ value }) {
  return <span className="roll">{String(value).split("").map((c, i) => <RollingDigit key={i} d={+c} />)}</span>;
}
