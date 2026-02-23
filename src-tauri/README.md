# FilesMind Desktop (Tauri)

## Sidecar contract

The desktop shell starts backend sidecar with environment variables:

- `FILESMIND_HOST=127.0.0.1`
- `FILESMIND_PORT=<dynamic_port>`
- `FILESMIND_AUTH_TOKEN=<random_token>`
- `FILESMIND_DATA_DIR=<app_data_dir>/data`
- `FILESMIND_LOG_DIR=<app_data_dir>/logs`
- `FILESMIND_APP_VERSION=<tauri_pkg_version>`

## Binary placement

For release packaging, place backend executable under:

- `src-tauri/binaries/filesmind-backend` (macOS/Linux)
- `src-tauri/binaries/filesmind-backend.exe` (Windows)

`tauri.conf.json` uses `externalBin` with base name `binaries/filesmind-backend`.

## Dev mode

`src-tauri/src/main.rs` defaults to running `python backend/desktop_server.py` in debug mode.
You can override with:

- `FILESMIND_SIDECAR_PATH=/absolute/path/to/backend-exe`
