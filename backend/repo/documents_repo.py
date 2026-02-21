from __future__ import annotations

from typing import Any, Dict, Optional

from .db import execute, fetch_one


class DocumentsRepo:
    def create_document(self, payload: Dict[str, Any]) -> None:
        execute(
            """
            insert into documents (
              doc_id, filename, file_hash, status, progress, message,
              workflow_id, run_id, source_pdf_path, output_md_path, parser_backend
            ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (doc_id) do update set
              filename = excluded.filename,
              file_hash = excluded.file_hash,
              status = excluded.status,
              progress = excluded.progress,
              message = excluded.message,
              workflow_id = excluded.workflow_id,
              run_id = excluded.run_id,
              source_pdf_path = excluded.source_pdf_path,
              output_md_path = excluded.output_md_path,
              parser_backend = excluded.parser_backend
            """,
            (
                payload["doc_id"],
                payload["filename"],
                payload["file_hash"],
                payload.get("status", "pending"),
                int(payload.get("progress", 0)),
                payload.get("message", ""),
                payload.get("workflow_id", payload["doc_id"]),
                payload.get("run_id"),
                payload.get("source_pdf_path"),
                payload.get("output_md_path"),
                payload.get("parser_backend"),
            ),
        )

    def update_document_status(self, doc_id: str, status: str, progress: int, message: str) -> None:
        execute(
            """
            update documents
            set status = %s, progress = %s, message = %s
            where doc_id = %s
            """,
            (status, int(progress), message, doc_id),
        )

    def set_output(self, doc_id: str, md_path: str) -> None:
        execute(
            """
            update documents
            set output_md_path = %s
            where doc_id = %s
            """,
            (md_path, doc_id),
        )

    def get_document(self, doc_id: str) -> Optional[Dict[str, Any]]:
        return fetch_one("select * from documents where doc_id = %s", (doc_id,))

    def get_document_by_workflow(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        return fetch_one("select * from documents where workflow_id = %s", (workflow_id,))
