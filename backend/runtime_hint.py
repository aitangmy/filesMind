from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional

_HINT_LOCK = threading.Lock()
_LAST_HINT: Optional[Dict[str, Any]] = None
_LAST_HINT_MONOTONIC = 0.0


def _to_int_or_none(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed


def _normalize_thermal_level(value: Any) -> str:
    level = str(value or "").strip().lower()
    if level in {"nominal", "fair", "serious", "critical"}:
        return level
    return "unknown"


def _normalize_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    timestamp_ms = _to_int_or_none(payload.get("timestamp_ms"))
    if timestamp_ms is None:
        timestamp_ms = int(time.time() * 1000)

    return {
        "platform": str(payload.get("platform") or "unknown").strip().lower() or "unknown",
        "thermal_level": _normalize_thermal_level(payload.get("thermal_level")),
        "cpu_speed_limit": _to_int_or_none(payload.get("cpu_speed_limit")),
        "scheduler_limit": _to_int_or_none(payload.get("scheduler_limit")),
        "available_cpus": _to_int_or_none(payload.get("available_cpus")),
        "low_power_mode": bool(payload.get("low_power_mode", False)),
        "source": str(payload.get("source") or "desktop_hint").strip() or "desktop_hint",
        "timestamp_ms": int(timestamp_ms),
    }


def upsert_runtime_hint(payload: Dict[str, Any]) -> Dict[str, Any]:
    global _LAST_HINT, _LAST_HINT_MONOTONIC
    normalized = _normalize_payload(payload or {})
    now = time.monotonic()
    with _HINT_LOCK:
        _LAST_HINT = dict(normalized)
        _LAST_HINT_MONOTONIC = now
        saved = dict(_LAST_HINT)
        saved["hint_age_ms"] = 0
    return saved


def get_runtime_hint(max_age_seconds: float = 20.0) -> Optional[Dict[str, Any]]:
    with _HINT_LOCK:
        if _LAST_HINT is None:
            return None
        now = time.monotonic()
        age_seconds = max(0.0, now - _LAST_HINT_MONOTONIC)
        if max_age_seconds > 0 and age_seconds > float(max_age_seconds):
            return None
        hint = dict(_LAST_HINT)
    hint["hint_age_ms"] = int(age_seconds * 1000)
    return hint
