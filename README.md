# FilesMind - AI-Powered Deep Knowledge Map Builder

> [English](README.md) | [简体中文](README.zh-CN.md)

Convert long PDFs into structured mind maps with source traceability, editable workflow, and configurable LLM processing.

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Backend](https://img.shields.io/badge/Backend-FastAPI-009688.svg)
![Frontend](https://img.shields.io/badge/Frontend-Vue3-4FC08D.svg)

---

## What FilesMind Does

FilesMind is a full-stack app for deep document reading:

1. Parse PDF content with `docling` / `marker` / `hybrid` backend strategies.
2. Build hierarchical knowledge trees with LLM refinement.
3. Persist processing results and file history.
4. Trace generated nodes back to source Markdown line ranges.
5. Export final maps as Markdown / XMind / PNG.

---

## Key Features

- Parser backend switching (`docling`, `marker`, `hybrid`) with runtime config.
- Settings center with model profiles, parser controls, and advanced engine controls.
- Debounced auto-save for advanced settings.
- Runtime task timeout control (`60` to `7200` seconds).
- Source index tree + per-node source excerpt API.
- Config import/export and encrypted config persistence on backend.
- Frontend workspace + settings route (`/workspace`, `/settings`).

---

## Requirements

- Python `3.12.x` (`==3.12.*` in `pyproject.toml`)
- Node.js `>= 18`
- Git

---

## Quick Start

### 1. Clone

```bash
git clone https://github.com/aitangmy/filesMind.git
cd filesMind
```

### 2. Install Python deps (uv)

```bash
python -m pip install -U uv
uv sync
```

### 3. Start backend

```bash
cd backend
uv run uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

Backend URL: `http://localhost:8000`

### 4. Start frontend

Open another terminal:

```bash
cd frontend
npm install
npm run dev
```

Frontend URL: `http://localhost:5173`

---

## First-Time Setup (Required)

Before uploading PDFs, open **Settings** and configure:

1. `API Base URL`
2. `Model`
3. `API Key` (not required for Ollama)
4. Click **Test Connection**
5. Click **Save All Config**

If this step is skipped, task processing will fail.

---

## Parser and Advanced Settings

### Parser controls

- `parser_backend`: `docling` / `marker` / `hybrid`
- `task_timeout_seconds`: `60 ~ 7200`
- `hybrid_noise_threshold`: `0 ~ 1`
- `hybrid_docling_skip_score`: `0 ~ 100`
- `hybrid_switch_min_delta`: `0 ~ 50`
- `hybrid_marker_min_length`: `0 ~ 1000000`
- `marker_prefer_api`: `true/false`

### Advanced engine controls

- `engine_concurrency`: `1 ~ 10`
- `engine_temperature`: `0 ~ 1`
- `engine_max_tokens`: `1000 ~ 16000`

Notes:

- Advanced panel changes trigger debounced auto-save.
- Task timeout is applied at runtime by backend task runner.

---

## Optional Environment Variables

- `PARSER_BACKEND` (default `docling`)
- `HYBRID_NOISE_THRESHOLD` (default `0.20`)
- `HYBRID_DOCLING_SKIP_SCORE` (default `70.0`)
- `HYBRID_SWITCH_MIN_DELTA` (default `2.0`)
- `HYBRID_MARKER_MIN_LENGTH` (default `200`)
- `MARKER_PREFER_API` (default `false`)
- `FILESMIND_PARSE_WORKERS` (process-pool worker count)

---

## API Surface (Backend)

Main endpoints (frontend accesses them via `/api/*` proxy):

- `POST /upload`
- `GET /task/{task_id}`
- `POST /task/{task_id}/cancel`
- `GET /history`
- `GET /file/{file_id}`
- `GET /file/{file_id}/tree`
- `GET /file/{file_id}/node/{node_id}/source`
- `GET /file/{file_id}/pdf`
- `DELETE /file/{file_id}`
- `GET /config` / `POST /config`
- `GET /config/export` / `POST /config/import`
- `POST /config/test` / `POST /config/models`
- `GET /health`
- `GET /system/hardware`
- `POST /admin/source-index/rebuild`

---

## Data and Persistence

Generated and runtime data are stored under `backend/data/`:

- `pdfs/`
- `mds/`
- `images/`
- `source_mds/`
- `source_indexes/`
- `history.json`
- `config.json` + `config.key`

---

## Project Structure

```text
filesMind/
  backend/
    app.py                # FastAPI API + task orchestration
    parser_service.py     # PDF parsing and parser backend routing
    cognitive_engine.py   # LLM integration and advanced engine runtime limits
    structure_utils.py    # Hierarchy reconstruction helpers
    data/                 # Persistent runtime data
    tests/                # Backend tests
  frontend/
    src/WorkspaceShell.vue
    src/components/MindMap.vue
    src/router/index.js
    package.json
  scripts/test_all.sh     # Local all-in-one checks
  pyproject.toml
  uv.lock
```

---

## Development Checks

Run full local checks:

```bash
./scripts/test_all.sh
```

Skip e2e if needed:

```bash
SKIP_E2E=1 ./scripts/test_all.sh
```

---

## Production Deployment (Minimal)

1. Build frontend:

```bash
cd frontend
npm run build
```

2. Run backend without reload:

```bash
cd backend
uv run uvicorn app:app --host 0.0.0.0 --port 8000 --workers 4
```

3. Put Nginx (or equivalent) in front of:

- static frontend assets
- `/api/*` proxy to backend
- `/images/*` proxy to backend

---

## Troubleshooting

1. Dependency install fails:
- Confirm Python `3.12.x`.
- Re-run `uv sync` from repo root.

2. Frontend startup fails:
- Confirm Node `>= 18`.
- Reinstall `frontend` dependencies.

3. Long-running tasks:
- Check backend logs.
- Increase timeout in Settings (`task_timeout_seconds`).
- Tune parser backend and worker count.

4. Model connection test fails:
- Verify endpoint/model/key.
- Check network access and provider-side limits.

---

## Contributing

Issues and pull requests are welcome.

For repository guidelines, see `CONTRIBUTING.md`.

---

## License

MIT License. See [LICENSE](LICENSE).
