"""Optional Redis coordination for expensive work.

Redis stores only short-lived locks and job status. Business results remain in
the existing file/GitHub persistence layer, preserving one source of truth.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable


_LOCAL_GUARD = threading.Lock()
_LOCAL_LOCKS: dict[str, tuple[str, float]] = {}
_LOCAL_STATUS: dict[str, tuple[dict[str, Any], float]] = {}

_RELEASE_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
  return redis.call("del", KEYS[1])
end
return 0
"""


@dataclass
class Lease:
    acquired: bool
    _release: Callable[[], None]

    def release(self) -> None:
        if self.acquired:
            self._release()
            self.acquired = False

    def __enter__(self) -> "Lease":
        return self

    def __exit__(self, *_exc) -> None:
        self.release()


class RedisCoordinator:
    """Distributed coordination with an automatic process-local fallback."""

    def __init__(self, redis_client=None, namespace: str = "smart-money"):
        self.redis = redis_client
        self.namespace = namespace

    @classmethod
    def from_env(cls) -> "RedisCoordinator":
        url = os.environ.get("REDIS_URL")
        if not url:
            return cls()
        try:
            import redis

            return cls(redis.Redis.from_url(
                url, socket_connect_timeout=1, socket_timeout=1,
                decode_responses=True))
        except Exception:
            return cls()

    def _key(self, kind: str, name: str) -> str:
        return f"{self.namespace}:{kind}:{name}"

    def acquire(self, name: str, ttl: int) -> Lease:
        key = self._key("lock", name)
        token = uuid.uuid4().hex
        if self.redis is not None:
            try:
                acquired = bool(self.redis.set(key, token, nx=True, ex=ttl))
                return Lease(acquired, lambda: self._release_redis(key, token))
            except Exception:
                pass
        return self._acquire_local(key, token, ttl)

    def _release_redis(self, key: str, token: str) -> None:
        try:
            self.redis.eval(_RELEASE_SCRIPT, 1, key, token)
        except Exception:
            pass

    def _acquire_local(self, key: str, token: str, ttl: int) -> Lease:
        now = time.time()
        with _LOCAL_GUARD:
            current = _LOCAL_LOCKS.get(key)
            if current and current[1] > now:
                return Lease(False, lambda: None)
            _LOCAL_LOCKS[key] = (token, now + ttl)

        def release() -> None:
            with _LOCAL_GUARD:
                if _LOCAL_LOCKS.get(key, (None,))[0] == token:
                    _LOCAL_LOCKS.pop(key, None)

        return Lease(True, release)

    def set_status(self, name: str, value: dict[str, Any], ttl: int) -> None:
        key = self._key("status", name)
        if self.redis is not None:
            try:
                self.redis.set(key, json.dumps(value), ex=ttl)
                return
            except Exception:
                pass
        with _LOCAL_GUARD:
            _LOCAL_STATUS[key] = (dict(value), time.time() + ttl)

    def get_status(self, name: str) -> dict[str, Any] | None:
        key = self._key("status", name)
        if self.redis is not None:
            try:
                raw = self.redis.get(key)
                if raw is None:
                    return None
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                return json.loads(raw)
            except Exception:
                pass
        with _LOCAL_GUARD:
            item = _LOCAL_STATUS.get(key)
            if not item:
                return None
            value, expires_at = item
            if expires_at <= time.time():
                _LOCAL_STATUS.pop(key, None)
                return None
            return dict(value)


coordinator = RedisCoordinator.from_env()
