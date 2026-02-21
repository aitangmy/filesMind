from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from repo.nodes_repo import NodesRepo
from structure_utils import tree_to_markdown


@dataclass(slots=True)
class AssembleMarkdownInput:
    doc_id: str
    root_node: Any
    title: str


@dataclass(slots=True)
class AssembleMarkdownOutput:
    markdown: str


class AssembleMarkdownActivity:
    def __init__(self, nodes_repo: NodesRepo | None = None):
        self.nodes_repo = nodes_repo or NodesRepo()

    async def run(self, payload: AssembleMarkdownInput) -> AssembleMarkdownOutput:
        payloads = self.nodes_repo.get_success_payloads(payload.doc_id)

        def walk(node: Any):
            node_payload = payloads.get(str(getattr(node, "id", "")))
            details = (node_payload or {}).get("details")
            if isinstance(details, list):
                node.ai_details = details
            for child in getattr(node, "children", []):
                walk(child)

        walk(payload.root_node)

        final_md = tree_to_markdown(payload.root_node)
        if not final_md.startswith("# "):
            final_md = f"# {payload.title}\n\n{final_md}"
        return AssembleMarkdownOutput(markdown=final_md)
