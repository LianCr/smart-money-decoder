"""Business contract: duplicate wallet builds do not duplicate AI spending."""

import sys
import json
import tempfile
from pathlib import Path

sys.path.insert(0, ".")

from core.dashboard_jobs import DashboardSingleFlight, stale_while_building
from core.redis_coord import RedisCoordinator


class FakeRedis:
    def __init__(self):
        self.values = {}

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    def eval(self, _script, _keys, key, token):
        if self.values.get(key) == token:
            self.values.pop(key, None)
            return 1
        return 0


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
first = DashboardSingleFlight(RedisCoordinator(redis, "test"))
second = DashboardSingleFlight(RedisCoordinator(redis, "test"))

lease = first.enter("0xABC", "2026-07-30")
check("first request may build the wallet", lease.acquired, True)
check("wallet keys are case insensitive",
      second.enter("0xabc", "2026-07-30").acquired, False)
check("another wallet is not blocked",
      second.enter("0xdef", "2026-07-30").acquired, True)
check("another as-of snapshot is not blocked",
      second.enter("0xabc", "2026-07-29").acquired, True)

lease.release()
check("completed build allows the next refresh",
      second.enter("0xabc", "2026-07-30").acquired, True)

with tempfile.TemporaryDirectory() as td:
    cache = Path(td)
    old = {"wallet": "0xabc", "as_of": "2026-07-29", "reasoning": {"confidence": "HIGH"}}
    path = cache / "0xabc_2026-07-29.json"
    path.write_text(json.dumps(old), encoding="utf-8")
    response = stale_while_building(cache, "0xABC")
    check("duplicate request gets the last good board",
          response["as_of"], "2026-07-29")
    check("stale response clearly says a refresh is running",
          response["refresh_in_progress"], True)
    check("serve-time marker does not mutate the persisted truth",
          json.loads(path.read_text()).get("refresh_in_progress"), None)
    check("first-ever build has no fake stale result",
          stale_while_building(cache, "0xunknown"), None)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
