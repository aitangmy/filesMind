#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional

import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from parse_concurrency import compute_recommended_parse_limit, resolve_base_parse_workers  # noqa: E402
from parser_service import process_pdf_safely  # noqa: E402


LEGACY_POLL_INTERVAL_MS = 1500
THERMAL_POLLING_PROFILE = {
    "nominal": 1400,
    "fair": 1800,
    "serious": 2400,
    "critical": 3200,
    "unknown": 1700,
}
THERMAL_PDF_PROFILE = {
    "nominal": {"preload_max_pages": 1500, "preload_concurrency": 2},
    "fair": {"preload_max_pages": 900, "preload_concurrency": 2},
    "serious": {"preload_max_pages": 420, "preload_concurrency": 1},
    "critical": {"preload_max_pages": 180, "preload_concurrency": 1},
    "unknown": {"preload_max_pages": 800, "preload_concurrency": 2},
}
THERMAL_PDF_WINDOW_PROFILE = {
    "nominal": {"max_mounted_pages": 8, "buffer_pages": 2},
    "fair": {"max_mounted_pages": 7, "buffer_pages": 2},
    "serious": {"max_mounted_pages": 5, "buffer_pages": 1},
    "critical": {"max_mounted_pages": 4, "buffer_pages": 1},
    "unknown": {"max_mounted_pages": 6, "buffer_pages": 1},
}
P1_STAGNANT_STEP = 0.18
P1_STAGNANT_MAX_TICKS = 6
P1_POLL_MAX_MS = 6500
LEGACY_RUNTIME_MONITOR_INTERVAL_MS = 5000
P1_RUNTIME_MONITOR_ACTIVE_INTERVAL_MS = 5000
P1_RUNTIME_MONITOR_IDLE_INTERVAL_MS = 20000
P1_RUNTIME_MONITOR_IDLE_LOW_POWER_INTERVAL_MS = 30000


@dataclass
class ParseModeResult:
    mode: str
    jobs: int
    concurrency_limit: int
    total_seconds: float
    avg_job_seconds: float
    min_job_seconds: float
    max_job_seconds: float
    success_jobs: int
    failed_jobs: int
    errors: List[str]


def normalize_thermal_level(value: str) -> str:
    text = str(value or "").strip().lower()
    if text in {"nominal", "fair", "serious", "critical"}:
        return text
    return "unknown"


def p0_poll_interval_ms(thermal_level: str, low_power_mode: bool) -> int:
    level = normalize_thermal_level(thermal_level)
    interval = THERMAL_POLLING_PROFILE.get(level, THERMAL_POLLING_PROFILE["unknown"])
    if low_power_mode:
        interval = int(round(interval * 1.25))
    return max(900, min(4500, interval))


def p0_pdf_profile(thermal_level: str, low_power_mode: bool) -> Dict[str, int]:
    level = normalize_thermal_level(thermal_level)
    profile = dict(THERMAL_PDF_PROFILE.get(level, THERMAL_PDF_PROFILE["unknown"]))
    if low_power_mode:
        profile["preload_max_pages"] = max(120, int(round(profile["preload_max_pages"] * 0.7)))
        profile["preload_concurrency"] = max(1, profile["preload_concurrency"] - 1)
    return profile


def p1_pdf_window_profile(thermal_level: str, low_power_mode: bool) -> Dict[str, int]:
    level = normalize_thermal_level(thermal_level)
    profile = dict(THERMAL_PDF_WINDOW_PROFILE.get(level, THERMAL_PDF_WINDOW_PROFILE["unknown"]))
    if low_power_mode:
        profile["max_mounted_pages"] = max(3, int(profile["max_mounted_pages"]) - 1)
    return profile


def _p1_processing_poll_interval_ms(base_interval_ms: int, stagnant_ticks: int, low_power_mode: bool) -> int:
    boost = 1.0 + min(P1_STAGNANT_MAX_TICKS, max(0, stagnant_ticks)) * P1_STAGNANT_STEP
    if low_power_mode:
        boost *= 1.15
    interval = int(round(base_interval_ms * boost))
    return max(900, min(P1_POLL_MAX_MS, interval))


def _simulate_request_count(duration_seconds: float, interval_seconds: float) -> float:
    if duration_seconds <= 0 or interval_seconds <= 0:
        return 0.0
    return duration_seconds / interval_seconds


def p1_poll_request_estimate(
    duration_seconds: int,
    thermal_level: str,
    low_power_mode: bool,
    stagnant_seconds: int,
) -> float:
    total_seconds = max(1, int(duration_seconds))
    stagnant = max(0, min(total_seconds, int(stagnant_seconds)))
    active_seconds = total_seconds - stagnant

    base_interval_ms = p0_poll_interval_ms(thermal_level, low_power_mode)
    base_interval_seconds = base_interval_ms / 1000.0

    requests = _simulate_request_count(active_seconds, base_interval_seconds)
    elapsed = 0.0
    stagnant_ticks = 0
    while elapsed < stagnant:
        interval_ms = _p1_processing_poll_interval_ms(base_interval_ms, stagnant_ticks, low_power_mode)
        requests += 1.0
        elapsed += interval_ms / 1000.0
        stagnant_ticks += 1
    return requests


def polling_comparison(
    duration_seconds: int,
    thermal_level: str,
    low_power_mode: bool,
    stagnant_seconds: int,
) -> Dict[str, float]:
    legacy_requests = _simulate_request_count(duration_seconds, LEGACY_POLL_INTERVAL_MS / 1000.0)
    p0_interval_ms = p0_poll_interval_ms(thermal_level, low_power_mode)
    p0_requests = _simulate_request_count(duration_seconds, p0_interval_ms / 1000.0)
    p1_requests = p1_poll_request_estimate(duration_seconds, thermal_level, low_power_mode, stagnant_seconds)

    p0_delta_vs_legacy = p0_requests - legacy_requests
    p1_delta_vs_legacy = p1_requests - legacy_requests
    p1_delta_vs_p0 = p1_requests - p0_requests

    return {
        "duration_seconds": float(duration_seconds),
        "stagnant_seconds": float(stagnant_seconds),
        "legacy_interval_ms": float(LEGACY_POLL_INTERVAL_MS),
        "p0_base_interval_ms": float(p0_interval_ms),
        "legacy_requests": round(legacy_requests, 2),
        "p0_requests": round(p0_requests, 2),
        "p1_requests": round(p1_requests, 2),
        "p0_delta_vs_legacy": round(p0_delta_vs_legacy, 2),
        "p1_delta_vs_legacy": round(p1_delta_vs_legacy, 2),
        "p1_delta_vs_p0": round(p1_delta_vs_p0, 2),
        "p0_delta_pct_vs_legacy": round((p0_delta_vs_legacy / legacy_requests * 100.0), 2) if legacy_requests else 0.0,
        "p1_delta_pct_vs_legacy": round((p1_delta_vs_legacy / legacy_requests * 100.0), 2) if legacy_requests else 0.0,
        "p1_delta_pct_vs_p0": round((p1_delta_vs_p0 / p0_requests * 100.0), 2) if p0_requests else 0.0,
    }


def runtime_monitor_comparison(
    processing_seconds: int,
    idle_seconds: int,
    low_power_mode: bool,
) -> Dict[str, float]:
    processing = max(0, int(processing_seconds))
    idle = max(0, int(idle_seconds))
    total = processing + idle

    legacy_requests = _simulate_request_count(total, LEGACY_RUNTIME_MONITOR_INTERVAL_MS / 1000.0)
    p0_requests = legacy_requests

    idle_interval_ms = (
        P1_RUNTIME_MONITOR_IDLE_LOW_POWER_INTERVAL_MS
        if low_power_mode
        else P1_RUNTIME_MONITOR_IDLE_INTERVAL_MS
    )
    p1_processing_requests = _simulate_request_count(processing, P1_RUNTIME_MONITOR_ACTIVE_INTERVAL_MS / 1000.0)
    p1_idle_requests = _simulate_request_count(idle, idle_interval_ms / 1000.0)
    p1_requests = p1_processing_requests + p1_idle_requests

    delta_vs_legacy = p1_requests - legacy_requests
    delta_vs_p0 = p1_requests - p0_requests
    return {
        "processing_seconds": float(processing),
        "idle_seconds": float(idle),
        "legacy_interval_ms": float(LEGACY_RUNTIME_MONITOR_INTERVAL_MS),
        "p1_active_interval_ms": float(P1_RUNTIME_MONITOR_ACTIVE_INTERVAL_MS),
        "p1_idle_interval_ms": float(idle_interval_ms),
        "legacy_requests": round(legacy_requests, 2),
        "p0_requests": round(p0_requests, 2),
        "p1_requests": round(p1_requests, 2),
        "p1_delta_vs_legacy": round(delta_vs_legacy, 2),
        "p1_delta_vs_p0": round(delta_vs_p0, 2),
        "p1_delta_pct_vs_legacy": round((delta_vs_legacy / legacy_requests * 100.0), 2) if legacy_requests else 0.0,
        "p1_delta_pct_vs_p0": round((delta_vs_p0 / p0_requests * 100.0), 2) if p0_requests else 0.0,
    }


def resolve_mode_concurrency(mode: str, base_workers: int, low_power_mode: bool) -> int:
    normalized = str(mode or "").strip().lower()
    if normalized in {"legacy", "legacy_fixed", "fixed"}:
        return base_workers
    runtime_state = {
        "thermal_level": normalize_thermal_level(normalized),
        "low_power_mode": bool(low_power_mode),
    }
    return compute_recommended_parse_limit(base_workers, runtime_state)


async def run_parse_mode(
    mode: str,
    pdf_path: Path,
    output_root: Path,
    jobs: int,
    parser_backend: Optional[str],
    base_workers: int,
    low_power_mode: bool,
    keep_outputs: bool,
) -> ParseModeResult:
    concurrency_limit = resolve_mode_concurrency(mode, base_workers, low_power_mode)
    semaphore = asyncio.Semaphore(concurrency_limit)
    job_durations: List[float] = []
    errors: List[str] = []
    mode_output_root = output_root / f"mode_{mode}"
    mode_output_root.mkdir(parents=True, exist_ok=True)

    async def _one_job(index: int):
        nonlocal job_durations, errors
        async with semaphore:
            started = time.perf_counter()
            file_id = f"perf_{mode}_{index}_{uuid.uuid4().hex[:8]}"
            try:
                await asyncio.to_thread(
                    process_pdf_safely,
                    str(pdf_path),
                    str(mode_output_root),
                    file_id,
                    True,
                    parser_backend,
                )
                elapsed = time.perf_counter() - started
                job_durations.append(elapsed)
            except Exception as exc:  # pragma: no cover - best effort capture
                elapsed = time.perf_counter() - started
                job_durations.append(elapsed)
                errors.append(f"job#{index}: {exc}")

    started_total = time.perf_counter()
    await asyncio.gather(*(_one_job(i) for i in range(jobs)))
    total_seconds = time.perf_counter() - started_total

    if not keep_outputs:
        shutil.rmtree(mode_output_root, ignore_errors=True)

    success_jobs = max(0, jobs - len(errors))
    failed_jobs = len(errors)
    avg_job_seconds = (sum(job_durations) / len(job_durations)) if job_durations else 0.0
    min_job_seconds = min(job_durations) if job_durations else 0.0
    max_job_seconds = max(job_durations) if job_durations else 0.0

    return ParseModeResult(
        mode=mode,
        jobs=jobs,
        concurrency_limit=concurrency_limit,
        total_seconds=round(total_seconds, 3),
        avg_job_seconds=round(avg_job_seconds, 3),
        min_job_seconds=round(min_job_seconds, 3),
        max_job_seconds=round(max_job_seconds, 3),
        success_jobs=success_jobs,
        failed_jobs=failed_jobs,
        errors=errors[:20],
    )


async def run_parse_benchmark(
    pdf_path: Path,
    modes: List[str],
    jobs: int,
    parser_backend: Optional[str],
    low_power_mode: bool,
    keep_outputs: bool,
) -> Dict[str, object]:
    base_workers = resolve_base_parse_workers()
    output_root = Path(tempfile.mkdtemp(prefix="filesmind_perf_"))
    try:
        results: List[ParseModeResult] = []
        for mode in modes:
            result = await run_parse_mode(
                mode=mode,
                pdf_path=pdf_path,
                output_root=output_root,
                jobs=jobs,
                parser_backend=parser_backend,
                base_workers=base_workers,
                low_power_mode=low_power_mode,
                keep_outputs=keep_outputs,
            )
            results.append(result)

        legacy = next((r for r in results if r.mode in {"legacy", "legacy_fixed", "fixed"}), None)
        comparison = {}
        if legacy:
            for item in results:
                if item is legacy:
                    continue
                if legacy.total_seconds > 0:
                    delta_pct = (item.total_seconds - legacy.total_seconds) / legacy.total_seconds * 100.0
                else:
                    delta_pct = 0.0
                comparison[item.mode] = {
                    "total_seconds_delta_vs_legacy": round(item.total_seconds - legacy.total_seconds, 3),
                    "total_seconds_delta_pct_vs_legacy": round(delta_pct, 2),
                }

        return {
            "pdf_path": str(pdf_path),
            "jobs": jobs,
            "base_workers": base_workers,
            "parser_backend": parser_backend or "runtime_default",
            "low_power_mode": low_power_mode,
            "results": [asdict(r) for r in results],
            "comparison_vs_legacy": comparison,
        }
    finally:
        if not keep_outputs:
            shutil.rmtree(output_root, ignore_errors=True)


def print_summary(report: Dict[str, object]) -> None:
    print("\n== Polling Comparison ==")
    polling = report["polling"]
    print(
        f"duration={polling['duration_seconds']:.0f}s "
        f"stagnant={polling['stagnant_seconds']:.0f}s "
        f"legacy={polling['legacy_requests']}/run "
        f"p0={polling['p0_requests']}/run "
        f"p1={polling['p1_requests']}/run"
    )
    print(
        f"p0 vs legacy: {polling['p0_delta_vs_legacy']} ({polling['p0_delta_pct_vs_legacy']}%), "
        f"p1 vs legacy: {polling['p1_delta_vs_legacy']} ({polling['p1_delta_pct_vs_legacy']}%), "
        f"p1 vs p0: {polling['p1_delta_vs_p0']} ({polling['p1_delta_pct_vs_p0']}%)"
    )

    print("\n== Runtime Monitor Comparison ==")
    monitor = report["runtime_monitor"]
    print(
        f"processing={monitor['processing_seconds']:.0f}s "
        f"idle={monitor['idle_seconds']:.0f}s "
        f"legacy={monitor['legacy_requests']}/run "
        f"p1={monitor['p1_requests']}/run"
    )
    print(
        f"p1 vs legacy: {monitor['p1_delta_vs_legacy']} ({monitor['p1_delta_pct_vs_legacy']}%), "
        f"p1 vs p0: {monitor['p1_delta_vs_p0']} ({monitor['p1_delta_pct_vs_p0']}%)"
    )

    print("\n== PDF Preload Comparison ==")
    pdf_profile = report["pdf_preload"]
    print(
        f"legacy: max_pages={pdf_profile['legacy']['preload_max_pages']} concurrency={pdf_profile['legacy']['preload_concurrency']}"
    )
    print(
        f"p0/p1: max_pages={pdf_profile['p0']['preload_max_pages']} concurrency={pdf_profile['p0']['preload_concurrency']}"
    )

    print("\n== PDF Window Comparison ==")
    window_profile = report["pdf_window"]
    print(
        f"legacy/p0: mounted={window_profile['legacy']['max_mounted_pages']} buffer={window_profile['legacy']['buffer_pages']}"
    )
    print(
        f"p1: mounted={window_profile['p1']['max_mounted_pages']} buffer={window_profile['p1']['buffer_pages']}"
    )

    parse = report.get("parse_benchmark")
    if parse:
        print("\n== Parse Benchmark ==")
        for row in parse["results"]:
            print(
                f"{row['mode']:>10} "
                f"limit={row['concurrency_limit']} "
                f"total={row['total_seconds']}s "
                f"avg={row['avg_job_seconds']}s "
                f"ok={row['success_jobs']} fail={row['failed_jobs']}"
            )


def build_report(
    thermal_level: str,
    low_power_mode: bool,
    duration_seconds: int,
    idle_seconds: int,
    stagnant_seconds: int,
    parse_report: Optional[Dict[str, object]],
) -> Dict[str, object]:
    return {
        "timestamp_unix": int(time.time()),
        "thermal_level": normalize_thermal_level(thermal_level),
        "low_power_mode": bool(low_power_mode),
        "polling": polling_comparison(duration_seconds, thermal_level, low_power_mode, stagnant_seconds),
        "runtime_monitor": runtime_monitor_comparison(duration_seconds, idle_seconds, low_power_mode),
        "pdf_preload": {
            "legacy": {"preload_max_pages": 1500, "preload_concurrency": 2},
            "p0": p0_pdf_profile(thermal_level, low_power_mode),
            "p1": p0_pdf_profile(thermal_level, low_power_mode),
        },
        "pdf_window": {
            "legacy": {"max_mounted_pages": 8, "buffer_pages": 2},
            "p0": {"max_mounted_pages": 8, "buffer_pages": 2},
            "p1": p1_pdf_window_profile(thermal_level, low_power_mode),
        },
        "parse_benchmark": parse_report,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="FilesMind P0/P1 performance comparison helper")
    parser.add_argument(
        "--pdf",
        type=str,
        default="",
        help="PDF path for parse benchmark. If omitted, parse benchmark is skipped.",
    )
    parser.add_argument(
        "--modes",
        type=str,
        default="legacy,nominal,fair,serious,critical",
        help="Comma separated parse benchmark modes.",
    )
    parser.add_argument("--jobs", type=int, default=2, help="Number of parse jobs per mode.")
    parser.add_argument("--parser-backend", type=str, default="", help="docling|marker|hybrid (optional)")
    parser.add_argument("--thermal", type=str, default="serious", help="Thermal level for policy comparison.")
    parser.add_argument("--low-power", action="store_true", help="Enable low-power mode in policy comparison.")
    parser.add_argument(
        "--duration-seconds",
        type=int,
        default=600,
        help="Task duration to estimate polling request counts.",
    )
    parser.add_argument(
        "--stagnant-seconds",
        type=int,
        default=420,
        help="Estimated seconds where task progress stays unchanged (used for P1 polling backoff simulation).",
    )
    parser.add_argument(
        "--idle-seconds",
        type=int,
        default=0,
        help="Estimated idle seconds after processing where runtime monitor stays enabled.",
    )
    parser.add_argument("--json-out", type=str, default="", help="Write full report to JSON path.")
    parser.add_argument("--keep-outputs", action="store_true", help="Keep parse outputs for inspection.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    parse_report = None
    pdf_path_raw = str(args.pdf or "").strip()
    if pdf_path_raw:
        pdf_path = Path(pdf_path_raw).expanduser().resolve()
        if not pdf_path.exists():
            print(f"ERROR: PDF not found: {pdf_path}")
            return 2
        modes = [m.strip().lower() for m in str(args.modes).split(",") if m.strip()]
        parse_report = asyncio.run(
            run_parse_benchmark(
                pdf_path=pdf_path,
                modes=modes,
                jobs=max(1, int(args.jobs)),
                parser_backend=(args.parser_backend.strip() or None),
                low_power_mode=bool(args.low_power),
                keep_outputs=bool(args.keep_outputs),
            )
        )

    report = build_report(
        thermal_level=args.thermal,
        low_power_mode=bool(args.low_power),
        duration_seconds=max(60, int(args.duration_seconds)),
        idle_seconds=max(0, int(args.idle_seconds)),
        stagnant_seconds=max(0, int(args.stagnant_seconds)),
        parse_report=parse_report,
    )
    print_summary(report)

    if args.json_out:
        out_path = Path(args.json_out).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nreport saved: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
