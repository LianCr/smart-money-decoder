"""Cross-process lifecycle for the expensive recommendation refresh."""

from __future__ import annotations

import threading
import time

from core.redis_coord import RedisCoordinator


class RecommendationRefresh:
    NAME = "recommendations"

    def __init__(self, coordinator: RedisCoordinator,
                 thread_factory=threading.Thread):
        self.coordinator = coordinator
        self.thread_factory = thread_factory

    def start(self, job) -> bool:
        lease = self.coordinator.acquire(self.NAME, ttl=30 * 60)
        if not lease.acquired:
            return False
        self.coordinator.set_status(
            self.NAME,
            {"running": True, "started_at": int(time.time()), "error": None},
            ttl=24 * 60 * 60)

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
                    ttl=24 * 60 * 60)
                lease.release()

        self.thread_factory(target=run, daemon=True).start()
        return True

    def status(self) -> dict:
        return self.coordinator.get_status(self.NAME) or {
            "running": False, "started_at": None, "error": None}
