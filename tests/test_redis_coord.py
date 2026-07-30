"""Redis coordination contracts: distributed single-flight with safe local fallback."""

import sys
import time

sys.path.insert(0, ".")

from core.redis_coord import RedisCoordinator


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.available = True

    def set(self, key, value, nx=False, ex=None):
        if not self.available:
            raise ConnectionError("redis unavailable")
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    def get(self, key):
        if not self.available:
            raise ConnectionError("redis unavailable")
        return self.values.get(key)

    def delete(self, key):
        if not self.available:
            raise ConnectionError("redis unavailable")
        return self.values.pop(key, None) is not None

    def eval(self, _script, _keys, key, token):
        if not self.available:
            raise ConnectionError("redis unavailable")
        if self.values.get(key) == token:
            self.delete(key)
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


# Two app instances sharing Redis must not run the same expensive job.
redis = FakeRedis()
first = RedisCoordinator(redis_client=redis, namespace="test")
second = RedisCoordinator(redis_client=redis, namespace="test")
lease = first.acquire("recommendations", ttl=60)
check("first instance acquires distributed lock", lease.acquired, True)
check("second instance is rejected while lock is held",
      second.acquire("recommendations", ttl=60).acquired, False)
lease.release()
check("release lets another instance acquire",
      second.acquire("recommendations", ttl=60).acquired, True)

# Only the owner token may release a distributed lock.
redis = FakeRedis()
owner = RedisCoordinator(redis_client=redis, namespace="test")
lease = owner.acquire("dashboard:0xabc", ttl=60)
redis.values["test:lock:dashboard:0xabc"] = "someone-else"
lease.release()
check("stale owner cannot release a newer owner's lock",
      redis.get("test:lock:dashboard:0xabc"), "someone-else")

# Job status is shared JSON, not business-result storage.
redis = FakeRedis()
writer = RedisCoordinator(redis_client=redis, namespace="test")
reader = RedisCoordinator(redis_client=redis, namespace="test")
writer.set_status("recommendations", {"running": True, "started_at": 123}, ttl=30)
check("job status is visible across instances",
      reader.get_status("recommendations"), {"running": True, "started_at": 123})

# Redis outages degrade to a process-local lock instead of breaking the product.
redis = FakeRedis()
redis.available = False
fallback = RedisCoordinator(redis_client=redis, namespace="test")
local_lease = fallback.acquire("recommendations", ttl=60)
check("redis outage falls back to local coordination", local_lease.acquired, True)
check("local fallback still prevents duplicate work",
      fallback.acquire("recommendations", ttl=60).acquired, False)
local_lease.release()
check("local fallback lock can be released",
      fallback.acquire("recommendations", ttl=60).acquired, True)

fallback.set_status("recommendations", {"running": True}, ttl=1)
check("status also falls back locally",
      fallback.get_status("recommendations"), {"running": True})
time.sleep(1.05)
check("local status respects TTL", fallback.get_status("recommendations"), None)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
