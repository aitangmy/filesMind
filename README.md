# FilesMind - AI-Powered Deep Knowledge Map Builder

> [English](README.md) | [简体中文](README.zh-CN.md)

Convert long PDFs into structured mind maps with source traceability, editable workflow, and configurable LLM processing.

![License](https://img.shields.io/badge/license-AGPLv3-blue.svg)
![Backend](https://img.shields.io/badge/Backend-FastAPI-009688.svg)
![Frontend](https://img.shields.io/badge/Frontend-Vue3-4FC08D.svg)

---

## 🌟 What FilesMind Does

FilesMind is a full-stack app for deep document reading:

1. Parse PDF content with `docling` / `marker` / `hybrid` backend strategies.
2. Build hierarchical knowledge trees with LLM refinement.
3. Persist processing results and file history.
4. Trace generated nodes back to source Markdown line ranges.
5. Export final maps as Markdown / XMind / PNG.

---

## 🧱 Frontend Architecture

The frontend now uses a feature-domain loading model focused on reliability and performance:

1. **Async feature loading**
- `MindMap` and `VirtualPdfViewer` are loaded via resilient async components.
- Async modules have loading state, error state, and automatic retry.

2. **Feature-based chunking**
- `pdfjs` chunk: `pdfjs-dist`
- `pdf-viewer` chunk: `vue-pdf-embed`
- `mindmap-vendor` chunk: `simple-mind-map` core
- `export-xmind` chunk: XMind export plugins only
- `vendor` chunk: remaining shared dependencies

3. **Intent-based prefetch**
- Hover/focus export button prefetches XMind exporter.
- Entering/hovering PDF detail area prefetches PDF viewer assets.

4. **Runtime chunk failure recovery**
- `vite:preloadError` listener auto-reloads the page to recover from stale chunk references after deployment.

---

## 📦 Bundle Budget Gate

Bundle budgets are enforced via `frontend/scripts/check-bundle-size.mjs`.

Current gzip thresholds:

- `app-shell` (`index-*.js`): `<= 120 KB`
- `pdfjs` (`pdfjs-*.js`): `<= 180 KB`
- `pdf-viewer` (`pdf-viewer-*.js`): `<= 850 KB`
- `single-chunk` (all other JS chunks): `<= 500 KB`

Commands:

```bash
cd frontend
npm run analyze      # build + report-only budget table
npm run check:bundle # enforce budget and fail on violation
```

---

## ✨ Key Features

- Parser backend switching (`docling`, `marker`, `hybrid`) with runtime config.
- Numbering-aware hierarchy validator (Level Stack AST mapping) for high resistance to OCR noise and structural jitter.
- Settings center with model profiles, parser controls, and advanced engine controls.
- Debounced auto-save for advanced settings.
- Source index tree + per-node source excerpt API.
- Config import/export and encrypted config persistence on backend.
- Frontend workspace + settings routes (`/workspace`, `/settings`).
- Durable workflow foundation for document processing (`activities/`, `workflows/`, `repo/`, `worker/`).

---

## 🧰 Requirements

- Python `3.12.x` (`==3.12.*` in `pyproject.toml`)
- Node.js `>= 18`
- PostgreSQL `>= 14` (required only for durable workflow persistence)
- Git

---

## 🚀 Quick Start

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

## ⚙️ First-Time Setup (Required)

Before uploading PDFs, open **Settings** and configure:

1. `API Base URL`
2. `Model`
3. `API Key` (not required for Ollama)
4. Click **Test Connection**
5. Click **Save All Config**

If this step is skipped, task processing will fail.

---

## 🧪 Parser and Advanced Settings

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

---

## 🌍 Optional Environment Variables

- `PARSER_BACKEND` (default `docling`)
- `HYBRID_NOISE_THRESHOLD` (default `0.20`)
- `HYBRID_DOCLING_SKIP_SCORE` (default `70.0`)
- `HYBRID_SWITCH_MIN_DELTA` (default `2.0`)
- `HYBRID_MARKER_MIN_LENGTH` (default `200`)
- `MARKER_PREFER_API` (default `false`)
- `FILESMIND_MAX_UPLOAD_BYTES` (default `52428800`, i.e. `50MB`)
- `FILESMIND_PARSE_WORKERS` (process-pool worker count)
- `FILESMIND_DB_DSN` (PostgreSQL DSN for durable workflow repo)
- `FILESMIND_REFINE_CONCURRENCY` (workflow refine concurrency, default `3`)
- `FILESMIND_REFINE_MAX_ATTEMPTS` (workflow refine retry cap, default `8`)

---

## 🧱 Durable Workflow (Optional)

FilesMind now includes a local durable-workflow implementation scaffolded for Temporal-style orchestration:

- Contracts: `backend/workflow_contracts/`
- Activities: `backend/activities/`
- Workflow runner: `backend/workflows/document_workflow.py`
- Worker entrypoint: `backend/worker/main.py`
- Postgres repository + migration: `backend/repo/`, `backend/migrations/0001_temporal_rebuild.sql`

Initialize schema:

```bash
psql "$FILESMIND_DB_DSN" -f backend/migrations/0001_temporal_rebuild.sql
```

Run one local workflow:

```bash
cd backend
python -m worker.main --doc-id <uuid> --filename <name.pdf> --file-path <pdf_path> --file-hash <sha256>
```

---

## 🔌 API Surface (Backend)

Main endpoints (frontend accesses via `/api/*` proxy):

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
- `GET /system/features`
- `POST /admin/source-index/rebuild`

---

## 💾 Data and Persistence

Generated and runtime data are stored under `backend/data/`:

- `pdfs/`
- `mds/`
- `images/`
- `source_mds/`
- `source_indexes/`
- `history.json`
- `config.json` + `config.key`

---

## 🗂️ Project Structure

```text
filesMind/
  backend/
    app.py
    parser_service.py
    cognitive_engine.py
    structure_utils.py
    activities/
    repo/
    workflow_contracts/
    workflows/
    worker/
    migrations/
    data/
    tests/
  frontend/
    src/WorkspaceShell.vue
    src/components/MindMap.vue
    src/components/VirtualPdfViewer.vue
    src/main.js
    vite.config.js
    scripts/check-bundle-size.mjs
    package.json
  scripts/test_all.sh
  pyproject.toml
  uv.lock
```

---

## ✅ Development Checks

Frontend checks:

```bash
cd frontend
npm run build
npm run test:unit
npm run test:e2e
npm run check:bundle
```

Full local checks:

```bash
./scripts/test_all.sh
```

Skip e2e if needed:

```bash
SKIP_E2E=1 ./scripts/test_all.sh
```

---

## 🚢 Production Deployment (Minimal)

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

## ❓ Q&A

1. **Why is `pdf-viewer` budget set to `850 KB`?**  
`vue-pdf-embed` currently bundles large rendering/runtime code. We keep a strict ceiling to prevent further regressions while preserving PDF functionality.

2. **Can I lower bundle limits immediately?**  
Yes, but expect failures until you further split or replace heavy dependencies. Start with `npm run analyze` and reduce thresholds gradually.

3. **Should CI enforce `check:bundle`?**  
Yes. Treat it as a required gate before merge to prevent silent performance regressions.

4. **Why do async modules auto-retry?**  
To reduce transient loading failures (network hiccups, stale cache windows) and improve end-user resilience.

---

## 🛠️ Troubleshooting

1. Frontend startup fails:
- Confirm Node `>= 18`.
- Reinstall frontend dependencies.

2. E2E fails with temp/output permission error on Windows:
- Ensure Playwright output uses project-local path.
- Run test command with sufficient file permissions.

3. Large bundle warning:
- Run `npm run analyze`.
- Check `manualChunks` and dynamic imports.
- Keep `npm run check:bundle` green before merge.

4. Model connection test fails:
- Verify endpoint/model/key.
- Check network access and provider-side limits.

---

## 🤝 Contributing

Issues and pull requests are welcome.

For repository guidelines, see `CONTRIBUTING.md`.

---

## 📄 License

FilesMind is dual-licensed:

1. Open-source license: GNU Affero General Public License v3.0 or later (`AGPL-3.0-or-later`), see [LICENSE](LICENSE).
2. Commercial license: available for organizations that need to distribute or operate proprietary derivatives, see [COMMERCIAL.md](COMMERCIAL.md).

Unless you have a separate written commercial agreement with the copyright holder, your use is governed by AGPL v3.0 or later.
