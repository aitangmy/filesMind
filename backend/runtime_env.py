from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RuntimeEnv:
    base_dir: str
    data_dir: str
    log_dir: str
    sqlite_db_path: str
    app_version: str
    auth_token: str


def _default_data_dir(base_dir: str) -> str:
    return os.path.join(base_dir, "data")


def load_runtime_env(base_dir: str) -> RuntimeEnv:
    base_dir_abs = os.path.abspath(base_dir)
    data_dir = os.path.abspath(os.getenv("FILESMIND_DATA_DIR", "").strip() or _default_data_dir(base_dir_abs))
    log_dir = os.path.abspath(os.getenv("FILESMIND_LOG_DIR", "").strip() or os.path.join(data_dir, "logs"))
    sqlite_db_path = os.path.abspath(
        os.getenv("FILESMIND_SQLITE_PATH", "").strip() or os.path.join(data_dir, "filesmind.db")
    )
    app_version = os.getenv("FILESMIND_APP_VERSION", "0.1.0").strip() or "0.1.0"
    auth_token = os.getenv("FILESMIND_AUTH_TOKEN", "").strip()
    return RuntimeEnv(
        base_dir=base_dir_abs,
        data_dir=data_dir,
        log_dir=log_dir,
        sqlite_db_path=sqlite_db_path,
        app_version=app_version,
        auth_token=auth_token,
    )


def ensure_runtime_dirs(env: RuntimeEnv) -> None:
    os.makedirs(env.data_dir, exist_ok=True)
    os.makedirs(env.log_dir, exist_ok=True)
    os.makedirs(os.path.dirname(env.sqlite_db_path), exist_ok=True)
