"""Yengil jarayon ichidagi monitoring ko'rsatkichlari.

Bu modul tashqi xizmatga bog'lanmaydi: Render/FastAPI jarayoni ichida
so'rovlar, xatolar va o'yin natijalari bo'yicha tezkor hisob yuritadi.
Admin panel va ``/api/metrics`` shu ma'lumotlarni o'qiydi.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass
class MetricsSnapshot:
    started_at: float
    uptime_seconds: int
    requests: int
    errors: int
    games_finished: int
    coins_awarded: int
    active_users: int


class Metrics:
    """Thread-safe oddiy hisoblagichlar."""

    def __init__(self) -> None:
        self.started_at = time.time()
        self._lock = threading.Lock()
        self.requests = 0
        self.errors = 0
        self.games_finished = 0
        self.coins_awarded = 0
        self._users: set[int] = set()

    def request(self) -> None:
        with self._lock:
            self.requests += 1

    def error(self) -> None:
        with self._lock:
            self.errors += 1

    def user(self, user_id: int) -> None:
        if int(user_id) > 0:
            with self._lock:
                self._users.add(int(user_id))

    def game_finished(self, coins: int = 0) -> None:
        with self._lock:
            self.games_finished += 1
            self.coins_awarded += max(0, int(coins))

    def snapshot(self) -> MetricsSnapshot:
        with self._lock:
            return MetricsSnapshot(
                started_at=self.started_at,
                uptime_seconds=max(0, int(time.time() - self.started_at)),
                requests=self.requests,
                errors=self.errors,
                games_finished=self.games_finished,
                coins_awarded=self.coins_awarded,
                active_users=len(self._users),
            )


metrics = Metrics()

__all__ = ["Metrics", "MetricsSnapshot", "metrics"]
