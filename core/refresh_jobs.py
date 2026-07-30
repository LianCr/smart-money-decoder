"""Cross-process lifecycle for the expensive recommendation refresh."""

from __future__ import annotations

import threading
import time

from core.redis_coord import RedisCoordinator


class RecommendationRefresh:
    NAME = "recommendations"
    LOCK_TTL = 30 * 60                      # a scan holds the lock at most this long
    # A hard-killed worker skips its finally; bound the 'running' status to just
    # past the lock lifetime so it self-clears near when a new refresh may start,
    # instead of lingering as a phantom "refreshing…" for a full day.
    RUNNING_STATUS_TTL = LOCK_TTL + 5 * 60
    DONE_STATUS_TTL = 24 * 60 * 60          # keep last success/error visible ~a day

    def __init__(self, coordinator: RedisCoordinator,
                 thread_factory=threading.Thread):
        self.coordinator = coordinator
        self.thread_factory = thread_factory

    def start(self, job) -> bool:
        lease = self.coordinator.acquire(self.NAME, ttl=self.LOCK_TTL)
        if not lease.acquired:
            return False
        self.coordinator.set_status(
            self.NAME,
            {"running": True, "started_at": int(time.time()), "error": None},
            ttl=self.RUNNING_STATUS_TTL)

        def run():
            error = None
            try:
                job()
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
            finally:
                self.coordinator.set_status(
                    self.NAME,
                    {"running": False, "started_at": None, "error": error},
                    ttl=self.DONE_STATUS_TTL)
                lease.release()

        self.thread_factory(target=run, daemon=True).start()
        return True

    def status(self) -> dict:
        return self.coordinator.get_status(self.NAME) or {
            "running": False, "started_at": None, "error": None}
