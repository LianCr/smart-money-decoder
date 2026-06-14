"""
backtest/_scan_timepoint.py — v2 关键实验（诊断脚本，非生产 pipeline）

验证 v2 核心假设：把判断时点从「结算-7天」改成「建仓时点 entry_time」，decoder 的 GO 率
会不会显著上升？（因为建仓时点有催化剂、T-7 往往早于催化剂）

每个合格样本（已结算政治盘 + 有结算-7天历史价 + cost≥1000），在两个时点各重放一次 decoder，
均用 #7 干净新闻（as_of 截断）：
  A. 结算-7天：current_price=CLOB(t7)，news as_of=t7
  B. 建仓时点：current_price≈entry_price，news as_of=entry_time
输出两时点的 GO 率对照 + 各自的 (a)无新闻 比例。

下划线前缀 = 内部诊断工具，不入生产、可删。
"""
import sys
from collections import Counter

from dotenv import load_dotenv
load_dotenv()

from fetcher.news import get_news_for_market
from analyzer.decoder import DecoderError
from backtest.full_activity import fetch_full_activity
from backtest.resolution import get_market_resolution
from backtest.snapshot import get_price_at
from backtest.pipeline import (
    _reconstruct_positions, _assemble, _is_political, _date, _decode_retry, ENDORSE,
)

WALLETS = [
    "0x7c3db723f1d4d8cb9c550095203b686cb11e5c6b",  # Iran
    "0x9d84ce0306f8551e02efef1680475fc0f1dc1344",  # ImJustKen
    "0xa61ef8773ec2e821962306ca87d4b57e39ff0abd",  # risk-manager
    "0x24c8cf69a0e0a17eee21f69d29752bfa32e823e1",  # debased
    "0x507e52ef684ca2dd91f90a9d26d149dd3288beae",  # GamblingIsAllYouNeed
    "0xfbfd14dd4bb607373119de95f1d4b21c3b6c0029",  # XAE12Archangel
    "0xc8ab97a9089a9ff7e6ef0688e6e591a066946418",  # ArmageddonRewardsBilly
    "0x2663daca3cecf3767ca1c3b126002a8578a8ed1f",
    "0x2a2c53bd278c04da9962fcf96490e17f3dfb9bc1",
]
PER_WALLET = 3
GO = ENDORSE


def _log(m): print(m, file=sys.stderr, flush=True)


def decode_at(pos, res, current_price, as_of_ts):
    """在 as_of_ts 用 clean 新闻重放 → (follow_call|None, raw新闻数, time_anchored)。"""
    news = get_news_for_market(pos["title"] or res["question"], pos["entry_time"], as_of=as_of_ts)
    if news.get("error"):
        return None, 0, None
    raw = len(news.get("articles", []))
    a = _assemble(pos, res, current_price, news)
    try:
        card = _decode_retry(a, _date(as_of_ts))
    except DecoderError:
        return None, raw, news.get("time_anchored")
    return card["follow_call"], raw, news.get("time_anchored")


def main():
    rows = []
    for w in WALLETS:
        _log(f"\n═══ {w[:12]}… ═══")
        try:
            recs = fetch_full_activity(w)
        except Exception as e:
            _log(f"  跳过（{type(e).__name__}）"); continue
        pos_map = _reconstruct_positions(recs)
        n = 0
        for cid, pos in pos_map.items():
            if n >= PER_WALLET:
                break
            if not pos["token"] or not pos["entry_time"]:
                continue
            if pos["entry_price"] * pos["size"] < 1000:
                continue
            # 逐候选包 try：单个瞬时 API 错（gamma 超时等）只跳过该候选，不杀全局长跑
            try:
                res = get_market_resolution(cid)
                if not res or not res.get("resolved_time"):
                    continue
                rt = res["resolved_time"]; t7 = rt - 7 * 86400
                p7 = get_price_at(pos["token"], t7)
                if p7 is None:
                    continue
                if not _is_political(res.get("event_id")):
                    continue
                fcA, rawA, anchA = decode_at(pos, res, p7, t7)                     # 结算-7天
                fcB, rawB, anchB = decode_at(pos, res, pos["entry_price"], pos["entry_time"])  # 建仓时点
            except Exception as e:
                _log(f"  ⚠️ {(pos['title'] or cid)[:28]} 跳过（{type(e).__name__}）")
                continue
            if fcA is None or fcB is None:
                _log(f"  ⚠️ {res['question'][:30]} decoder 跳过"); continue
            won = (pos["outcome"] == res["winning_outcome"])
            entry_before_t7 = pos["entry_time"] < t7
            rows.append(dict(q=res["question"], won=won, fcA=fcA, rawA=rawA, fcB=fcB, rawB=rawB,
                             ebt7=entry_before_t7))
            n += 1
            _log(f"  {res['question'][:34]:34} | 结算-7d:{fcA:9}(raw{rawA}) | 建仓:{fcB:9}(raw{rawB})"
                 f" | {'赢' if won else '输'} | 建仓{'早于' if entry_before_t7 else '晚于'}T-7")
        _log(f"  → 贡献 {n}")

    N = len(rows)
    if not N:
        _log("无样本"); return
    goA = sum(r["fcA"] in GO for r in rows); goB = sum(r["fcB"] in GO for r in rows)
    aA = sum(r["rawA"] == 0 for r in rows); aB = sum(r["rawB"] == 0 for r in rows)
    ebt7 = sum(r["ebt7"] for r in rows)
    flips = sum((r["fcA"] not in GO) and (r["fcB"] in GO) for r in rows)  # T-7躲→建仓跟
    print("\n" + "=" * 60)
    print(f"样本 N={N}（建仓早于T-7的 {ebt7} 个）")
    print(f"结算-7天 GO 率 : {goA}/{N} = {goA/N:.0%}   | (a)无新闻 {aA}/{N}")
    print(f"建仓时点 GO 率 : {goB}/{N} = {goB/N:.0%}   | (a)无新闻 {aB}/{N}")
    print(f"时点切换后由「躲」转「跟」的样本：{flips}/{N}")
    print("=" * 60)
    print(f">>> v2 核心假设：换到建仓时点 GO 率显著上升？ {'✅ 是' if goB > goA*1.5 and goB>=3 else '⚠️ 不明显/样本不足'}")


if __name__ == "__main__":
    main()
