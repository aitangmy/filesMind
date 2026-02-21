from __future__ import annotations

import os
from dataclasses import dataclass

from repo.db import execute
from repo.documents_repo import DocumentsRepo


@dataclass(slots=True)
class PersistExportInput:
    doc_id: str
    markdown: str
    markdown_path: str
    integrity: str
    success_nodes: int
    failed_nodes: int


class PersistExportActivity:
    def __init__(self, documents_repo: DocumentsRepo | None = None):
        self.documents_repo = documents_repo or DocumentsRepo()

    async def run(self, payload: PersistExportInput) -> None:
        os.makedirs(os.path.dirname(payload.markdown_path), exist_ok=True)
        with open(payload.markdown_path, "w", encoding="utf-8") as f:
            f.write(payload.markdown)

        self.documents_repo.set_output(payload.doc_id, payload.markdown_path)
        execute(
            """
            insert into exports (doc_id, integrity, success_nodes, failed_nodes, markdown_path)
            values (%s, %s, %s, %s, %s)
            on conflict (doc_id) do update set
              integrity = excluded.integrity,
              success_nodes = excluded.success_nodes,
              failed_nodes = excluded.failed_nodes,
              markdown_path = excluded.markdown_path,
              exported_at = now()
            """,
            (
                payload.doc_id,
                payload.integrity,
                int(payload.success_nodes),
                int(payload.failed_nodes),
                payload.markdown_path,
            ),
        )
