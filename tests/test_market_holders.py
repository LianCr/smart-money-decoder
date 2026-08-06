"""
tests/test_market_holders.py — get_market_holders 分页修复（P2-29）

老病：docstring 写"556 按 cid 全量"，实现却用裸 `call()`（单页 ≤200 条）——热门盘
成交流轻松破 200，第 201 条起被静默丢弃 → 共持大户发现池（recommend + hot_traders
的地基）系统性缺人：一个只在尾部成交的大买家会整个从推荐宇宙里消失。
修复=接 `paginate()`。本测试钉死：>200 条时尾部大户必须被算进来。
"""

import sys
sys.path.insert(0, ".")

import fetcher.markets as mk

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


def trade(w, size, price=0.5, side="BUY"):
    return {"proxy_wallet": w, "size": size, "price": price, "side": side}


W_HEAD = "0x" + "a" * 40      # 前 200 条里的散户（每条小额）
W_TAIL = "0x" + "b" * 40      # 🔴 只出现在第 201 条以后的大户——裸 call() 时代他会消失
W_SELL = "0x" + "c" * 40      # 净卖出者，不该出现在多头侧

# 250 条成交：前 200 条=散户小单，第 201-250 条=尾部大户 + 一个净卖出者
FEED = ([trade(W_HEAD, 10)] * 200
        + [trade(W_TAIL, 500)] * 45
        + [trade(W_SELL, 100, side="BUY")] + [trade(W_SELL, 300, side="SELL")]
        + [trade(W_TAIL, 500)] * 3)

_pages = []


def fake_paginate(agent_id, params, max_pages=30, sleep=0.15):
    _pages.append({"agent_id": agent_id, "params": dict(params), "max_pages": max_pages})
    return list(FEED)


_saved = mk.paginate
mk.paginate = fake_paginate
try:
    holders = mk.get_market_holders("0x" + "d" * 40, as_of="2026-08-06", top_n=10)
    by_w = dict(holders)

    check("走的是 paginate（不再裸 call 单页）", len(_pages), 1)
    check("翻页目标是 556 Trades", _pages[0]["agent_id"], 556)
    check("proxy_wallet=ALL 全市场聚合", _pages[0]["params"].get("proxy_wallet"), "ALL")
    check("🔴 >200 条时尾部大户被算进来（裸 call 时代他会消失）", W_TAIL in by_w, True)
    check("尾部大户净额完整（48×500×0.5）", round(by_w[W_TAIL], 2), 12000.0)
    check("头部散户也在（200×10×0.5）", round(by_w.get(W_HEAD, 0), 2), 1000.0)
    check("大户排在散户前（按净额降序）", holders[0][0], W_TAIL)
    check("净卖出者不进多头侧", W_SELL in by_w, False)

    _pages.clear()
    check("坏 cid → 空列表（不打网络）", mk.get_market_holders("not-a-cid"), [])
    check("坏 cid 不翻页", _pages, [])
finally:
    mk.paginate = _saved

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
