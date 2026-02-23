from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from refine_policy import should_refine_content
from structure_utils import assign_stable_node_ids, build_hierarchy_tree


@dataclass(slots=True)
class BuildSkeletonInput:
    doc_id: str
    markdown: str


@dataclass(slots=True)
class BuildSkeletonOutput:
    root_node: Any
    expected_nodes: List[Dict[str, Any]]


class BuildSkeletonActivity:
    async def run(self, payload: BuildSkeletonInput) -> BuildSkeletonOutput:
        root_node = await asyncio.to_thread(build_hierarchy_tree, payload.markdown)
        await asyncio.to_thread(assign_stable_node_ids, root_node, payload.doc_id)

        expected_rows: List[Dict[str, Any]] = []

        def walk(node: Any):
            content = str(getattr(node, "full_content", "") or "")
            if should_refine_content(content) and getattr(node, "level", 0) > 0:
                parent = getattr(node, "parent", None)
                expected_rows.append(
                    {
                        "node_id": str(getattr(node, "id", "")),
                        "parent_node_id": str(getattr(parent, "id", "")) if parent else None,
                        "level": int(getattr(node, "level", 0)),
                        "topic": str(getattr(node, "topic", "")),
                        "content_text": content,
                        "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                        "content_length": len(content),
                        "breadcrumbs": str(node.get_breadcrumbs()),
                    }
                )
            for child in getattr(node, "children", []):
                walk(child)

        walk(root_node)
        return BuildSkeletonOutput(root_node=root_node, expected_nodes=expected_rows)
