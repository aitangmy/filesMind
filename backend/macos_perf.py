from __future__ import annotations

import os
import platform
import re
import subprocess
import time
from typing import Any, Dict, Optional


def _run_command_output(command: list[str]) -> str:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=1.5,
            check=False,
        )
    except Exception:
        return ""
    stdout = (completed.stdout or "").strip()
    if stdout:
        return stdout
    return (completed.stderr or "").strip()


def _extract_first_int(output: str, key: str) -> Optional[int]:
    key_l = key.lower()
    for line in output.splitlines():
        if key_l not in line.lower():
            continue
        match = re.search(r"-?\d+", line)
        if not match:
            continue
        try:
            return int(match.group(0))
        except (TypeError, ValueError):
            continue
    return None


def _infer_thermal_level(
    thermal_level_raw: Optional[int],
    cpu_speed_limit: Optional[int],
    scheduler_limit: Optional[int],
    therm_output: str,
) -> str:
    if thermal_level_raw is not None:
        if thermal_level_raw >= 3:
            return "critical"
        if thermal_level_raw == 2:
            return "serious"
        if thermal_level_raw == 1:
            return "fair"
        return "nominal"

    limits = [x for x in (cpu_speed_limit, scheduler_limit) if isinstance(x, int)]
    if limits:
        min_limit = min(limits)
        if min_limit <= 50:
            return "critical"
        if min_limit <= 75:
            return "serious"
        if min_limit <= 90:
            return "fair"
        return "nominal"

    if "no thermal warning" in therm_output.lower():
        return "nominal"
    return "unknown"


def _detect_low_power_mode() -> Optional[bool]:
    output = _run_command_output(["pmset", "-g"])
    if not output:
        return None
    for line in output.splitlines():
        lowered = line.lower()
        if "lowpowermode" not in lowered:
            continue
        match = re.search(r"lowpowermode\s*[=\t ]\s*(\d+)", lowered)
        if match:
            return match.group(1) == "1"
        return None
    return None


def snapshot_macos_runtime_state() -> Dict[str, Any]:
    now_ms = int(time.time() * 1000)
    platform_name = platform.system().strip().lower()
    if platform_name != "darwin":
        return {
            "platform": platform_name or "unknown",
            "thermal_level": "unknown",
            "cpu_speed_limit": None,
            "scheduler_limit": None,
            "available_cpus": None,
            "low_power_mode": None,
            "source": "unsupported",
            "timestamp_ms": now_ms,
        }

    therm_output = _run_command_output(["pmset", "-g", "therm"])
    cpu_speed_limit = _extract_first_int(therm_output, "cpu_speed_limit")
    scheduler_limit = _extract_first_int(therm_output, "scheduler_limit")
    available_cpus = _extract_first_int(therm_output, "cpu_available_cpus")
    thermal_level_raw = _extract_first_int(therm_output, "thermal level")
    thermal_level = _infer_thermal_level(thermal_level_raw, cpu_speed_limit, scheduler_limit, therm_output)

    return {
        "platform": "macos",
        "thermal_level": thermal_level,
        "cpu_speed_limit": cpu_speed_limit,
        "scheduler_limit": scheduler_limit,
        "available_cpus": available_cpus,
        "low_power_mode": _detect_low_power_mode(),
        "source": "pmset",
        "timestamp_ms": now_ms,
    }
