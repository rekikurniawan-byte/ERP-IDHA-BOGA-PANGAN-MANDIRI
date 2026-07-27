"""Small in-process TTL cache for read-only UI context payloads."""

from __future__ import annotations

from threading import RLock
from time import monotonic
from typing import Callable, Hashable, TypeVar


T = TypeVar("T")

_CACHE: dict[Hashable, tuple[float, object]] = {}
_LOCK = RLock()


def get_cached_value(key: Hashable, factory: Callable[[], T], *, ttl_seconds: int = 30) -> T:
    now = monotonic()
    with _LOCK:
        cached = _CACHE.get(key)
        if cached and cached[0] > now:
            return cached[1]  # type: ignore[return-value]

    value = factory()
    expires_at = now + max(1, int(ttl_seconds))
    with _LOCK:
        _CACHE[key] = (expires_at, value)
    return value


def clear_cache(prefix: Hashable | None = None) -> None:
    with _LOCK:
        if prefix is None:
            _CACHE.clear()
            return

        keys = [key for key in _CACHE if isinstance(key, tuple) and key and key[0] == prefix]
        for key in keys:
            _CACHE.pop(key, None)
