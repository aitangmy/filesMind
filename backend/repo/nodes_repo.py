from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, List, Optional

from .db import execute, executemany, fetch_all, fetch_one


class NodesRepo:
    def insert_expected_nodes(self, doc_id: str, rows: Iterable[Dict[str, Any]]) -> None:
        rows = list(rows)
        if not rows:
            return

        execute("delete from expected_nodes where doc_id = %s", (doc_id,))
        execute("delete from node_results where doc_id = %s", (doc_id,))

        executemany(
            """
            insert into expected_nodes (
              doc_id, node_id, parent_node_id, level, topic,
              content_text, content_hash, content_length, breadcrumbs
            ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [
                (
                    doc_id,
                    row["node_id"],
                    row.get("parent_node_id"),
                    int(row.get("level", 0)),
                    row.get("topic", ""),
                    row.get("content_text", ""),
                    row.get("content_hash", ""),
                    int(row.get("content_length", 0)),
                    row.get("breadcrumbs", ""),
                )
                for row in rows
            ],
        )

        executemany(
            """
            insert into node_results (doc_id, node_id, status, attempt)
            values (%s, %s, 'pending', 0)
            on conflict (doc_id, node_id) do update set
              status = excluded.status,
              attempt = excluded.attempt,
              error_code = null,
              error_message = null,
              payload_json = null,
              payload_hash = null,
              started_at = null,
              finished_at = null
            """,
            [(doc_id, row["node_id"]) for row in rows],
        )

    def mark_node_running(self, doc_id: str, node_id: str, attempt: int) -> None:
        execute(
            """
            update node_results
            set status = 'running', attempt = %s, error_code = null, error_message = null,
                started_at = now(), finished_at = null, updated_at = now()
            where doc_id = %s and node_id = %s
            """,
            (attempt, doc_id, node_id),
        )

    def mark_node_success(self, doc_id: str, node_id: str, attempt: int, payload: Dict[str, Any]) -> None:
        payload_json = json.dumps(payload, ensure_ascii=False)
        payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        execute(
            """
            update node_results
            set status = 'success', attempt = %s, payload_json = %s::jsonb, payload_hash = %s,
                error_code = null, error_message = null, finished_at = now(), updated_at = now()
            where doc_id = %s and node_id = %s
            """,
            (attempt, payload_json, payload_hash, doc_id, node_id),
        )

    def mark_node_retryable_failed(self, doc_id: str, node_id: str, attempt: int, error_code: str, error_message: str) -> None:
        execute(
            """
            update node_results
            set status = 'retryable_failed', attempt = %s, error_code = %s, error_message = %s,
                finished_at = now(), updated_at = now()
            where doc_id = %s and node_id = %s
            """,
            (attempt, error_code, error_message[:500], doc_id, node_id),
        )

    def mark_node_non_retryable_failed(
        self, doc_id: str, node_id: str, attempt: int, error_code: str, error_message: str
    ) -> None:
        execute(
            """
            update node_results
            set status = 'non_retryable_failed', attempt = %s, error_code = %s, error_message = %s,
                finished_at = now(), updated_at = now()
            where doc_id = %s and node_id = %s
            """,
            (attempt, error_code, error_message[:500], doc_id, node_id),
        )

    def mark_node_exhausted(self, doc_id: str, node_id: str, attempt: int, error_code: str, error_message: str) -> None:
        execute(
            """
            update node_results
            set status = 'exhausted', attempt = %s, error_code = %s, error_message = %s,
                finished_at = now(), updated_at = now()
            where doc_id = %s and node_id = %s
            """,
            (attempt, error_code, error_message[:500], doc_id, node_id),
        )

    def list_pending_nodes(self, doc_id: str) -> List[Dict[str, Any]]:
        return fetch_all(
            """
            select e.doc_id, e.node_id, e.topic, e.content_text, e.breadcrumbs, r.attempt
            from expected_nodes e
            join node_results r on r.doc_id = e.doc_id and r.node_id = e.node_id
            where e.doc_id = %s and r.status in ('pending', 'retryable_failed')
            order by e.node_id asc
            """,
            (doc_id,),
        )

    def get_completeness_snapshot(self, doc_id: str) -> Dict[str, int]:
        row = fetch_one(
            """
            select
              coalesce((select count(*) from expected_nodes where doc_id = %s), 0) as expected_count,
              coalesce((select count(*) from node_results where doc_id = %s and status in ('success', 'non_retryable_failed', 'exhausted')), 0) as terminal_count,
              coalesce((select count(*) from node_results where doc_id = %s and status = 'success'), 0) as success_count,
              coalesce((select count(*) from node_results where doc_id = %s and status in ('non_retryable_failed', 'exhausted')), 0) as failed_count
            """,
            (doc_id, doc_id, doc_id, doc_id),
        )
        return {
            "expected_count": int((row or {}).get("expected_count", 0)),
            "terminal_count": int((row or {}).get("terminal_count", 0)),
            "success_count": int((row or {}).get("success_count", 0)),
            "failed_count": int((row or {}).get("failed_count", 0)),
        }

    def get_failed_nodes(self, doc_id: str) -> List[Dict[str, Any]]:
        return fetch_all(
            """
            select e.node_id, e.topic, r.status, r.error_code, r.error_message, r.attempt
            from node_results r
            join expected_nodes e on e.doc_id = r.doc_id and e.node_id = r.node_id
            where r.doc_id = %s and r.status in ('non_retryable_failed', 'exhausted')
            order by e.node_id asc
            """,
            (doc_id,),
        )

    def get_success_payloads(self, doc_id: str) -> Dict[str, Dict[str, Any]]:
        rows = fetch_all(
            """
            select node_id, payload_json
            from node_results
            where doc_id = %s and status = 'success' and payload_json is not null
            """,
            (doc_id,),
        )
        output: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            node_id = str(row.get("node_id", ""))
            payload = row.get("payload_json")
            if node_id and isinstance(payload, dict):
                output[node_id] = payload
        return output

    def upsert_attempt_log(
        self,
        doc_id: str,
        node_id: str,
        attempt: int,
        status: str,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> None:
        execute(
            """
            insert into node_attempt_logs (
              doc_id, node_id, attempt, status, error_code, error_message,
              finished_at, provider, model, request_id
            ) values (%s, %s, %s, %s, %s, %s, now(), %s, %s, %s)
            on conflict (doc_id, node_id, attempt) do update set
              status = excluded.status,
              error_code = excluded.error_code,
              error_message = excluded.error_message,
              finished_at = now(),
              provider = excluded.provider,
              model = excluded.model,
              request_id = excluded.request_id
            """,
            (doc_id, node_id, attempt, status, error_code, (error_message or "")[:500], provider, model, request_id),
        )
