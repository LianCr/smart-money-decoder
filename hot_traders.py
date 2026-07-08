"""
hot_traders.py — 入口页"本周政治盘热门交易者"滚动条数据（免费、无 LLM）。

🔴 为什么不是直接拉 Polymarket politics/weekly/profit 榜：
  没有"政治分类周榜"端点——579 官方周榜**无 category 参数**（是全品类、且只回地址无昵称）。
  故重建：579 7d 取本周最活跃/最赚的"宇宙" → 581 window_days=7 拿每人**政治盘 7 天净盈亏**（按子类求和）→ 政治盈利 top N。
  诚实边界：① 只有地址没昵称（API 不给）；② 宇宙=全品类周榜 top，纯小额政治玩家若不在其中会漏（热门条要的是体量，可接受），非该页 1:1 镜像。

跑法：`.venv/bin/python -u hot_traders.py`（~几分钟、纯免费 key、0 老师 token）。前端 /hot-traders 直读 .data/hot_traders.json。
"""
import json
import time
from pathlib import Path

from fetcher.heisenberg import call, results, AGENTS, HeisenbergError
from fetcher.positions import get_top_political_position_hz
from fetcher.markets import get_market_holders
from recommend import SEEDS

from core.config import BRIEFING_AS_OF as AS_OF
OUT = Path(".data/hot_traders.json")


def _retry(fn, *a, **k):
    for i in range(4):
        try:
            return fn(*a, **k)
        except HeisenbergError as e:
            if "429" in str(e):
                time.sleep(3 * (i + 1))
                continue
            return None
        except Exception:
            return None
    return None


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _politics_7d(wallet):
    """581 window_days=7 → 该钱包**政治盘 7 天**净盈亏(求和所有政治子类) + 注数/胜率。无政治活动→None。"""
    r = _retry(lambda: results(call(AGENTS["wallet360"][0],
               {"proxy_wallet": wallet, "window_days": "7"})))
    if not r:
        return None
    pbc = r[0].get("performance_by_category")
    if isinstance(pbc, str):
        try:
            pbc = json.loads(pbc)
        except ValueError:
            return None
    pnl, trades, wins = 0.0, 0, 0.0
    seen = False
    for c in pbc or []:
        if "politic" in str(c.get("category", "")).lower():
            seen = True
            pnl += _f(c.get("total_pnl")) or 0
            t = _f(c.get("total_trades")) or 0
            trades += int(t)
            wins += (_f(c.get("win_rate")) or 0) * t        # 注数加权胜率
    if not seen:
        return None
    return {"pnl": pnl, "trades": trades, "win_rate": (wins / trades) if trades else None}


def _political_pool():
    """从种子的热门政治盘共持人扩展出一批政治钱包——补 579 全品类周榜「政治稀薄」（top100 里仅 ~6 个政治赢家）。
    复用方法 E 的发现路：种子 → 热门政治盘 → 共持大户（天生政治），与 579 宇宙并集后再算 7d 政治盈亏。"""
    cids, pool = set(), set()
    for w in SEEDS:
        pos = _retry(get_top_political_position_hz, w, as_of=AS_OF, max_pages=15)
        if pos and not pos.get("error") and pos.get("market_id"):
            cids.add(pos["market_id"])
        time.sleep(0.4)
    for cid in cids:
        for hw, _v in _retry(get_market_holders, cid, as_of=AS_OF, top_n=12) or []:
            pool.add(hw)
        time.sleep(0.3)
    return pool


def scan(keep=10, floor=100.0):
    # 1) 宇宙 = 579 7d 全品类周榜(top100) ∪ 种子政治盘共持大户（补政治稀薄）
    uni = _retry(lambda: results(call(AGENTS["leaderboard"][0],
                {"wallet_address": "ALL", "leaderboard_period": "7d"}))) or []
    rank_of = {str(r.get("address", "")).lower(): r.get("rank") for r in uni}
    wallets = {str(r.get("address", "")).lower() for r in uni if r.get("address")}
    pool = _political_pool()
    wallets |= pool
    print(f"宇宙 = 579 7d {len(uni)} ∪ 政治共持池 {len(pool)} = {len(wallets)} 个 → 算各自政治盘 7 天盈亏…", flush=True)

    hot = []
    for i, w in enumerate(wallets):
        time.sleep(0.2)
        p = _politics_7d(w)
        if p and p["pnl"] > floor:             # 本周政治盘真赚钱（floor 滤掉 $44/0注 这类噪声尾巴）
            hot.append({"wallet": w, "weekly_politics_pnl": round(p["pnl"], 2),
                        "trades": p["trades"], "win_rate": p["win_rate"],
                        "overall_rank_7d": rank_of.get(w)})
        if (i + 1) % 30 == 0:
            print(f"  …扫到 {i+1}/{len(wallets)}，本周政治盈利者 {len(hot)} 个", flush=True)

    hot.sort(key=lambda h: -h["weekly_politics_pnl"])
    hot = hot[:keep]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"as_of": AS_OF, "generated_at": int(time.time()),
                               "period": "7d", "source": "579_7d_universe + 581_window7_politics",
                               "traders": hot}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✓ 本周政治盘热门交易者 {len(hot)} 个写入 {OUT}", flush=True)
    for h in hot:
        print(f"  {h['wallet'][:12]}… 本周政治 +${h['weekly_politics_pnl']:,.0f} · {h['trades']} 注", flush=True)
    return hot


if __name__ == "__main__":
    scan()
