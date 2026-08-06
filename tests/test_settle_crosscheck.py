"""
tests/test_settle_crosscheck.py — 574/575 结算交叉校验（T1 ④，monkeypatch 无网络）

背景：scorecard/回验 settle 依赖 574 `winning_outcome`——它是**未文档化字段**（坑表
2026-08-07），575 有文档化的 `winning_side` 可交叉。契约：
  1. 574 给 winner 且 575 一致 → 照常结算。
  2. 两者都在且矛盾 → 记入 conflicts、返回 None（保持 pending，**不猜**——如实标注）。
  3. 575 缺/空/挂 → 574 单裁（交叉是加固不是新硬依赖；实测 winning_side 常为 null）。
  4. 574 没给 winner → None，且不浪费 575 调用。
  5. 注入对象仍是 _resolve_574 本尊（test_api_endpoints 的 identity 契约不破）。
"""

import sys

sys.path.insert(0, ".")

import api.routes.scorecard as sc_route

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


class _FakeHz:
    """按 agent id 路由的 hz_call 替身：574 吐 winning_outcome、575 吐 winning_side。"""
    def __init__(self, wo, ws, raise_575=False):
        self.wo, self.ws, self.raise_575 = wo, ws, raise_575
        self.calls = []

    def __call__(self, agent, params, **kw):
        self.calls.append(agent)
        if agent == 575:
            if self.raise_575:
                raise RuntimeError("575 挂了")
            return {"data": [{"winning_side": self.ws}] if self.ws is not None else []}
        return {"data": [{"winning_outcome": self.wo}] if self.wo is not None else []}


_saved = sc_route.hz_call
try:
    # 1. 一致 → 结算
    fake = _FakeHz("Yes", "Yes")
    sc_route.hz_call = fake
    sc_route._SETTLE_CONFLICTS.clear()
    check("574=Yes · 575=Yes → 结算 Yes", sc_route._resolve_574("0xc1"), "Yes")
    check("无矛盾记录", sc_route._SETTLE_CONFLICTS, [])

    # 2. 矛盾 → None + conflicts（不猜）
    fake = _FakeHz("Yes", "No")
    sc_route.hz_call = fake
    sc_route._SETTLE_CONFLICTS.clear()
    check("🔴 574=Yes · 575=No → None（保持 pending 不猜）", sc_route._resolve_574("0xc2"), None)
    check("矛盾如实入册", sc_route._SETTLE_CONFLICTS,
          [{"cid": "0xc2", "winning_outcome_574": "Yes", "winning_side_575": "No"}])

    # 3. 575 空/null/挂 → 574 单裁
    fake = _FakeHz("No", None)
    sc_route.hz_call = fake
    check("575 无记录 → 574 单裁 No", sc_route._resolve_574("0xc3"), "No")
    fake = _FakeHz("No", "")
    sc_route.hz_call = fake
    check("575 winning_side 空串 → 574 单裁", sc_route._resolve_574("0xc4"), "No")
    fake = _FakeHz("Yes", "Yes", raise_575=True)
    sc_route.hz_call = fake
    sc_route._SETTLE_CONFLICTS.clear()
    check("575 抛异常 → 574 单裁（加固非硬依赖）", sc_route._resolve_574("0xc5"), "Yes")
    check("575 挂不算矛盾", sc_route._SETTLE_CONFLICTS, [])

    # 4. 574 没 winner → None 且不打 575（省调用）
    fake = _FakeHz(None, "Yes")
    sc_route.hz_call = fake
    check("574 无 winner → None", sc_route._resolve_574("0xc6"), None)
    check("574 无 winner 时不浪费 575 调用", 575 in fake.calls, False)
    fake = _FakeHz("Up", "No")          # 574 非 Yes/No 字面（实测有 Up/Down 盘）
    sc_route.hz_call = fake
    check("574 非 Yes/No 白名单 → None", sc_route._resolve_574("0xc7"), None)
    check("白名单外同样不打 575", 575 in fake.calls, False)
finally:
    sc_route.hz_call = _saved

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
