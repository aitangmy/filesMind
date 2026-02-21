"""PostgreSQL database adapter for durable orchestration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Iterable, Optional

try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:  # pragma: no cover - optional runtime dependency
    psycopg = None
    dict_row = None


@dataclass(slots=True)
class DatabaseConfig:
    dsn: str


def get_db_config() -> DatabaseConfig:
    dsn = os.getenv("FILESMIND_DB_DSN", "").strip()
    if not dsn:
        raise RuntimeError("FILESMIND_DB_DSN is required")
    return DatabaseConfig(dsn=dsn)


def _connect():
    if psycopg is None:
        raise RuntimeError("psycopg is not installed; install psycopg[binary] to enable Postgres repo")
    cfg = get_db_config()
    return psycopg.connect(cfg.dsn, row_factory=dict_row)


def fetch_one(sql: str, params: Optional[Iterable[Any]] = None) -> Optional[dict]:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            row = cur.fetchone()
            conn.commit()
            return dict(row) if row else None


def fetch_all(sql: str, params: Optional[Iterable[Any]] = None) -> list[dict]:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            rows = cur.fetchall() or []
            conn.commit()
            return [dict(r) for r in rows]


def execute(sql: str, params: Optional[Iterable[Any]] = None) -> None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
        conn.commit()


def executemany(sql: str, params_seq: Iterable[Iterable[Any]]) -> None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.executemany(sql, params_seq)
        conn.commit()
