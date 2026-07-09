"""
tests/test_positions_near_settled.py — 入口"近结算守卫"（monkeypatch heisenberg，无网络）

背景（2026-07-09 实测 0xe8dd…钱包）：最大仓入口只看规模+未结算，选中 Fed 降息 NO@99.5¢
的无悬念盘。守卫：持有侧 ≥95¢ → 跳过找下一个有悬念的仓；整本全是近结算（卖彩票型
NO 农场）→ 诚实回退最大那个并打 near_settled 标。覆盖：
  1. 最大仓近结算、次大仓有悬念 → 选次大仓
  2. 整本全近结算 → 回退最大 + near_settled/held_price 标
  3. 价格拿不到（568 空）→ 不参与判定，照常返回最大仓（数据故障不改选择）
  4. 列表版：近结算不进推荐发现（无回退）
  5. 94¢（阈值之下）不触发守卫
"""

import sys
sys.path.insert(0, ".")

import fetcher.positions as fp

passed = 0
failed = 0


def check(name, got, want):
    global passed, failed
    if got == want:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name}: got={got!r} want={want!r}")


W = "0x" + "a" * 40
AS_OF = "2026-07-09"


def _trade(cid, outcome, size, price, side="BUY", slug="trump-market"):
    return {"condition_id": cid, "outcome": outcome, "size": size, "price": price,
            "side": side, "slug": slug}


def _market(cid, q):
    return {"condition_id": cid, "question": q, "closed": False, "end_date": "2026-12-31T00:00:00Z",
            "side_a_outcome": "Yes", "side_a_token_id": f"tokY-{cid}",
            "side_b_outcome": "No", "side_b_token_id": f"tokN-{cid}"}


class _Fake:
    """替身 heisenberg：trades 由 paginate 供给；574 按 cid 查市场；568 按 token 查价。"""
    def __init__(self, trades, markets, prices):
        self.trades = trades
        self.markets = {m["condition_id"]: m for m in markets}
        self.prices = prices          # {token_id: close 或 None(无K线)}

    def paginate(self, agent_id, params, max_pages=15):
        return self.trades

    def call(self, agent_id, params, **kw):
        if agent_id == fp.AGENTS["markets"][0]:
            m = self.markets.get(params.get("condition_id"))
            return {"data": [m] if m else []}
        if agent_id == fp.AGENTS["candles"][0]:
            px = self.prices.get(params.get("token_id"))
            if px is None:
                return {"data": []}
            return {"data": [{"candle_time": "2026-07-08T00:00:00Z", "close": px}]}
        return {"data": []}


def _install(fake):
    fp.paginate = fake.paginate
    fp.call = fake.call


_real = (fp.paginate, fp.call, fp.results)
try:
    # 1. 最大仓近结算(No@0.99)、次大仓有悬念(Yes@0.60) → 选次大仓
    trades = [_trade("cid1", "No", 10000, 0.98), _trade("cid2", "Yes", 5000, 0.55)]
    fake = _Fake(trades,
                 [_market("cid1", "Will the Fed cut rates?"), _market("cid2", "Trump wins?")],
                 {"tokN-cid1": 0.99, "tokY-cid2": 0.60})
    _install(fake)
    got = fp.get_top_political_position_hz(W, as_of=AS_OF)
    check("最大仓 99¢ 被跳过 → 选次大有悬念仓", got.get("market_id"), "cid2")
    check("有悬念仓不带 near_settled 标", got.get("near_settled"), None)

    # 2. 整本全近结算 → 回退最大那个 + 打标
    fake = _Fake(trades,
                 [_market("cid1", "Will the Fed cut rates?"), _market("cid2", "Trump wins?")],
                 {"tokN-cid1": 0.995, "tokY-cid2": 0.97})
    _install(fake)
    got = fp.get_top_political_position_hz(W, as_of=AS_OF)
    check("全近结算 → 诚实回退最大仓", got.get("market_id"), "cid1")
    check("回退带 near_settled 标", got.get("near_settled"), True)
    check("回退带 held_price", got.get("held_price"), 0.995)

    # 3. 价格拿不到（568 无K线）→ 不参与判定，照常返回最大仓
    fake = _Fake(trades,
                 [_market("cid1", "Will the Fed cut rates?"), _market("cid2", "Trump wins?")],
                 {})                                        # 所有 token 都查不到价
    _install(fake)
    got = fp.get_top_political_position_hz(W, as_of=AS_OF)
    check("价格未知不改选择（返回最大仓）", got.get("market_id"), "cid1")
    check("价格未知不打标", got.get("near_settled"), None)

    # 4. 列表版：近结算不进推荐发现
    fake = _Fake(trades,
                 [_market("cid1", "Will the Fed cut rates?"), _market("cid2", "Trump wins?")],
                 {"tokN-cid1": 0.99, "tokY-cid2": 0.60})
    _install(fake)
    got = fp.get_top_political_positions_hz(W, as_of=AS_OF, n=3)
    check("列表版排除 99¢ 盘", [p["market_id"] for p in got], ["cid2"])

    # 5. 94¢ 不触发（阈值 0.95）
    fake = _Fake(trades,
                 [_market("cid1", "Will the Fed cut rates?"), _market("cid2", "Trump wins?")],
                 {"tokN-cid1": 0.94, "tokY-cid2": 0.60})
    _install(fake)
    got = fp.get_top_political_position_hz(W, as_of=AS_OF)
    check("94¢ 在阈值内，照常选最大仓", got.get("market_id"), "cid1")
finally:
    fp.paginate, fp.call, fp.results = _real

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
