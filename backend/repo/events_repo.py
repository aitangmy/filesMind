from __future__ import annotations

import json
from typing import Any, Dict

from .db import execute


class EventsRepo:
    def append_event(self, doc_id: str, event_type: str, payload: Dict[str, Any], level: str = "info") -> None:
        execute(
            """
            insert into processing_events (doc_id, event_type, event_level, payload_json)
            values (%s, %s, %s, %s::jsonb)
            """,
            (doc_id, event_type, level, json.dumps(payload, ensure_ascii=False)),
        )
