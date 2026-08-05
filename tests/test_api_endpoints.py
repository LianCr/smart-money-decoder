"""
tests/test_api_endpoints.py — /dashboard 端点三态 + _dashboard_status 直测（T2.4 #4 销账）

🔴 本文件能存在的前提是 T2.3：import api.main 不再复制 seed / 打 GitHub（副作用全进
lifespan），TestClient 不进 `with` 就不触发 lifespan → 零 key 零网络可跑。
这是全仓第一批端点层测试——此前"绝不 import api.main"的取舍到此终结。

覆盖（T2.4 #4 原文三态 + 400）：
  1. 200 缓存命中（fixture 带 i18n_en key——缺它会触发真翻译懒自愈，探明的地雷）
  2. 400 垃圾地址（INVALID_ADDRESS：positions_hz 首句纯代码校验、网络之前）
  3. 202 构建中（单飞锁被占 + 无旧板 → retry_after）
  4. 刷新失败回退 stale 带 refresh_error（200 + 旧板 + 错误横幅字段）
  5. _dashboard_status 查表矩阵（欠账三年的 6 行映射，从 api.routes.dashboard 直测）
  6. 响应头 x-request-id（P1-12 中间件 wiring 的端点级验证）
  7. /confidence-replay 读写分离（T2.5）：裸 GET 纯读绝不 settle；?settle=1 注入 _resolve_574
"""

import json
import sys
import tempfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, ".")

from fastapi.testclient import TestClient

import services.dashboard_build as db
import api.main
from api.routes.dashboard import _dashboard_status

client = TestClient(api.main.app)   # 🔴 不进 with：不触发 lifespan（seed/GitHub 恢复留给真启动）

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


class patched:
    def __init__(self, **kw):
        self.kw = kw

    def __enter__(self):
        self.old = {k: getattr(db, k) for k in self.kw}
        for k, v in self.kw.items():
            setattr(db, k, v)

    def __exit__(self, *exc):
        for k, v in self.old.items():
            setattr(db, k, v)


def board_fixture(wallet, as_of):
    return {"wallet": wallet, "as_of": as_of, "reasoning": {"confidence": "中"},
            "i18n_en": {}}   # 带 i18n_en：缺它且 as_of>=2026-07-08 会触发真翻译懒自愈


TODAY = date.today().isoformat()

with tempfile.TemporaryDirectory() as tmp:
    cache = Path(tmp) / "dashboard"
    cache.mkdir(parents=True)

    print("态一：200 缓存命中")
    w1 = "0x" + "a" * 40
    (cache / f"{w1}_{TODAY}.json").write_text(json.dumps(board_fixture(w1, TODAY)), encoding="utf-8")
    with patched(DASHBOARD_CACHE=cache, attach_i18n_en=lambda d: False):
        r = client.get(f"/dashboard?wallet={w1}")
        check("缓存命中 → 200", r.status_code, 200)
        check("body 是板本体", r.json().get("wallet"), w1)
        check("x-request-id 响应头在场（P1-12）", bool(r.headers.get("x-request-id")), True)
        r2 = client.get(f"/dashboard?wallet={w1}", headers={"x-request-id": "endpointtest1"})
        check("入站 x-request-id 被原样回传", r2.headers.get("x-request-id"), "endpointtest1")

    print("态二：400 垃圾地址")
    with patched(DASHBOARD_CACHE=cache):
        r = client.get("/dashboard?wallet=nope")
        check("垃圾地址 → 400", r.status_code, 400)
        check("reason=INVALID_ADDRESS", r.json().get("error"), "INVALID_ADDRESS")
        check("带人话 message", bool(r.json().get("message")), True)

    print("态三：202 构建中（单飞锁被占、无旧板）")
    held = SimpleNamespace(enter=lambda w, a: SimpleNamespace(acquired=False, release=lambda: None))
    empty = Path(tmp) / "empty"
    empty.mkdir()
    with patched(DASHBOARD_CACHE=empty, _FLIGHT=held):
        r = client.get("/dashboard?wallet=" + "0x" + "b" * 40)
        check("构建中无旧板 → 202", r.status_code, 202)
        check("reason=DASHBOARD_BUILD_IN_PROGRESS", r.json().get("error"), "DASHBOARD_BUILD_IN_PROGRESS")
        check("retry_after=3", r.json().get("retry_after"), 3)

    print("态四：刷新失败回退 stale 带 refresh_error")
    w4 = "0x" + "c" * 40
    stale_cache = Path(tmp) / "stale"
    stale_cache.mkdir()
    (stale_cache / f"{w4}_2026-01-01.json").write_text(
        json.dumps(board_fixture(w4, "2026-01-01")), encoding="utf-8")
    with patched(DASHBOARD_CACHE=stale_cache, attach_i18n_en=lambda d: False,
                 _purge_wallet_caches=lambda *a, **k: 0,
                 get_top_political_position_hz=lambda w, as_of=None: {
                     "error": True, "reason": "API_TIMEOUT", "message": "上游超时"}):
        r = client.get(f"/dashboard?wallet={w4}&refresh=1")
        check("刷新失败 + 有旧板 → 200", r.status_code, 200)
        check("回退的是旧板", r.json().get("wallet"), w4)
        check("带 refresh_error 横幅字段", r.json().get("refresh_error"), "API_TIMEOUT: 上游超时")

    print("/confidence-replay 读写分离（T2.5）")
    import confidence_replay as _cr
    import api.routes.scorecard as _sc_route
    _saved_cr = {"settle": _cr.settle, "compute": _cr.compute}
    _settle_resolvers = []
    try:
        _cr.settle = lambda resolver: (_ for _ in ()).throw(AssertionError("裸 GET 不许 settle"))
        _cr.compute = lambda: {"total": 0, "marker": "pure-read"}
        r = client.get("/confidence-replay")
        check("裸 GET → 200 纯读（settle 未被调）", r.status_code, 200)
        check("返回 compute 的 payload", r.json().get("marker"), "pure-read")

        _cr.settle = lambda resolver: _settle_resolvers.append(resolver) or 0
        r = client.get("/confidence-replay?settle=1")
        check("?settle=1 → 200 且 settle 被调", (r.status_code, len(_settle_resolvers)), (200, 1))
        check("settle 注入的是 574 resolver", _settle_resolvers[0] is _sc_route._resolve_574, True)
    finally:
        _cr.settle, _cr.compute = _saved_cr["settle"], _saved_cr["compute"]

    print("_dashboard_status 查表矩阵（欠账销掉）")
    check("INVALID_ADDRESS → 400", _dashboard_status("INVALID_ADDRESS"), 400)
    for reason in sorted(db.NO_POSITION_REASONS):
        check(f"{reason} → 404", _dashboard_status(reason), 404)
    check("DASHBOARD_BUILD_IN_PROGRESS → 202", _dashboard_status("DASHBOARD_BUILD_IN_PROGRESS"), 202)
    check("其余上游失败 → 502", _dashboard_status("API_TIMEOUT"), 502)
    check("未知 reason 兜底 502", _dashboard_status("SOMETHING_NEW"), 502)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
