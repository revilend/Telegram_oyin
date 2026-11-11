"""Jarayon ichidagi tezkor kesh va umumiy Supabase ulanish havzasi.

Ikki vazifa:

* :class:`TTLCache` — 60 sekundlik in-memory kesh. Minglab o'yinchi bir
  vaqtda tugma bosganda ham har bir bosish Supabase so'rovi bo'lmaydi.
* :func:`create_supabase_client` — butun jarayon uchun **bitta** persistent
  ``httpx`` sessiyasi (keep-alive + connection pool) bilan Supabase klienti.
  Har bir store o'z klientini qayta ochmaydi, ulanish qayta ishlatiladi.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Generic, TypeVar

T = TypeVar("T")

__all__ = [
    "TTLCache",
    "create_supabase_client",
    "shared_http_client",
    "cache_stats",
]


class TTLCache(Generic[T]):
    """Thread-safe TTL kesh: eski yozuvlar so'rov paytida o'chiriladi.

    ``max_size`` dan oshsa eng eski yozuv chiqarib yuboriladi — xotira
    o'sib ketmaydi (ommaviy yuklamada muhim).
    """

    __slots__ = ("ttl", "max_size", "_data", "_lock", "hits", "misses")

    def __init__(self, ttl: float = 60.0, max_size: int = 50_000) -> None:
        self.ttl = float(ttl)
        self.max_size = max(1, int(max_size))
        self._data: dict[Any, tuple[float, T]] = {}
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: Any) -> T | None:
        stamp = time.monotonic()
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                self.misses += 1
                return None
            created, value = entry
            if stamp - created > self.ttl:
                self._data.pop(key, None)
                self.misses += 1
                return None
            self.hits += 1
            return value

    def set(self, key: Any, value: T) -> None:
        with self._lock:
            if key not in self._data and len(self._data) >= self.max_size:
                # Eng eski yozuvni chiqaramiz (dict tartibi = qo'shilish tartibi).
                oldest = next(iter(self._data), None)
                if oldest is not None:
                    self._data.pop(oldest, None)
            self._data[key] = (time.monotonic(), value)

    def delete(self, key: Any) -> None:
        with self._lock:
            self._data.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self.hits = 0
            self.misses = 0

    def __contains__(self, key: Any) -> bool:
        return self.get(key) is not None

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)


# ----------------------------------------------------------------------
# Supabase: umumiy persistent sessiya (connection pool reuse)
# ----------------------------------------------------------------------
_http_lock = threading.Lock()
_http_client: Any | None = None


def shared_http_client() -> Any:
    """Butun jarayon uchun bitta keep-alive ``httpx.Client``.

    Supabase'ning postgrest/auth klientlari shu sessiyani bo'lishadi:
    har so'rovda TLS handshake va yangi ulanish bo'lmaydi, ulanishlar
    qayta ishlatiladi (connection pooling).
    """
    global _http_client
    if _http_client is None:
        with _http_lock:
            if _http_client is None:
                import httpx

                _http_client = httpx.Client(
                    limits=httpx.Limits(
                        max_connections=200,
                        max_keepalive_connections=50,
                        keepalive_expiry=60.0,
                    ),
                    # DB osilib qolsa so'rov 10 s dan keyin uziladi —
                    # bot va Mini App hech qachon muzlab qolmaydi.
                    timeout=httpx.Timeout(10.0, connect=5.0),
                    headers={"Connection": "keep-alive"},
                )
    return _http_client


def create_supabase_client(url: str, key: str) -> Any:
    """Persistent sessiyali Supabase klienti (eski versiyalar bilan mos)."""
    from supabase import create_client

    try:
        from supabase import ClientOptions

        return create_client(
            url,
            key,
            options=ClientOptions(
                httpx_client=shared_http_client(),
                postgrest_client_timeout=10,
            ),
        )
    except (ImportError, TypeError):  # eski supabase-py
        return create_client(url, key)


def cache_stats(cache: TTLCache[Any]) -> dict[str, Any]:
    """Kesh samaradorligi (diagnostika/log uchun)."""
    total = cache.hits + cache.misses
    return {
        "size": len(cache),
        "hits": cache.hits,
        "misses": cache.misses,
        "hit_rate": round(cache.hits / total, 3) if total else 0.0,
        "ttl": cache.ttl,
    }
