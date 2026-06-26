"""
recommend.py — 扫榜推荐 · 免费扫榜层（定期手动/cron 跑，写 .data/recommendations.json）

584 H-Score 质量榜(已滤机器人/运气/刷量) → 逐个查政治顶仓 → 启发式打分 → 候选清单。
🔴 全免费(纯 Heisenberg 数据,无 LLM)。AI 精选层(对 top N 跑完整 ⑥)随后另加,会填 ai_pick + verdict。
🔴 红线#6：候选只是"值得一看",不是"该跟";单边 vs 对冲的真判定留给 AI 精选的 R2。

跑法：`.venv/bin/python recommend.py`（慢，~分钟级，逐个钱包查 556；带 429 退避）。
"""
import json
import time
from pathlib import Path

from fetcher.heisenberg import call, results, AGENTS, HeisenbergError
from fetcher.positions import get_top_political_position_hz
from briefing.market_context import get_behavior_flags

AS_OF = "2026-06-25"                 # 与 api.main.BRIEFING_AS_OF 对齐，点击即 /dashboard 同时点
OUT = Path(".data/recommendations.json")


def _retry(fn, *a, **k):
    for i in range(5):
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


def scan(top_n=24, keep=10):
    board = _retry(lambda: results(call(AGENTS["hscore"][0], {"sort_by": "pnl"}))) or []
    board = sorted(board, key=lambda r: -(_f(r.get("h_score")) or 0))   # 按 H-Score 质量排
    print(f"584 榜拉到 {len(board)} 个，扫前 {top_n} 找政治盘…", flush=True)

    cands = []
    for i, row in enumerate(board[:top_n]):
        w = row.get("wallet")
        if not w:
            continue
        time.sleep(0.4)
        pos = _retry(get_top_political_position_hz, w, as_of=AS_OF)
        if not pos or pos.get("error"):           # 非政治 / 无未结算政治顶仓 → 跳
            continue
        time.sleep(0.4)
        bf = _retry(get_behavior_flags, w, pos["market_id"], AS_OF) or {}
        beh = bf.get("flag")

        # 启发式打分（全免费信号）：H-Score 质量底座 + 行为(加仓正/退出负)
        score = _f(row.get("h_score")) or 0.0
        if beh == "ADD":
            score += 15
        elif beh == "EXIT":
            score -= 25                            # 主力撤退 = 别推
        cands.append({
            "wallet": w,
            "market_question": pos["market_question"],
            "outcome": pos["outcome"],
            "h_score": row.get("h_score"),
            "tier": row.get("tier"),
            "roi_15d": row.get("roi_pct_15d"),
            "win_rate_15d": row.get("win_rate_pct_15d"),
            "behavior": beh,
            "behavior_fact": bf.get("fact"),
            "score": round(score, 1),
            "ai_pick": False,                      # AI 精选层后填 True + verdict/confidence
        })
        print(f"  [{i+1}] {w[:12]}… H{row.get('h_score')} {beh} · {pos['market_question'][:34]} {pos['outcome']}", flush=True)

    cands.sort(key=lambda c: -c["score"])
    cands = cands[:keep]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"as_of": AS_OF, "generated_at": int(time.time()),
                               "candidates": cands}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✓ 候选 {len(cands)} 个写入 {OUT}")
    return cands


if __name__ == "__main__":
    scan()
