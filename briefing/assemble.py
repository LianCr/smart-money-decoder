"""
briefing/assemble.py — A 段编排器：拼第一份完整聪明钱简报（v3）

职责：把已建好的零件按顺序串成一份**结构化简报 JSON**（代码组织，无判断、无第三个 AI）。
  WHO   profile.py    画像（581/579/569）
  WHAT  actions.py    动作（556/568/574）
  PRICE price.py      价格（568+算）
  催化剂 dual_catalyst 双向辩证（Tavily）+ price_reaction 市场份量刻度/测谎仪（编排层接入）

红线：本层只**编排与如实陈列**，不下任何"该不该跟"判断（那是 B 段第三个 AI 的事，且也只整理不判断）。
Token：仅 dual_catalyst 的 2 次 LLM 烧老师 token（≈3.2k）；profile/actions/price/reaction 全免费 key。
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from fetcher.heisenberg import AGENTS, call, results
from fetcher.profile import get_trader_profile
from fetcher.actions import get_position_actions
from fetcher.price import get_price_context
from analyzer.dual_catalyst import analyze as dual_catalyst_analyze
from analyzer.price_reaction import enrich_catalysts


def _resolve_market(slug=None, cid=None):
    base = {}
    if slug:
        base["market_slug"] = slug
    if cid:
        base["condition_id"] = cid
    # 先查未结算(默认)，再查已结算——同时支持 live open 仓和已结算复盘
    for extra in ({}, {"closed": "True"}):
        rs = results(call(AGENTS["markets"][0], {**base, **extra}))
        if rs:
            return rs[0]
    return None


def _token_for(market, outcome):
    if outcome.lower() == str(market.get("side_a_outcome", "")).lower():
        return market.get("side_a_token_id")
    if outcome.lower() == str(market.get("side_b_outcome", "")).lower():
        return market.get("side_b_token_id")
    return None


def _entry_unix(entry_str):
    if not entry_str:
        return None
    try:
        return int(datetime.strptime(entry_str, "%Y-%m-%d %H:%M")
                   .replace(tzinfo=timezone.utc).timestamp())
    except ValueError:
        return None


def assemble_briefing(wallet, outcome, slug=None, cid=None, as_of="2026-06-20", mode="live"):
    """
    组装一份完整简报。slug 或 cid 二选一定位市场。
    mode：'live'(实战，催化剂锚 as_of/现在) | 'replay'(复盘，催化剂锚鲸鱼建仓时间)。
    """
    market = _resolve_market(slug=slug, cid=cid)
    if not market:
        return {"error": "574 定位不到市场（slug/cid 检查）"}
    cid = market.get("condition_id")
    token = _token_for(market, outcome)
    market_title = market.get("question", "")

    # WHO / WHAT / PRICE（全免费）
    who = get_trader_profile(wallet)
    what = get_position_actions(wallet, cid, outcome, as_of_date=as_of)
    entry_str = (what.get("actions") or {}).get("entry_time")
    avg_price = (what.get("actions") or {}).get("avg_entry_price")
    price_ctx = get_price_context(token, outcome, market, entry_price=avg_price, as_of_date=as_of)

    # 催化剂辩证（dual_catalyst，烧 token）+ price_reaction 接入（编排层）
    # live 锚 as_of(现在看当前局势) / replay 锚 entry_time(看鲸鱼当初为何进)
    as_of_anchor = as_of if mode == "live" else None
    cats = dual_catalyst_analyze(market_title, outcome, _entry_unix(entry_str),
                                 as_of_anchor=as_of_anchor)
    enrich_catalysts(cats.get("positive_catalysts", []), token, "positive", as_of=as_of)
    enrich_catalysts(cats.get("negative_catalysts", []), token, "negative", as_of=as_of)

    return {
        "meta": {"wallet": wallet, "market": market_title, "analyzed_side": outcome,
                 "as_of": as_of, "mode": mode, "catalyst_anchor": as_of_anchor or "entry_time",
                 "settle": (what.get("market") or {}).get("settle_note")},
        "who_trader_profile": who,
        "what_position_actions": what,
        "price_context": price_ctx,
        "catalysts": {
            "positive": cats.get("positive_catalysts", []),
            "negative": cats.get("negative_catalysts", []),
            "balance_summary": cats.get("evidence_balance_summary"),
            "honesty_caveat": cats.get("honesty_caveat"),
            "guards": cats.get("_guards"),
        },
        "_audit": {"teacher_tokens_approx": cats.get("_audit", {}).get("total_teacher_tokens_approx"),
                   "free_sources": ["581", "579", "569", "556", "568", "574"],
                   "catalyst_window": cats.get("_audit", {}).get("window")},
    }


# ── 缓存：结构化简报按 (钱包,市场,as_of) 缓存，重跑不再烧 dual_catalyst ──────────
CACHE_DIR = Path(".cache/briefing")


def _cache_path(wallet, key, as_of, mode):
    sig = f"{wallet.lower()}|{key}|{as_of}|{mode}"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{hashlib.md5(sig.encode()).hexdigest()}.json"


def load_or_build_briefing(wallet, outcome, slug=None, cid=None, as_of="2026-06-20", mode="live"):
    """命中缓存直接返回（不烧 token）；未命中才 assemble（烧 dual_catalyst）并落盘。"""
    path = _cache_path(wallet, slug or cid or "", as_of, mode)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    b = assemble_briefing(wallet, outcome, slug=slug, cid=cid, as_of=as_of, mode=mode)
    if "error" not in b:
        try:
            path.write_text(json.dumps(b, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
    return b


# ── 第一份简报验证：ImJustKen · Starmer out by May 31（已结算·真相已知）─────────
if __name__ == "__main__":
    KEN = "0x9d84ce0306f8551e02efef1680475fc0f1dc1344"
    b = assemble_briefing(KEN, "Yes", slug="starmer-out-by-may-31-2026")

    print("=" * 82)
    print(f"完整简报（A段编排器·结构化）· {b['meta']['market']} · 押注 {b['meta']['analyzed_side']}")
    print(f"钱包 {b['meta']['wallet'][:14]}… · as_of {b['meta']['as_of']} · {b['meta']['settle']}")
    print("=" * 82)

    who = b["who_trader_profile"]
    q = who.get("quality", {})
    rk = who.get("official_rank", {})
    print("\n▌WHO 画像")
    print(f"  风险分={q.get('combined_risk_score')} · flagged={q.get('flagged_metrics')} · 曲线={q.get('equity_curve_pattern')}")
    print(f"  官方榜 rank={rk.get('rank')} win_rate={rk.get('win_rate')} total_pnl={rk.get('total_pnl')}")
    pol = [c for c in who.get("category_specialization", []) if "Politics" in str(c.get("category"))]
    if pol:
        print(f"  政治盘专长：{pol[0]['category']} roi={pol[0]['roi']} win={pol[0]['win_rate']} pnl={pol[0]['total_pnl']}")
    wr = _f = None
    try:
        if float(rk.get("win_rate", 0)) > 0.8 and float(rk.get("total_pnl", 0)) < 0:
            print("  ⚠️诚实标注：高胜率(>80%)但净 PnL 为负 = 胜率谎言/幸存者偏差，看净盈亏非胜率")
    except (TypeError, ValueError):
        pass

    act = b["what_position_actions"].get("actions", {})
    ts = b["what_position_actions"].get("two_side_distribution", {})
    un = b["what_position_actions"].get("unrealized", {})
    print("\n▌WHAT 动作")
    print(f"  建仓 {act.get('entry_time')} · {act.get('num_buys')}笔买 · 均价 {act.get('avg_entry_price')} · 成本 ${act.get('net_cost_usd')}")
    print(f"  两侧分布 hedged={ts.get('hedged')} · {ts.get('note')}")
    print(f"  浮/实现盈亏 {un.get('unrealized_pnl_usd')} ({un.get('unrealized_pct')}%) · {un.get('note')}")

    pc = b["price_context"]
    print("\n▌PRICE 价格")
    print(f"  现价={pc.get('current_price')} 隐含概率={pc.get('implied_probability_pct')}% "
          f"剩余空间(赢)={pc.get('remaining_upside_pct_if_win')}% 赔率={pc.get('odds_to_one')} vs入场={pc.get('price_delta_pct')}%")

    print("\n▌催化剂辩证（材质标签 + 市场份量/测谎）")
    for side, key in (("正向·支持", "positive"), ("负向·威胁", "negative")):
        print(f"  【{side}】")
        for c in b["catalysts"][key]:
            pr = c.get("price_reaction", {})
            tag = (f"{pr.get('direction','')}{pr.get('move_pct','')}% {pr.get('market_check','')}"
                   if pr.get("available") else pr.get("reason", ""))
            print(f"    ·[{c.get('type')}] {c.get('title','')[:50]} [{c.get('date')}]")
            print(f"       市场反应: {tag}")
    print(f"\n  天平: {b['catalysts']['balance_summary']}")
    print(f"  honesty: {json.dumps(b['catalysts']['honesty_caveat'], ensure_ascii=False)}")

    print(f"\n▌Token 审计: 老师 token≈{b['_audit']['teacher_tokens_approx']}（仅 dual_catalyst）· "
          f"其余 {b['_audit']['free_sources']} 全免费")
    print("\n第一份完整简报组装成功。")
