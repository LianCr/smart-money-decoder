"""
fetcher/markets.py — 市场反向找大户（扫榜推荐"正解源"原语）

🔴 为什么不是"列热门政治盘再找大户"：实测**没有任何端点能按成交量列政治盘**——
  574 列市场但记录里无 volume 字段、无活跃度排序（2000+ 未结算盘里热门盘是针）；
  575 Market Insights 必须传 condition_id（按盘查、不能列）；556 全局流被 HFT 微盘淹没（btc-updown-5m 单盘 686 笔）。
  唯一可靠原语 = 556 按 cid 聚合大户。所以发现走"种子扩展"：
  已知政治钱包 → 它的热门政治顶仓盘 → 共持大户。实测某热门盘 top15 共持人 15/15 是政治专家，良率≈100%。

本模块只放反向原语；"种子→盘→大户→质量门"的编排在 recommend.py。
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from core.config import BRIEFING_AS_OF
from fetcher.heisenberg import AGENTS, HeisenbergError, call, results


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def get_market_holders(cid, as_of=BRIEFING_AS_OF, top_n=10, window_days=60):
    """某盘当前净持仓最大的大户 → [(wallet, net_value), ...]（556 按 cid 全量、proxy_wallet=ALL、聚合净买入额）。
    net = Σ(BUY size×price) − Σ(SELL size×price)；只留净>0（仍持有的多头侧）。空盘/已清仓自然返空。"""
    if not (cid and str(cid).startswith("0x")):
        return []
    end = datetime.strptime(as_of, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    start = end - timedelta(days=window_days)
    try:
        ts = results(call(AGENTS["trades"][0],
                          {"proxy_wallet": "ALL", "condition_id": cid,
                           "start_time": str(int(start.timestamp())),
                           "end_time": str(int(end.timestamp()))}))
    except HeisenbergError:
        return []
    net = defaultdict(float)
    for t in ts:
        w = str(t.get("proxy_wallet", "")).lower()
        if not w.startswith("0x"):
            continue
        v = (_f(t.get("size")) or 0) * (_f(t.get("price")) or 0)
        net[w] += v if str(t.get("side", "")).upper() == "BUY" else -v
    return sorted([(w, v) for w, v in net.items() if v > 0], key=lambda kv: -kv[1])[:top_n]
