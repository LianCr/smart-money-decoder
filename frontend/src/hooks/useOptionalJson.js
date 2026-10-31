import { useEffect, useState } from "react";

// 可选数据源：GET 一个 JSON 端点，任何失败（网络错 / 非 2xx / 解析失败）都静默得到 null。
// 给"拿不到就整块不渲染"的附加面板用（选举横幅、科技移民盘）——绝不抛错、绝不出错误态。
export function useOptionalJson(url) {
  const [data, setData] = useState(null);
  useEffect(() => {
    let alive = true;
    fetch(url)
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => { if (alive) setData(j && typeof j === "object" ? j : null); })
      .catch(() => { if (alive) setData(null); });
    return () => { alive = false; };
  }, [url]);
  return data;
}
