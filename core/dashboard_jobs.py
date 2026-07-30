"""Per-wallet distributed single-flight for expensive dashboard builds."""

import json

from core.cachefiles import newest_dated
from core.redis_coord import RedisCoordinator


class DashboardSingleFlight:
    def __init__(self, coordinator: RedisCoordinator):
        self.coordinator = coordinator

    def enter(self, wallet: str, as_of: str):
        key = f"dashboard:{wallet.strip().lower()}:{as_of}"
        return self.coordinator.acquire(key, ttl=10 * 60)


def resolve_contention(stale, refresh):
    """Decide what a request that LOST the single-flight lock gets served.

    A plain viewer is happy with the last good board (stale-while-revalidate).
    A refresh (the user's ↻ = real-time intent) must NOT settle for the
    pre-refresh board — return None so the caller responds 202 and the frontend
    polls until the actual rebuild lands.
    """
    if stale is not None and not refresh:
        return stale
    return None


def stale_while_building(cache_dir, wallet: str):
    """Return a marked copy of the last good board without mutating its file."""
    newest = newest_dated(cache_dir, wallet.strip().lower())
    if not newest:
        return None
    try:
        stale = json.loads(newest[0].read_text(encoding="utf-8"))
        stale["refresh_in_progress"] = True
        return stale
    except Exception:
        return None
