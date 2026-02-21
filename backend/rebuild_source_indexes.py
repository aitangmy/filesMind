#!/usr/bin/env python3
"""
批量重建历史 source index。

默认策略：
- 仅处理 history 中 status=completed 的文件
- 仅重建“缺失索引”或“结构过浅（<=2 节点）”的索引
- 默认跳过 has_precise_anchor=true 的索引（避免覆盖精确锚点）
"""

from __future__ import annotations

import argparse
import json

import app as app_module


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="批量重建 FilesMind 的 source indexes")
    parser.add_argument("--file-id", action="append", default=[], help="仅处理指定 file_id，可重复传入")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不写入")
    parser.add_argument("--force", action="store_true", help="强制重建，忽略 shallow 检查")
    parser.add_argument(
        "--all",
        dest="only_shallow",
        action="store_false",
        help="重建所有可处理文件（默认只重建缺失/过浅索引）",
    )
    parser.add_argument(
        "--include-precise-anchor",
        action="store_true",
        help="包含 has_precise_anchor=true 的索引（默认跳过）",
    )
    parser.add_argument("--max-files", type=int, default=None, help="最多处理文件数量")
    parser.add_argument("--verbose", action="store_true", help="输出每条处理详情")
    parser.set_defaults(only_shallow=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    result = app_module.rebuild_source_indexes_batch(
        file_ids=args.file_id,
        dry_run=args.dry_run,
        force=args.force,
        only_shallow=args.only_shallow,
        include_precise_anchor=args.include_precise_anchor,
        max_files=args.max_files,
        verbose=args.verbose,
    )

    print(
        json.dumps(
            {
                "mode": "dry-run" if args.dry_run else "write",
                "options": result.get("options", {}),
                "summary": result.get("summary", {}),
                "message": result.get("message", ""),
            },
            ensure_ascii=False,
        )
    )

    if args.verbose:
        for item in result.get("items", []):
            file_id = item.get("file_id", "")
            filename = item.get("filename", "")
            action = item.get("action", "unknown")
            reason = item.get("reason", "")
            old_nodes = item.get("old_nodes")
            new_nodes = item.get("new_nodes")
            mode = item.get("index_mode")
            extra = []
            if old_nodes is not None:
                extra.append(f"old_nodes={old_nodes}")
            if new_nodes is not None:
                extra.append(f"new_nodes={new_nodes}")
            if mode:
                extra.append(f"mode={mode}")
            suffix = f", {'; '.join(extra)}" if extra else ""
            print(f"[{file_id}] {filename} -> {action}: {reason}{suffix}")

    summary = result.get("summary", {})
    failed = int(summary.get("failed", 0) or 0)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
