"""State transition guards for document and node execution."""

from __future__ import annotations

from typing import Dict, Set

from .models import DocumentStatus, NodeStatus


_ALLOWED_DOC_TRANSITIONS: Dict[DocumentStatus, Set[DocumentStatus]] = {
    DocumentStatus.PENDING: {DocumentStatus.RUNNING, DocumentStatus.CANCELLED, DocumentStatus.FAILED},
    DocumentStatus.RUNNING: {
        DocumentStatus.COMPLETED,
        DocumentStatus.COMPLETED_WITH_GAPS,
        DocumentStatus.CANCELLED,
        DocumentStatus.FAILED,
    },
    DocumentStatus.COMPLETED: set(),
    DocumentStatus.COMPLETED_WITH_GAPS: set(),
    DocumentStatus.CANCELLED: set(),
    DocumentStatus.FAILED: set(),
}

_ALLOWED_NODE_TRANSITIONS: Dict[NodeStatus, Set[NodeStatus]] = {
    NodeStatus.PENDING: {NodeStatus.RUNNING, NodeStatus.NON_RETRYABLE_FAILED},
    NodeStatus.RUNNING: {
        NodeStatus.SUCCESS,
        NodeStatus.RETRYABLE_FAILED,
        NodeStatus.NON_RETRYABLE_FAILED,
    },
    NodeStatus.RETRYABLE_FAILED: {NodeStatus.RUNNING, NodeStatus.EXHAUSTED},
    NodeStatus.SUCCESS: set(),
    NodeStatus.NON_RETRYABLE_FAILED: set(),
    NodeStatus.EXHAUSTED: set(),
}


def can_transition_document(old: DocumentStatus, new: DocumentStatus) -> bool:
    return new in _ALLOWED_DOC_TRANSITIONS.get(old, set())


def can_transition_node(old: NodeStatus, new: NodeStatus) -> bool:
    return new in _ALLOWED_NODE_TRANSITIONS.get(old, set())
