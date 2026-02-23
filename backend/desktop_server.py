from __future__ import annotations

import os
import stat

# 开启 macOS M 系列芯片的 GPU 加速兼容回退机制
# 允许不支持的 PyTorch 算子回退到 CPU，其余使用 MPS，避免全盘崩溃
os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"

import uvicorn


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
        if value <= 0:
            return default
        return value
    except ValueError:
        return default


def _prepare_uds_path(path: str) -> str:
    uds_path = os.path.abspath(path)
    if os.path.exists(uds_path):
        mode = os.stat(uds_path).st_mode
        if stat.S_ISSOCK(mode):
            os.remove(uds_path)
        else:
            raise RuntimeError(f"UDS path exists and is not a socket: {uds_path}")
    parent = os.path.dirname(uds_path) or "/tmp"
    os.makedirs(parent, exist_ok=True)
    return uds_path


def main() -> None:
    transport = os.getenv("FILESMIND_BACKEND_TRANSPORT", "tcp").strip().lower() or "tcp"
    host = os.getenv("FILESMIND_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = _env_int("FILESMIND_PORT", 8000)
    log_level = os.getenv("FILESMIND_LOG_LEVEL", "info").strip() or "info"
    if transport == "uds" and os.name != "nt":
        uds_path = _prepare_uds_path(os.getenv("FILESMIND_UDS_PATH", "/tmp/filesmind.sock"))
        uvicorn.run("app:app", uds=uds_path, log_level=log_level)
        return
    uvicorn.run("app:app", host=host, port=port, log_level=log_level)


if __name__ == "__main__":
    main()
