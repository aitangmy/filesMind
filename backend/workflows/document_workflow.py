"""Executable durable workflow runner (local implementation).

This module keeps the same contract that will later map to Temporal workflow methods.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import List

from activities.assemble_markdown_activity import AssembleMarkdownActivity, AssembleMarkdownInput
from activities.build_skeleton_activity import BuildSkeletonActivity, BuildSkeletonInput
from activities.completeness_gate_activity import CompletenessGateActivity, CompletenessGateInput
from activities.parse_pdf_activity import ParsePdfActivity, ParsePdfInput
from activities.persist_export_activity import PersistExportActivity, PersistExportInput
from activities.refine_node_activity import RefineNodeActivity, RefineNodeInput
from repo.documents_repo import DocumentsRepo
from repo.events_repo import EventsRepo
from repo.nodes_repo import NodesRepo
from workflow_contracts.models import CompletenessSnapshot, DocumentStatus, ExportSummary, WorkflowInput


@dataclass(slots=True)
class DocumentWorkflowResult:
    doc_id: str
    status: DocumentStatus
    summary: ExportSummary


class DocumentWorkflow:
    def __init__(self):
        self.documents_repo = DocumentsRepo()
        self.nodes_repo = NodesRepo()
        self.events_repo = EventsRepo()
        self.parse_activity = ParsePdfActivity()
        self.skeleton_activity = BuildSkeletonActivity()
        self.refine_activity = RefineNodeActivity(self.nodes_repo)
        self.gate_activity = CompletenessGateActivity(self.nodes_repo)
        self.assemble_activity = AssembleMarkdownActivity(self.nodes_repo)
        self.persist_activity = PersistExportActivity(self.documents_repo)

    async def run(self, wf_input: WorkflowInput) -> DocumentWorkflowResult:
        self.documents_repo.create_document(
            {
                "doc_id": wf_input.doc_id,
                "filename": wf_input.filename,
                "file_hash": wf_input.file_hash,
                "status": DocumentStatus.RUNNING.value,
                "progress": 1,
                "message": "Parsing PDF",
                "workflow_id": wf_input.doc_id,
                "source_pdf_path": wf_input.file_path,
                "parser_backend": wf_input.parser_backend,
            }
        )

        parsed = await self.parse_activity.run(
            ParsePdfInput(doc_id=wf_input.doc_id, file_path=wf_input.file_path, output_dir=_md_dir())
        )
        self.documents_repo.update_document_status(wf_input.doc_id, DocumentStatus.RUNNING.value, 15, "Building skeleton")

        skeleton = await self.skeleton_activity.run(BuildSkeletonInput(doc_id=wf_input.doc_id, markdown=parsed.markdown))
        self.nodes_repo.insert_expected_nodes(wf_input.doc_id, skeleton.expected_nodes)
        self.events_repo.append_event(
            wf_input.doc_id,
            "skeleton_built",
            {"expected_nodes": len(skeleton.expected_nodes)},
        )

        await self.refine_nodes(wf_input.doc_id, [])
        self.documents_repo.update_document_status(wf_input.doc_id, DocumentStatus.RUNNING.value, 92, "Checking completeness")

        snap = await self.completeness_gate(wf_input.doc_id)
        integrity = "full" if snap.is_full_success else "partial"

        assembled = await self.assemble_activity.run(
            AssembleMarkdownInput(
                doc_id=wf_input.doc_id,
                root_node=skeleton.root_node,
                title=os.path.splitext(wf_input.filename)[0],
            )
        )
        out_path = os.path.join(_md_dir(), f"{wf_input.doc_id}.md")
        await self.persist_activity.run(
            PersistExportInput(
                doc_id=wf_input.doc_id,
                markdown=assembled.markdown,
                markdown_path=out_path,
                integrity=integrity,
                success_nodes=snap.success_count,
                failed_nodes=snap.failed_count,
            )
        )

        final_status = DocumentStatus.COMPLETED if snap.is_full_success else DocumentStatus.COMPLETED_WITH_GAPS
        self.documents_repo.update_document_status(
            wf_input.doc_id,
            final_status.value,
            100,
            "Completed" if snap.is_full_success else "Completed with gaps",
        )

        summary = ExportSummary(
            doc_id=wf_input.doc_id,
            status=final_status,
            integrity=integrity,
            success_nodes=snap.success_count,
            failed_nodes=snap.failed_count,
            markdown_path=out_path,
        )
        return DocumentWorkflowResult(doc_id=wf_input.doc_id, status=final_status, summary=summary)

    async def completeness_gate(self, doc_id: str) -> CompletenessSnapshot:
        return await self.gate_activity.run(CompletenessGateInput(doc_id=doc_id))

    async def refine_nodes(self, doc_id: str, node_ids: List[str]) -> None:
        max_attempts = int(os.getenv("FILESMIND_REFINE_MAX_ATTEMPTS", "8"))
        concurrency = max(1, int(os.getenv("FILESMIND_REFINE_CONCURRENCY", "3")))

        while True:
            pending = self.nodes_repo.list_pending_nodes(doc_id)
            if node_ids:
                wanted = set(node_ids)
                pending = [p for p in pending if str(p.get("node_id")) in wanted]
            if not pending:
                break

            sem = asyncio.Semaphore(concurrency)

            async def _run(item: dict):
                async with sem:
                    attempt = int(item.get("attempt", 0)) + 1
                    result = await self.refine_activity.run(
                        RefineNodeInput(
                            doc_id=doc_id,
                            node_id=str(item.get("node_id", "")),
                            topic=str(item.get("topic", "")),
                            content=str(item.get("content_text", "")),
                            breadcrumbs=str(item.get("breadcrumbs", "")),
                            model_profile="default",
                            attempt=attempt,
                            max_attempts=max_attempts,
                        )
                    )
                    return result

            await asyncio.gather(*[_run(item) for item in pending])

            snap = self.nodes_repo.get_completeness_snapshot(doc_id)
            expected = max(1, int(snap.get("expected_count", 1)))
            terminal = int(snap.get("terminal_count", 0))
            progress = min(90, 20 + int((terminal / expected) * 65))
            self.documents_repo.update_document_status(doc_id, DocumentStatus.RUNNING.value, progress, "Refining nodes")


def _md_dir() -> str:
    base = os.path.dirname(os.path.dirname(__file__))
    path = os.path.join(base, "data", "mds")
    os.makedirs(path, exist_ok=True)
    return path
