"""Business contract: recommendation refresh is single-flight across app instances."""

import sys

sys.path.insert(0, ".")

from core.redis_coord import RedisCoordinator
from core.refresh_jobs import RecommendationRefresh


class FakeRedis:
    def __init__(self):
        self.values = {}

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    def get(self, key):
        return self.values.get(key)

    def eval(self, _script, _keys, key, token):
        if self.values.get(key) == token:
            self.values.pop(key, None)
            return 1
        return 0


class DeferredThread:
    pending = []

    def __init__(self, target, daemon):
        self.target = target
        self.daemon = daemon

    def start(self):
        self.pending.append(self.target)


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


redis = FakeRedis()
first = RecommendationRefresh(
    RedisCoordinator(redis, "test"), thread_factory=DeferredThread)
second = RecommendationRefresh(
    RedisCoordinator(redis, "test"), thread_factory=DeferredThread)
calls = []

check("first instance starts the expensive scan",
      first.start(lambda: calls.append("scan")), True)
check("second instance does not start a duplicate scan",
      second.start(lambda: calls.append("duplicate")), False)
check("only one background task was scheduled", len(DeferredThread.pending), 1)
check("other instances see shared running state",
      second.status()["running"], True)

DeferredThread.pending.pop()()
check("the winning instance ran the scan exactly once", calls, ["scan"])
check("completion is shared across instances", second.status()["running"], False)
check("successful completion has no error", second.status().get("error"), None)


def fail():
    raise RuntimeError("upstream failed")


check("a later refresh can start after lock release", first.start(fail), True)
DeferredThread.pending.pop()()
check("failure is shared with every instance",
      second.status().get("error"), "RuntimeError: upstream failed")
check("failure still clears running state", second.status()["running"], False)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
