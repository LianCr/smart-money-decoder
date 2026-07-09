"""
tests/test_heisenberg_retry.py — heisenberg.call 的 429 退避重试（monkeypatch，无网络不真睡）

背景（对应 bug）：扫榜线程和看板重建**并发**打 Heisenberg 限流时，一个 429 就把整条
dashboard pipeline 炸成 DASHBOARD_PIPELINE_FAILED。现在 call 内建退避（2s/4s/6s）。覆盖：
  1. 一次 200 → 只发 1 次请求、不睡
  2. 429×2 后 200 → 共 3 次请求、睡 [2,4]、最终成功
  3. 一直 429 → 重试耗尽（1+3 次）抛 RATE_LIMITED
  4. 429 后恢复的响应仍过第七道守卫（钱包不匹配照拦）
"""

import sys
sys.path.insert(0, ".")

import fetcher.heisenberg as hz

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


class _FakeResp:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._p = payload if payload is not None else {"data": []}
        self.text = "rate limited" if status_code == 429 else "ok"

    def json(self):
        return self._p


class _FakePost:
    def __init__(self, script):
        self.script = list(script)
        self.n = 0

    def __call__(self, url, headers=None, json=None, timeout=None):
        self.n += 1
        return self.script.pop(0)


class _FakeRequestsModule:
    """只替换 post；exceptions 沿用真 requests 的（call 里 except 要用）。"""
    def __init__(self, post):
        self.post = post
        self.exceptions = hz.requests.exceptions


_real_requests, _real_sleep, _real_key = hz.requests, hz._SLEEP, hz.KEY
sleeps = []
try:
    hz.KEY = "test-key"                      # 绕过 NO_KEY（不打真网络）
    hz._SLEEP = lambda s: sleeps.append(s)   # 不真睡，只记录

    # 1. 一次 200：1 次请求、不睡
    post = _FakePost([_FakeResp(200)])
    hz.requests = _FakeRequestsModule(post)
    sleeps.clear()
    out = hz.call(574, {"condition_id": "0xcid"})     # 574 无钱包参数 → 不触发守卫
    check("200 直接成功", out, {"data": []})
    check("200 只发 1 次", post.n, 1)
    check("200 不睡", sleeps, [])

    # 2. 429×2 → 200：3 次请求、睡 [2,4]、成功
    post = _FakePost([_FakeResp(429), _FakeResp(429), _FakeResp(200)])
    hz.requests = _FakeRequestsModule(post)
    sleeps.clear()
    out = hz.call(574, {"condition_id": "0xcid"})
    check("429×2 后恢复 → 成功", out, {"data": []})
    check("429×2 共发 3 次", post.n, 3)
    check("退避节奏 [2,4]", sleeps, [2, 4])

    # 3. 一直 429：1+3 次后抛 RATE_LIMITED
    post = _FakePost([_FakeResp(429)] * 4)
    hz.requests = _FakeRequestsModule(post)
    sleeps.clear()
    try:
        hz.call(574, {"condition_id": "0xcid"})
        check("持续 429 → 抛 RATE_LIMITED", "no-raise", "HeisenbergError")
    except hz.HeisenbergError as e:
        check("持续 429 → 抛 RATE_LIMITED", e.reason, "RATE_LIMITED")
    check("重试耗尽共发 4 次", post.n, 4)
    check("退避节奏 [2,4,6]", sleeps, [2, 4, 6])

    # 4. 重试恢复后第七道守卫照常工作（返回钱包 ≠ 请求钱包 → 拦）
    w_req = "0x" + "a" * 40
    bad_payload = {"data": [{"proxy_wallet": "0x" + "b" * 40}]}
    post = _FakePost([_FakeResp(429), _FakeResp(200, bad_payload)])
    hz.requests = _FakeRequestsModule(post)
    sleeps.clear()
    try:
        hz.call(556, {"proxy_wallet": w_req})
        check("恢复后守卫照拦串号", "no-raise", "WALLET_MISMATCH")
    except hz.HeisenbergError as e:
        check("恢复后守卫照拦串号", e.reason, "WALLET_MISMATCH")
finally:
    hz.requests, hz._SLEEP, hz.KEY = _real_requests, _real_sleep, _real_key

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
