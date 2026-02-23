from __future__ import annotations

import os
import sqlite3
from typing import Any, Dict, List, Tuple


MIGRATIONS: List[Tuple[str, str]] = [
    (
        "0001_core",
        """
        create table if not exists schema_migrations (
          id text primary key,
          applied_at text not null default (datetime('now'))
        );

        create table if not exists app_config (
          key text primary key,
          value text not null,
          updated_at text not null default (datetime('now'))
        );

        create table if not exists documents (
          file_id text primary key,
          task_id text,
          filename text not null,
          file_hash text not null,
          pdf_path text not null,
          md_path text not null,
          status text not null,
          created_at text not null,
          updated_at text not null default (datetime('now'))
        );

        create index if not exists idx_documents_status on documents(status);
        create index if not exists idx_documents_hash on documents(file_hash);

        create table if not exists tasks (
          task_id text primary key,
          file_id text,
          status text not null,
          progress integer not null default 0,
          message text not null default '',
          error text,
          result_md text,
          failure_details_json text,
          cancel_requested integer not null default 0,
          cancel_reason text,
          timeout_seconds integer not null default 0,
          started_at text,
          updated_at text not null default (datetime('now'))
        );

        create index if not exists idx_tasks_file on tasks(file_id);
        create index if not exists idx_tasks_status on tasks(status);

        create table if not exists profiles (
          id text primary key,
          name text not null,
          provider text not null,
          base_url text not null,
          model text not null,
          api_key_cipher text not null default '',
          account_type text not null default 'free',
          manual_models_json text not null default '[]',
          updated_at text not null default (datetime('now'))
        );

        create table if not exists events (
          id integer primary key autoincrement,
          category text not null,
          event text not null,
          payload_json text not null default '{}',
          created_at text not null default (datetime('now'))
        );

        create index if not exists idx_events_category_created on events(category, created_at);
        """,
    ),
    (
        "0002_learning",
        """
        create table if not exists question_bank (
          id text primary key,
          file_id text not null,
          node_id text not null,
          q_type text not null,
          stem text not null,
          options_json text not null default '[]',
          answer_json text not null default '{}',
          explanation text not null default '',
          source_refs_json text not null default '[]',
          difficulty real not null default 0.5,
          status text not null default 'active',
          prompt_version text not null default 'v1',
          created_at text not null default (datetime('now')),
          updated_at text not null default (datetime('now'))
        );

        create index if not exists idx_question_bank_node on question_bank(file_id, node_id);

        create table if not exists quiz_attempts (
          id text primary key,
          question_id text not null,
          file_id text not null,
          node_id text not null,
          user_answer_json text not null,
          is_correct integer not null,
          latency_ms integer not null default 0,
          confidence real,
          error_tags_json text not null default '[]',
          created_at text not null default (datetime('now'))
        );

        create index if not exists idx_quiz_attempts_node_created on quiz_attempts(file_id, node_id, created_at);

        create table if not exists wrong_book (
          id text primary key,
          attempt_id text not null,
          file_id text not null,
          node_id text not null,
          reason text not null default '',
          status text not null default 'open',
          next_review_at text,
          created_at text not null default (datetime('now'))
        );

        create index if not exists idx_wrong_book_node_status on wrong_book(file_id, node_id, status);

        create table if not exists node_mastery (
          file_id text not null,
          node_id text not null,
          mastery_score real not null default 50,
          weakness_index real not null default 50,
          wrong_streak integer not null default 0,
          last_reviewed_at text,
          updated_at text not null default (datetime('now')),
          primary key (file_id, node_id)
        );

        create table if not exists study_sessions (
          id text primary key,
          file_id text not null,
          started_at text not null,
          ended_at text,
          duration_sec integer not null default 0,
          summary_json text not null default '{}'
        );
        """,
    ),
]


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma journal_mode=WAL;")
    conn.execute("pragma synchronous=NORMAL;")
    conn.execute("pragma foreign_keys=ON;")
    conn.execute("pragma busy_timeout=5000;")
    return conn


def init_sqlite(db_path: str) -> Dict[str, Any]:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    applied: List[str] = []
    with _connect(db_path) as conn:
        conn.execute(
            """
            create table if not exists schema_migrations (
              id text primary key,
              applied_at text not null default (datetime('now'))
            )
            """
        )
        existing = {str(row["id"]) for row in conn.execute("select id from schema_migrations")}

        for migration_id, sql in MIGRATIONS:
            if migration_id in existing:
                continue
            conn.executescript(sql)
            conn.execute("insert into schema_migrations (id) values (?)", (migration_id,))
            applied.append(migration_id)

        schema_version = conn.execute(
            "select count(*) as cnt from schema_migrations"
        ).fetchone()["cnt"]
        conn.commit()

    return {
        "db_path": db_path,
        "schema_version": int(schema_version),
        "applied_migrations": applied,
    }


def sqlite_health(db_path: str) -> Dict[str, Any]:
    try:
        with _connect(db_path) as conn:
            row = conn.execute("select count(*) as cnt from schema_migrations").fetchone()
            conn.execute("select 1").fetchone()
            return {
                "ok": True,
                "schema_version": int((row or {"cnt": 0})["cnt"]),
                "db_path": db_path,
            }
    except Exception as exc:
        return {"ok": False, "schema_version": 0, "db_path": db_path, "error": str(exc)}
