"""Node refinement activity implementation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from cognitive_engine import refine_node_content
from refine_policy import should_fail_on_empty_refine_result
from repo.nodes_repo import NodesRepo
from workflow_contracts.errors import ErrorCode, NON_RETRYABLE_CODES, RETRYABLE_CODES
from workflow_contracts.models import NodeExecutionResult, NodeStatus, RefinePayload


@dataclass(slots=True)
class RefineNodeInput:
    doc_id: str
    node_id: str
    topic: str
    content: str
    breadcrumbs: str
    model_profile: str
    attempt: int
    max_attempts: int = 8


class RefineNodeActivity:
    """Durable node refinement activity.

    Idempotent row key is (doc_id, node_id) and each attempt is logged.
    """

    def __init__(self, nodes_repo: NodesRepo | None = None):
        self.nodes_repo = nodes_repo or NodesRepo()

    async def run(self, payload: RefineNodeInput) -> NodeExecutionResult:
        self.nodes_repo.mark_node_running(payload.doc_id, payload.node_id, payload.attempt)
        try:
            details = await refine_node_content(
                node_title=payload.topic,
                content_chunk=payload.content,
                context_path=payload.breadcrumbs,
            )
            if not details and should_fail_on_empty_refine_result(payload.content):
                raise RuntimeError(ErrorCode.REFINE_EMPTY_RESULT.value)

            data = {
                "topic": payload.topic,
                "details": details or [],
            }
            self.nodes_repo.mark_node_success(payload.doc_id, payload.node_id, payload.attempt, data)
            self.nodes_repo.upsert_attempt_log(
                payload.doc_id,
                payload.node_id,
                payload.attempt,
                "success",
                provider="openai-compatible",
                model=payload.model_profile,
            )
            return NodeExecutionResult(
                doc_id=payload.doc_id,
                node_id=payload.node_id,
                status=NodeStatus.SUCCESS,
                attempt=payload.attempt,
                payload=RefinePayload(topic=payload.topic, details=details or []),
            )
        except Exception as exc:
            code = map_provider_exception(exc)
            message = to_error_message(code, str(exc))

            if code in NON_RETRYABLE_CODES:
                self.nodes_repo.mark_node_non_retryable_failed(
                    payload.doc_id, payload.node_id, payload.attempt, code.value, message
                )
                final_status = NodeStatus.NON_RETRYABLE_FAILED
            elif payload.attempt >= payload.max_attempts:
                self.nodes_repo.mark_node_exhausted(payload.doc_id, payload.node_id, payload.attempt, code.value, message)
                final_status = NodeStatus.EXHAUSTED
            else:
                self.nodes_repo.mark_node_retryable_failed(
                    payload.doc_id, payload.node_id, payload.attempt, code.value, message
                )
                final_status = NodeStatus.RETRYABLE_FAILED

            self.nodes_repo.upsert_attempt_log(
                payload.doc_id,
                payload.node_id,
                payload.attempt,
                final_status.value,
                error_code=code.value,
                error_message=message,
                provider="openai-compatible",
                model=payload.model_profile,
            )
            return NodeExecutionResult(
                doc_id=payload.doc_id,
                node_id=payload.node_id,
                status=final_status,
                attempt=payload.attempt,
                error_code=code.value,
                error_message=message,
            )


def map_provider_exception(exc: Exception) -> ErrorCode:
    """Map provider/network exceptions to standard error codes."""
    message = str(exc).lower()
    if ErrorCode.REFINE_EMPTY_RESULT.value.lower() in message:
        return ErrorCode.REFINE_EMPTY_RESULT
    if "429" in message or "rate limit" in message:
        return ErrorCode.PROVIDER_RATE_LIMIT
    if "timeout" in message:
        return ErrorCode.PROVIDER_TIMEOUT
    if "connection" in message or "network" in message or "reset" in message:
        return ErrorCode.PROVIDER_NETWORK_ERROR
    if "json" in message or "schema" in message or "invalid" in message:
        return ErrorCode.PROVIDER_RESPONSE_INVALID
    return ErrorCode.INTERNAL_ERROR


def is_retryable(code: ErrorCode) -> bool:
    return code in RETRYABLE_CODES


def to_error_message(code: ErrorCode, raw: Optional[str]) -> str:
    base = raw or code.value
    return base[:500]
