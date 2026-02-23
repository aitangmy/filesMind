#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
import types
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Tuple

from fastapi.testclient import TestClient


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


_STUBBED_MODULES = ("parser_service", "cognitive_engine", "hardware_utils")
_ORIGINAL_MODULES = {name: sys.modules.get(name) for name in _STUBBED_MODULES}


def _install_test_stubs() -> None:
    parser_service = types.ModuleType("parser_service")
    parser_service.process_pdf_safely = lambda *args, **kwargs: ("# dummy\n", None)
    parser_service.get_parser_runtime_config = lambda: {
        "parser_backend": "docling",
        "hybrid_noise_threshold": 0.2,
        "hybrid_docling_skip_score": 70.0,
        "hybrid_switch_min_delta": 2.0,
        "hybrid_marker_min_length": 200,
        "marker_prefer_api": False,
        "task_timeout_seconds": 600,
    }
    parser_service.update_parser_runtime_config = lambda *args, **kwargs: None
    sys.modules["parser_service"] = parser_service

    cognitive_engine = types.ModuleType("cognitive_engine")
    cognitive_engine.generate_mindmap_structure = lambda *args, **kwargs: "# dummy"
    cognitive_engine.update_client_config = lambda *args, **kwargs: None
    cognitive_engine.set_model = lambda *args, **kwargs: None
    cognitive_engine.set_account_type = lambda *args, **kwargs: None

    async def _test_connection(*args, **kwargs):
        return {"success": True, "message": "ok"}

    async def _fetch_models_detailed(*args, **kwargs):
        return {"success": True, "models": ["dummy-model"], "error": ""}

    cognitive_engine.test_connection = _test_connection
    cognitive_engine.fetch_models_detailed = _fetch_models_detailed
    sys.modules["cognitive_engine"] = cognitive_engine

    hardware_utils = types.ModuleType("hardware_utils")
    hardware_utils.get_hardware_info = lambda: {"device_type": "cpu"}
    sys.modules["hardware_utils"] = hardware_utils


def _restore_original_modules() -> None:
    for name, module in _ORIGINAL_MODULES.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


_install_test_stubs()
import app as app_module  # noqa: E402

_restore_original_modules()


@dataclass
class ModeRun:
    mode: str
    status_ms: float
    status_bytes: int
    tree_ms: float
    tree_bytes: int
    file_ms: float
    file_bytes: int
    total_ms: float
    total_bytes: int


@dataclass
class ModeSummary:
    mode: str
    status_ms_avg: float
    status_bytes_avg: int
    tree_ms_avg: float
    tree_bytes_avg: int
    file_ms_avg: float
    file_bytes_avg: int
    total_ms_avg: float
    total_bytes_avg: int
    runs: int


def _rebind_storage_paths(base: Path) -> None:
    app_module.DATA_DIR = str(base / "data")
    app_module.PDF_DIR = str(base / "data" / "pdfs")
    app_module.MD_DIR = str(base / "data" / "mds")
    app_module.IMAGES_DIR = str(base / "data" / "images")
    app_module.SOURCE_MD_DIR = str(base / "data" / "source_mds")
    app_module.SOURCE_INDEX_DIR = str(base / "data" / "source_indexes")
    app_module.SOURCE_LINE_MAP_DIR = str(base / "data" / "source_line_maps")
    app_module.HISTORY_FILE = str(base / "data" / "history.json")
    app_module.CONFIG_FILE = str(base / "data" / "config.json")
    app_module.CONFIG_KEY_FILE = str(base / "data" / "config.key")

    os.makedirs(app_module.PDF_DIR, exist_ok=True)
    os.makedirs(app_module.MD_DIR, exist_ok=True)
    os.makedirs(app_module.IMAGES_DIR, exist_ok=True)
    os.makedirs(app_module.SOURCE_MD_DIR, exist_ok=True)
    os.makedirs(app_module.SOURCE_INDEX_DIR, exist_ok=True)
    os.makedirs(app_module.SOURCE_LINE_MAP_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(app_module.HISTORY_FILE), exist_ok=True)
    with open(app_module.HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump([], f)
    app_module.tasks.clear()


def _build_markdown(target_bytes: int) -> str:
    # Keep deterministic content so legacy/optimized hashes are comparable.
    header = "# Benchmark Root\n\n"
    chunk = (
        "## Section {i}\n"
        "Lorem ipsum dolor sit amet, consectetur adipiscing elit.\n"
        "Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.\n\n"
    )
    parts: List[str] = [header]
    current_size = len(header.encode("utf-8"))
    idx = 1
    while current_size < target_bytes:
        text = chunk.format(i=idx)
        parts.append(text)
        current_size += len(text.encode("utf-8"))
        idx += 1
    return "".join(parts)


def _build_source_index(file_id: str, total_lines: int, source_md_path: str, node_count: int) -> Dict[str, Any]:
    root = {
        "node_id": "root",
        "topic": "Root",
        "level": 0,
        "source_line_start": 1,
        "source_line_end": max(1, total_lines),
        "children": [],
    }
    flat_nodes: List[Dict[str, Any]] = [
        {
            "node_id": "root",
            "topic": "Root",
            "level": 0,
            "source_line_start": 1,
            "source_line_end": max(1, total_lines),
            "pdf_page_no": None,
            "pdf_y_ratio": None,
        }
    ]

    if total_lines <= 1:
        total_lines = 2
    spacing = max(1, total_lines // max(1, node_count))
    line_cursor = 2
    for i in range(1, node_count + 1):
        start = min(total_lines, line_cursor)
        end = min(total_lines, start + max(1, spacing // 2))
        node = {
            "node_id": f"n_{i}",
            "topic": f"Topic {i}",
            "level": 1,
            "source_line_start": start,
            "source_line_end": max(start, end),
            "pdf_page_no": None,
            "pdf_y_ratio": None,
            "children": [],
        }
        root["children"].append(node)
        flat_nodes.append(
            {
                "node_id": node["node_id"],
                "topic": node["topic"],
                "level": node["level"],
                "source_line_start": node["source_line_start"],
                "source_line_end": node["source_line_end"],
                "pdf_page_no": None,
                "pdf_y_ratio": None,
            }
        )
        line_cursor = min(total_lines, line_cursor + spacing)

    node_index = {item["node_id"]: item for item in flat_nodes}
    return {
        "version": 2,
        "file_id": file_id,
        "created_at": "2026-01-01T00:00:00+00:00",
        "source_md_path": source_md_path,
        "source_line_map_path": None,
        "line_system": "normalized_v1",
        "tree": root,
        "flat_nodes": flat_nodes,
        "node_index": node_index,
        "capabilities": {
            "anchor_version": "1.0",
            "has_precise_anchor": False,
            "parser_backend": "docling",
        },
    }


def _prepare_fixture(size_mb: int, nodes_per_mb: int) -> Dict[str, Any]:
    size_bytes = size_mb * 1024 * 1024
    file_id = f"bench-{size_mb}mb-{uuid.uuid4().hex[:8]}"
    task_id = f"task-{size_mb}mb-{uuid.uuid4().hex[:8]}"
    md_content = _build_markdown(size_bytes)
    md_hash = hashlib.sha256(md_content.encode("utf-8")).hexdigest()

    pdf_path = Path(app_module.PDF_DIR) / f"{file_id}.pdf"
    md_path = Path(app_module.MD_DIR) / f"{file_id}.md"
    source_md_path = Path(app_module.SOURCE_MD_DIR) / f"{file_id}.md"
    source_index_path = Path(app_module.SOURCE_INDEX_DIR) / f"{file_id}.json"

    pdf_path.write_bytes(b"%PDF-1.4\n")
    md_path.write_text(md_content, encoding="utf-8")
    source_md_path.write_text(md_content, encoding="utf-8")

    total_lines = max(1, md_content.count("\n") + 1)
    node_count = max(128, size_mb * nodes_per_mb)
    source_index = _build_source_index(file_id, total_lines=total_lines, source_md_path=str(source_md_path), node_count=node_count)
    source_index_path.write_text(json.dumps(source_index, ensure_ascii=False), encoding="utf-8")

    app_module.add_file_record(
        file_id=file_id,
        filename=f"{file_id}.pdf",
        file_hash=hashlib.md5(md_content.encode("utf-8")).hexdigest(),
        pdf_path=str(pdf_path),
        md_path=str(md_path),
        status="completed",
        task_id=task_id,
    )
    task = app_module.create_task(task_id, file_id=file_id)
    task.status = app_module.TaskStatus.COMPLETED
    task.progress = 100
    task.message = "处理完成"
    task.result = md_content
    app_module._persist_task_snapshot(task)

    return {
        "file_id": file_id,
        "task_id": task_id,
        "size_bytes": len(md_content.encode("utf-8")),
        "md_hash": md_hash,
        "node_count": node_count,
    }


def _call_json(client: TestClient, url: str) -> Tuple[Dict[str, Any], int, float]:
    start = time.perf_counter()
    resp = client.get(url)
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    if resp.status_code != 200:
        raise RuntimeError(f"GET {url} failed: {resp.status_code} {resp.text}")
    payload = resp.json()
    return payload, len(resp.content), elapsed_ms


def _call_text(client: TestClient, url: str) -> Tuple[str, int, float]:
    start = time.perf_counter()
    resp = client.get(url)
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    if resp.status_code != 200:
        raise RuntimeError(f"GET {url} failed: {resp.status_code} {resp.text}")
    return resp.text, len(resp.content), elapsed_ms


def _run_mode_once(client: TestClient, file_id: str, md_hash: str, mode: str) -> ModeRun:
    if mode == "legacy":
        status_url = f"/documents/{file_id}/status?include_result=true"
        file_url = f"/file/{file_id}"
    elif mode == "optimized":
        status_url = f"/documents/{file_id}/status"
        file_url = f"/file/{file_id}?format=raw"
    else:
        raise ValueError(f"unsupported mode: {mode}")

    status_data, status_bytes, status_ms = _call_json(client, status_url)
    if status_data.get("status") not in {"completed", "completed_with_gaps"}:
        raise RuntimeError(f"unexpected status for {mode}: {status_data.get('status')}")
    if mode == "legacy":
        result_text = str(status_data.get("result", ""))
        if hashlib.sha256(result_text.encode("utf-8")).hexdigest() != md_hash:
            raise RuntimeError("legacy status result hash mismatch")
    else:
        if "result" in status_data:
            raise RuntimeError("optimized status unexpectedly includes result")

    tree_data, tree_bytes, tree_ms = _call_json(client, f"/file/{file_id}/tree")
    if not isinstance(tree_data.get("flat_nodes"), list):
        raise RuntimeError("tree payload missing flat_nodes")

    if mode == "legacy":
        file_data, file_bytes, file_ms = _call_json(client, file_url)
        text = str(file_data.get("content", ""))
    else:
        text, file_bytes, file_ms = _call_text(client, file_url)

    if hashlib.sha256(text.encode("utf-8")).hexdigest() != md_hash:
        raise RuntimeError(f"{mode} file content hash mismatch")

    total_ms = status_ms + tree_ms + file_ms
    total_bytes = status_bytes + tree_bytes + file_bytes
    return ModeRun(
        mode=mode,
        status_ms=status_ms,
        status_bytes=status_bytes,
        tree_ms=tree_ms,
        tree_bytes=tree_bytes,
        file_ms=file_ms,
        file_bytes=file_bytes,
        total_ms=total_ms,
        total_bytes=total_bytes,
    )


def _summarize(runs: List[ModeRun], mode: str) -> ModeSummary:
    selected = [r for r in runs if r.mode == mode]
    if not selected:
        raise ValueError(f"no runs for mode={mode}")
    return ModeSummary(
        mode=mode,
        status_ms_avg=round(mean(r.status_ms for r in selected), 2),
        status_bytes_avg=int(round(mean(r.status_bytes for r in selected))),
        tree_ms_avg=round(mean(r.tree_ms for r in selected), 2),
        tree_bytes_avg=int(round(mean(r.tree_bytes for r in selected))),
        file_ms_avg=round(mean(r.file_ms for r in selected), 2),
        file_bytes_avg=int(round(mean(r.file_bytes for r in selected))),
        total_ms_avg=round(mean(r.total_ms for r in selected), 2),
        total_bytes_avg=int(round(mean(r.total_bytes for r in selected))),
        runs=len(selected),
    )


def _pct_delta(old: float, new: float) -> float:
    if old == 0:
        return 0.0
    return round(((new - old) / old) * 100.0, 2)


def _parse_sizes(raw: str) -> List[int]:
    sizes: List[int] = []
    for part in str(raw).split(","):
        text = part.strip()
        if not text:
            continue
        sizes.append(int(text))
    return sizes or [10, 30, 60]


def run_benchmark(sizes_mb: List[int], iterations: int, nodes_per_mb: int) -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="filesmind-e2e-bench-") as tmp:
        base = Path(tmp)
        _rebind_storage_paths(base)

        with TestClient(app_module.app) as client:
            for size_mb in sizes_mb:
                fixture = _prepare_fixture(size_mb=size_mb, nodes_per_mb=nodes_per_mb)
                mode_runs: List[ModeRun] = []

                # Warmup once per mode to reduce first-request skew.
                _run_mode_once(client, fixture["file_id"], fixture["md_hash"], "legacy")
                _run_mode_once(client, fixture["file_id"], fixture["md_hash"], "optimized")

                for _ in range(iterations):
                    mode_runs.append(_run_mode_once(client, fixture["file_id"], fixture["md_hash"], "legacy"))
                    mode_runs.append(_run_mode_once(client, fixture["file_id"], fixture["md_hash"], "optimized"))

                legacy = _summarize(mode_runs, "legacy")
                optimized = _summarize(mode_runs, "optimized")
                delta = {
                    "status_ms_pct": _pct_delta(legacy.status_ms_avg, optimized.status_ms_avg),
                    "status_bytes_pct": _pct_delta(float(legacy.status_bytes_avg), float(optimized.status_bytes_avg)),
                    "file_ms_pct": _pct_delta(legacy.file_ms_avg, optimized.file_ms_avg),
                    "file_bytes_pct": _pct_delta(float(legacy.file_bytes_avg), float(optimized.file_bytes_avg)),
                    "total_ms_pct": _pct_delta(legacy.total_ms_avg, optimized.total_ms_avg),
                    "total_bytes_pct": _pct_delta(float(legacy.total_bytes_avg), float(optimized.total_bytes_avg)),
                }
                results.append(
                    {
                        "size_mb": size_mb,
                        "markdown_bytes": fixture["size_bytes"],
                        "tree_nodes": fixture["node_count"],
                        "legacy": asdict(legacy),
                        "optimized": asdict(optimized),
                        "delta_pct_optimized_vs_legacy": delta,
                    }
                )

    return {
        "benchmark": "desktop_first_screen_payload_chain",
        "notes": [
            "in-process FastAPI TestClient benchmark (focus on backend serialization/payload cost)",
            "flow = documents status + file tree + file markdown",
            "legacy = include_result=true + file json",
            "optimized = default status + file raw",
        ],
        "iterations": iterations,
        "sizes_mb": sizes_mb,
        "nodes_per_mb": nodes_per_mb,
        "results": results,
    }


def _print_human(report: Dict[str, Any]) -> None:
    print("=== FilesMind Desktop First-Screen Benchmark ===")
    print(f"iterations={report['iterations']} sizes_mb={report['sizes_mb']} nodes_per_mb={report['nodes_per_mb']}")
    for item in report["results"]:
        legacy = item["legacy"]
        optimized = item["optimized"]
        delta = item["delta_pct_optimized_vs_legacy"]
        print(
            f"\n[{item['size_mb']}MB] md_bytes={item['markdown_bytes']} tree_nodes={item['tree_nodes']}\n"
            f"  status: legacy {legacy['status_ms_avg']}ms/{legacy['status_bytes_avg']}B"
            f" -> optimized {optimized['status_ms_avg']}ms/{optimized['status_bytes_avg']}B"
            f" ({delta['status_ms_pct']}%, {delta['status_bytes_pct']}%)\n"
            f"  file:   legacy {legacy['file_ms_avg']}ms/{legacy['file_bytes_avg']}B"
            f" -> optimized {optimized['file_ms_avg']}ms/{optimized['file_bytes_avg']}B"
            f" ({delta['file_ms_pct']}%, {delta['file_bytes_pct']}%)\n"
            f"  total:  legacy {legacy['total_ms_avg']}ms/{legacy['total_bytes_avg']}B"
            f" -> optimized {optimized['total_ms_avg']}ms/{optimized['total_bytes_avg']}B"
            f" ({delta['total_ms_pct']}%, {delta['total_bytes_pct']}%)"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark first-screen API chain payload/latency for legacy vs optimized desktop flow."
    )
    parser.add_argument(
        "--sizes-mb",
        default="10,30,60",
        help="Comma-separated markdown sizes in MB (default: 10,30,60)",
    )
    parser.add_argument("--iterations", type=int, default=3, help="Runs per mode per size (default: 3)")
    parser.add_argument(
        "--nodes-per-mb",
        type=int,
        default=220,
        help="Synthetic flat node count scale factor (default: 220)",
    )
    parser.add_argument("--output", default="", help="Optional path to save JSON report")
    args = parser.parse_args()

    sizes_mb = _parse_sizes(args.sizes_mb)
    iterations = max(1, int(args.iterations))
    nodes_per_mb = max(1, int(args.nodes_per_mb))

    report = run_benchmark(sizes_mb=sizes_mb, iterations=iterations, nodes_per_mb=nodes_per_mb)
    _print_human(report)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nreport saved: {output_path}")


if __name__ == "__main__":
    main()
