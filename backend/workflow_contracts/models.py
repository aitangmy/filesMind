"""Workflow contract models for durable document processing."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class DocumentStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_GAPS = "completed_with_gaps"
    FAILED = "failed"
    CANCELLED = "cancelled"


class NodeStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    RETRYABLE_FAILED = "retryable_failed"
    NON_RETRYABLE_FAILED = "non_retryable_failed"
    EXHAUSTED = "exhausted"


TERMINAL_NODE_STATES = {
    NodeStatus.SUCCESS,
    NodeStatus.NON_RETRYABLE_FAILED,
    NodeStatus.EXHAUSTED,
}


@dataclass(slots=True)
class WorkflowInput:
    doc_id: str
    filename: str
    file_path: str
    file_hash: str
    parser_backend: str
    model_profile: str
    runtime_config: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExpectedNode:
    doc_id: str
    node_id: str
    topic: str
    level: int
    content: str
    content_hash: str
    breadcrumbs: str
    parent_node_id: Optional[str] = None


@dataclass(slots=True)
class RefinePayload:
    topic: str
    details: List[Dict[str, Any]]


@dataclass(slots=True)
class NodeExecutionResult:
    doc_id: str
    node_id: str
    status: NodeStatus
    attempt: int
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    payload: Optional[RefinePayload] = None


@dataclass(slots=True)
class CompletenessSnapshot:
    expected_count: int
    terminal_count: int
    success_count: int
    failed_count: int

    @property
    def is_terminal_complete(self) -> bool:
        return self.expected_count == self.terminal_count

    @property
    def is_full_success(self) -> bool:
        return self.expected_count == self.success_count


@dataclass(slots=True)
class ExportSummary:
    doc_id: str
    status: DocumentStatus
    integrity: str
    success_nodes: int
    failed_nodes: int
    markdown_path: str
