"""
backtest/_t2_probe.py — T2 前置字段实测（下划线前缀 = 内部诊断，不入生产、可删）

三个问题，结果进 CLAUDE.md 坑表后才许写生产代码：
  1. 572 Orderbook：毫秒时间戳实证（喂秒是不是静默空）、参数真名、
     best_bid/best_ask/spread/bid_depth/ask_depth 真名真值与单位、快照密度。
  2. 596 Price Jumps：在我们 key 上存在吗（403 plan-gated 风险）、参数真名、
     返回形状、有没有 start/end 时间锚（决定②能不能锚 as_of）。
  3. 568 volume：字段真名、单位量级（VOLUME_THIN 标定地基）。

跑法：.venv/bin/python backtest/_t2_probe.py
"""
import json
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, ".")
from dotenv import load_dotenv

load_dotenv()

from fetcher.heisenberg import call, results, HeisenbergError


def get_live_token():
    """找个高量活跃盘的 token（572/596/568 都要 token_id）。"""
    mkts = results(call(574, {"closed": "False", "min_volume": "500000"}, limit=10))
    for m in mkts:
        tok = m.get("side_a_token_id")
        if tok:
            return tok, m.get("question", "")[:60]
    return None, None


def main():
    tok, q = get_live_token()
    if not tok:
        print("✗ 拿不到活跃盘 token，止步")
        return 1
    print(f"样本盘：{q}\ntoken：{str(tok)[:24]}…\n")

    now_s = int(time.time())
    day_s = 86400

    # ── 1. 572 Orderbook ────────────────────────────────────────────────────
    print("===== ① 572 Orderbook =====")
    for label, params in [
        ("毫秒时间戳（文档说的对不对）", {"token_id": tok,
                                          "start_time": str((now_s - 3 * day_s) * 1000),
                                          "end_time": str(now_s * 1000)}),
        ("秒时间戳（喂秒会怎样）", {"token_id": tok,
                                    "start_time": str(now_s - 3 * day_s),
                                    "end_time": str(now_s)}),
        ("无时间参数", {"token_id": tok}),
    ]:
        try:
            rs = results(call(572, params, limit=200))
            print(f"  {label}: 200, {len(rs)} 条")
            if rs:
                print(f"    首条 keys: {sorted(rs[0].keys())}")
                print(f"    首条: {json.dumps(rs[0], ensure_ascii=False)[:300]}")
                if len(rs) >= 2:
                    print(f"    末条: {json.dumps(rs[-1], ensure_ascii=False)[:200]}")
        except HeisenbergError as e:
            print(f"  {label}: ✗ {e.reason} —— {e.message[:100]}")

    # ── 2. 596 Price Jumps ──────────────────────────────────────────────────
    print("\n===== ② 596 Price Jumps =====")
    base = {"token_id": tok, "resolution": "1d", "min_change_pct": "3", "lookback_hours": "720"}
    for label, params in [
        ("文档四参数", dict(base)),
        ("加 start/end 秒（有没有 as_of 锚）", {**base,
             "start_time": str(now_s - 30 * day_s), "end_time": str(now_s - 7 * day_s)}),
        ("加 end_time 单独", {**base, "end_time": str(now_s - 7 * day_s)}),
    ]:
        try:
            rs = results(call(596, params, limit=50))
            print(f"  {label}: 200, {len(rs)} 条")
            if rs:
                print(f"    首条 keys: {sorted(rs[0].keys())}")
                print(f"    首条: {json.dumps(rs[0], ensure_ascii=False)[:300]}")
                latest = max(str(r.get('jump_time', '')) for r in rs)
                print(f"    最新 jump_time: {latest}（对照 end_time 判断锚是否生效）")
        except HeisenbergError as e:
            print(f"  {label}: ✗ {e.reason} —— {e.message[:100]}")

    # ── 3. 568 volume ───────────────────────────────────────────────────────
    print("\n===== ③ 568 volume 字段 =====")
    try:
        rs = results(call(568, {"token_id": tok, "interval": "1d",
                                "start_time": str(now_s - 10 * day_s), "end_time": str(now_s)}))
        print(f"  {len(rs)} 条日 K")
        if rs:
            print(f"  keys: {sorted(rs[0].keys())}")
            for r in rs[-5:]:
                print(f"    {str(r.get('candle_time'))[:10]} close={r.get('close')} "
                      f"volume={r.get('volume')!r} vol={r.get('vol')!r}")
    except HeisenbergError as e:
        print(f"  ✗ {e.reason} —— {e.message[:100]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
