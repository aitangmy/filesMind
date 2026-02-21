from __future__ import annotations

from dataclasses import dataclass

from repo.nodes_repo import NodesRepo
from workflow_contracts.errors import ErrorCode
from workflow_contracts.models import CompletenessSnapshot


@dataclass(slots=True)
class CompletenessGateInput:
    doc_id: str


class CompletenessGateActivity:
    def __init__(self, nodes_repo: NodesRepo | None = None):
        self.nodes_repo = nodes_repo or NodesRepo()

    async def run(self, payload: CompletenessGateInput) -> CompletenessSnapshot:
        raw = self.nodes_repo.get_completeness_snapshot(payload.doc_id)
        snapshot = CompletenessSnapshot(
            expected_count=int(raw.get("expected_count", 0)),
            terminal_count=int(raw.get("terminal_count", 0)),
            success_count=int(raw.get("success_count", 0)),
            failed_count=int(raw.get("failed_count", 0)),
        )
        if not snapshot.is_terminal_complete:
            raise RuntimeError(ErrorCode.INTEGRITY_INCOMPLETE.value)
        return snapshot
