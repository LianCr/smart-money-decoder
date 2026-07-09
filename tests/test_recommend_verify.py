"""
tests/test_recommend_verify.py — recommend.ai_verify 诚实守卫测试（monkeypatch requests，无网络）

背景（对应 bug 实拍）：刷新推荐榜后出现"有 AI 精选徽章但信心/推理全空"的残卡——
旧 ai_verify 只要 HTTP 没抛异常就无条件 ai_pick=True，看板返回错误 JSON 也照标。覆盖：
  1. 看板返回完整 reasoning → 标精选 + 字段齐全 + verified_as_of
  2. 看板返回错误 JSON（error 字段）→ 绝不标精选、不留半截字段
  3. reasoning 存在但 confidence 空 → 不标精选（残卡的直接根因）
  4. 请求抛异常（后端不在线）→ 跳过不崩、不标精选
  5. fresh=True → 请求带 fresh=1；fresh=False → 不带（保鲜语义）
  6. facts 回填 market_question/outcome（防卡片与看板判断错配）
"""

import sys
sys.path.insert(0, ".")

import recommend

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
    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p


class _FakeRequests:
    """替身 requests：记录每次调用参数，按脚本依次吐响应（可混入异常）。"""
    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": dict(params or {})})
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return _FakeResp(item)


def _cand(w="0x" + "a" * 40):
    return {"wallet": w, "market_question": "原始盘名?", "outcome": "Yes", "ai_pick": False}


FULL = {
    "as_of": "2026-07-08",
    "reasoning": {
        "confidence": "med", "follow_call": "CHASED", "reasoning": "推理文本",
        "market_lean": "NO", "alignment": "逆 edge",
        "facts": {"market_question": "看板盘名?", "outcome": "No", "position_type": "single_side_conviction"},
    },
}
ERROR_JSON = {"error": "DASHBOARD_PIPELINE_FAILED", "reason": "DASHBOARD_PIPELINE_FAILED", "message": "上游挂了"}
EMPTY_CONF = {"as_of": "2026-07-08", "reasoning": {"confidence": None, "follow_call": None, "facts": {}}}

_real = recommend.requests
try:
    # 1. 完整裁决 → 标精选、字段齐全
    fake = _FakeRequests([FULL]); recommend.requests = fake
    c = _cand(); recommend.ai_verify([c], top=1)
    check("完整裁决 → ai_pick=True", c["ai_pick"], True)
    check("完整裁决 → confidence=med", c.get("ai_confidence"), "med")
    check("完整裁决 → follow_call=CHASED", c.get("ai_follow_call"), "CHASED")
    check("完整裁决 → verified_as_of 记录", c.get("verified_as_of"), "2026-07-08")

    # 6. facts 回填（与看板同一注）
    check("facts 回填 market_question", c["market_question"], "看板盘名?")
    check("facts 回填 outcome", c["outcome"], "No")

    # 2. 错误 JSON → 绝不标精选、不留半截字段
    fake = _FakeRequests([ERROR_JSON]); recommend.requests = fake
    c = _cand(); recommend.ai_verify([c], top=1)
    check("错误 JSON → ai_pick 保持 False", c["ai_pick"], False)
    check("错误 JSON → 不留 ai_confidence 残字段", "ai_confidence" in c, False)
    check("错误 JSON → 不留 ai_verdict 残字段", "ai_verdict" in c, False)

    # 3. reasoning 有但 confidence 空 → 不标精选（残卡直接根因）
    fake = _FakeRequests([EMPTY_CONF]); recommend.requests = fake
    c = _cand(); recommend.ai_verify([c], top=1)
    check("confidence 空 → ai_pick 保持 False", c["ai_pick"], False)

    # 4. 请求抛异常 → 跳过不崩
    fake = _FakeRequests([ConnectionError("refused")]); recommend.requests = fake
    c = _cand(); recommend.ai_verify([c], top=1)
    check("请求异常 → 不崩且不标精选", c["ai_pick"], False)

    # 5. fresh 语义：True 带 fresh=1，False 不带
    fake = _FakeRequests([FULL]); recommend.requests = fake
    recommend.ai_verify([_cand()], top=1, fresh=True)
    check("fresh=True → 请求带 fresh=1", fake.calls[0]["params"].get("fresh"), 1)
    fake = _FakeRequests([FULL]); recommend.requests = fake
    recommend.ai_verify([_cand()], top=1, fresh=False)
    check("fresh=False → 请求不带 fresh", "fresh" in fake.calls[0]["params"], False)

    # 附：top 截断——只验证前 N 个（第 2 个候选不该发请求）
    fake = _FakeRequests([FULL]); recommend.requests = fake
    c1, c2 = _cand(), _cand("0x" + "b" * 40)
    recommend.ai_verify([c1, c2], top=1)
    check("top=1 只发 1 次请求", len(fake.calls), 1)
    check("top 之外的候选不动", c2["ai_pick"], False)

    # ── 并行验证（2026-07-08）：不同盘真并发、同盘串行（防 thesis 重复建/市场观分裂）──
    import threading as _th
    import time as _tm
    import copy as _cp

    class _SlowFake:
        """线程安全假 requests：每次 get 睡 0.15s，记录并发峰值。"""
        def __init__(self):
            self.lock = _th.Lock()
            self.inflight = 0
            self.peak = 0
            self.calls = 0

        def get(self, url, params=None, timeout=None):
            with self.lock:
                self.inflight += 1
                self.peak = max(self.peak, self.inflight)
                self.calls += 1
            _tm.sleep(0.15)
            with self.lock:
                self.inflight -= 1
            class _R:
                def json(_s):
                    return _cp.deepcopy(FULL)
            return _R()

    # 3 个不同盘的候选 → 并发峰值应 ≥2（真并行）
    slow = _SlowFake(); recommend.requests = slow
    cs = [dict(_cand("0x" + ch * 40), market_question=f"盘{ch}?") for ch in "abc"]
    t0 = _tm.time()
    recommend.ai_verify(cs, top=3)
    check("不同盘 3 候选全部验证", all(c["ai_pick"] for c in cs), True)
    check("不同盘真并发（峰值≥2）", slow.peak >= 2, True)
    check("并行总耗时 < 串行(0.45s)", _tm.time() - t0 < 0.4, True)

    # 2 个同盘候选 → 串行（峰值==1），防止并行各建 market_thesis 分裂市场观
    slow = _SlowFake(); recommend.requests = slow
    cs = [dict(_cand("0x" + ch * 40), market_question="同一个盘?") for ch in "de"]
    recommend.ai_verify(cs, top=2)
    check("同盘候选照常验证", all(c["ai_pick"] for c in cs), True)
    check("同盘串行（峰值==1）", slow.peak, 1)
finally:
    recommend.requests = _real

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
