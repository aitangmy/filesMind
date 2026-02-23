from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

from macos_perf import snapshot_macos_runtime_state
from runtime_hint import get_runtime_hint

logger = logging.getLogger("FilesMind")

_ENV_PARSE_WORKERS = "FILESMIND_PARSE_WORKERS"
_DEFAULT_REFRESH_INTERVAL_SECONDS = 5.0


def resolve_base_parse_workers() -> int:
    raw = os.getenv(_ENV_PARSE_WORKERS)
    if raw:
        try:
            parsed = int(raw)
            if parsed > 0:
                return parsed
        except ValueError:
            logger.warning(f"{_ENV_PARSE_WORKERS}={raw!r} 非法，将使用默认值")
    cpu_count = os.cpu_count() or 2
    return max(1, min(4, cpu_count - 1))


def compute_recommended_parse_limit(base_limit: int, runtime: Dict[str, Any]) -> int:
    base = max(1, int(base_limit))
    thermal_level = str(runtime.get("thermal_level", "unknown") or "unknown").strip().lower()
    low_power_mode = bool(runtime.get("low_power_mode", False))

    if thermal_level == "critical":
        limit = 1
    elif thermal_level == "serious":
        limit = min(base, 2)
    elif thermal_level == "fair":
        limit = max(1, min(base, base - 1))
    else:
        limit = base

    cpu_speed_limit = runtime.get("cpu_speed_limit")
    if isinstance(cpu_speed_limit, int):
        if cpu_speed_limit <= 50:
            limit = min(limit, 1)
        elif cpu_speed_limit <= 70:
            limit = min(limit, 2)
        elif cpu_speed_limit <= 85:
            limit = min(limit, max(1, base - 1))

    if low_power_mode:
        limit = min(limit, max(1, base // 2))

    return max(1, min(base, limit))


class AdaptiveParseLimiter:
    def __init__(self, base_limit: int, refresh_interval_seconds: float = _DEFAULT_REFRESH_INTERVAL_SECONDS):
        self._base_limit = max(1, int(base_limit))
        self._limit = self._base_limit
        self._inflight = 0
        self._refresh_interval_seconds = max(1.0, float(refresh_interval_seconds))
        self._last_refresh_monotonic = 0.0
        self._last_runtime: Dict[str, Any] = {
            "platform": "unknown",
            "thermal_level": "unknown",
            "low_power_mode": None,
            "source": "init",
        }
        self._condition = asyncio.Condition()
        self._refresh_lock = asyncio.Lock()

    @property
    def base_limit(self) -> int:
        return self._base_limit

    @property
    def current_limit(self) -> int:
        return self._limit

    def set_base_limit(self, value: int) -> None:
        self._base_limit = max(1, int(value))
        self._limit = max(1, min(self._limit, self._base_limit))

    def snapshot(self) -> Dict[str, Any]:
        return {
            "base_limit": int(self._base_limit),
            "current_limit": int(self._limit),
            "inflight": int(self._inflight),
            "runtime": dict(self._last_runtime),
        }

    async def refresh_runtime_if_needed(self, force: bool = False) -> Dict[str, Any]:
        now = time.monotonic()
        if not force and (now - self._last_refresh_monotonic) < self._refresh_interval_seconds:
            return self.snapshot()

        async with self._refresh_lock:
            now = time.monotonic()
            if not force and (now - self._last_refresh_monotonic) < self._refresh_interval_seconds:
                return self.snapshot()

            hint_state = get_runtime_hint(max_age_seconds=max(12.0, self._refresh_interval_seconds * 4.0))
            runtime_state = dict(hint_state) if hint_state else await asyncio.to_thread(snapshot_macos_runtime_state)
            next_limit = compute_recommended_parse_limit(self._base_limit, runtime_state)

            async with self._condition:
                self._last_runtime = dict(runtime_state)
                self._last_refresh_monotonic = now
                if next_limit != self._limit:
                    old_limit = self._limit
                    self._limit = next_limit
                    self._condition.notify_all()
                    logger.info(
                        f"parse limiter adjusted: {old_limit} -> {next_limit}, "
                        f"thermal={runtime_state.get('thermal_level')}, "
                        f"cpu_limit={runtime_state.get('cpu_speed_limit')}, "
                        f"low_power={runtime_state.get('low_power_mode')}"
                    )

            return self.snapshot()

    async def acquire(self) -> None:
        await self.refresh_runtime_if_needed()
        async with self._condition:
            while self._inflight >= self._limit:
                await self._condition.wait()
            self._inflight += 1

    async def release(self) -> None:
        async with self._condition:
            self._inflight = max(0, self._inflight - 1)
            self._condition.notify_all()

    @asynccontextmanager
    async def slot(self):
        await self.acquire()
        try:
            yield self.snapshot()
        finally:
            await self.release()


_parse_limiter_singleton: Optional[AdaptiveParseLimiter] = None
_parse_limiter_guard = threading.Lock()


def get_parse_limiter(base_limit: Optional[int] = None) -> AdaptiveParseLimiter:
    global _parse_limiter_singleton

    resolved_base = max(1, int(base_limit)) if base_limit is not None else resolve_base_parse_workers()
    with _parse_limiter_guard:
        if _parse_limiter_singleton is None:
            _parse_limiter_singleton = AdaptiveParseLimiter(resolved_base)
        else:
            _parse_limiter_singleton.set_base_limit(resolved_base)
    return _parse_limiter_singleton
