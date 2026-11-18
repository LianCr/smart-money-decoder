"""
tests/test_visit.py — POST /visit 来源统计端点（2026-10-30）

契约：
  1. 合法事件 → 204，日志一行 "[visit] {json}"，带 src/ref/path/ua
  2. 未知 event 归一成 "load"；超长字段截断；非 JSON / 非对象 body 不炸
  3. 超出独立限流 → 仍 204（静默丢弃，不暴露限流给爬虫），且不写日志
  4. 不吃 /dashboard 的分析限流单例
零 key 零网络：TestClient 不进 with，不触发 lifespan。
"""

import json
import logging
import sys

sys.path.insert(0, ".")

from fastapi.testclient import TestClient

import api.main
import api.routes.meta as meta
import api.shared as shared
from core.ratelimit import RateLimiter

client = TestClient(api.main.app)

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


class Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


cap = Capture()
meta.LOG.addHandler(cap)
meta.LOG.setLevel(logging.INFO)


def visits():
    return [json.loads(l.split("[visit] ", 1)[1]) for l in cap.lines if "[visit] " in l]


print("合法事件")
meta._VISIT_LIMITER = RateLimiter(60, 60, 20000)
r = client.post("/visit", json={"event": "wallet", "src": "resume", "ref": "https://www.linkedin.com/",
                                "path": "/?src=resume", "detail": "0xabc"},
                headers={"user-agent": "Mozilla/5.0 Test"})
check("204", r.status_code, 204)
v = visits()[-1]
check("event", v["event"], "wallet")
check("src", v["src"], "resume")
check("ref", v["ref"], "https://www.linkedin.com/")
check("ua", v["ua"], "Mozilla/5.0 Test")

print("归一与截断")
client.post("/visit", json={"event": "rm -rf", "src": "x" * 500})
v = visits()[-1]
check("未知 event → load", v["event"], "load")
check("src 截到 40", len(v["src"]), 40)
r = client.post("/visit", content=b"not json", headers={"content-type": "text/plain"})
check("非 JSON → 204", r.status_code, 204)
check("非 JSON 仍记 load", visits()[-1]["event"], "load")
r = client.post("/visit", json=[1, 2, 3])
check("数组 body → 204", r.status_code, 204)

print("独立限流")
meta._VISIT_LIMITER = RateLimiter(1, 60, 20000)
before_shared = dict(shared._RATE_LIMITER._hits)
n0 = len(visits())
client.post("/visit", json={"event": "load"})
r = client.post("/visit", json={"event": "load"})
check("超限仍 204", r.status_code, 204)
check("超限不写日志", len(visits()) - n0, 1)
check("不吃 dashboard 限流", dict(shared._RATE_LIMITER._hits), before_shared)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
