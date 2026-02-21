# FilesMind - AI 驱动的深度知识导图构建工具

> [English](README.md) | [简体中文](README.zh-CN.md)

将长篇 PDF 转换为结构化导图，支持源码追溯、可编辑流程和可配置的大模型处理参数。

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Backend](https://img.shields.io/badge/Backend-FastAPI-009688.svg)
![Frontend](https://img.shields.io/badge/Frontend-Vue3-4FC08D.svg)

---

## 项目能力

FilesMind 是一个面向深度文档阅读的全栈应用：

1. 使用 `docling` / `marker` / `hybrid` 解析 PDF。
2. 通过大模型精炼生成层级化知识结构。
3. 持久化任务结果和历史记录。
4. 支持节点回溯到源 Markdown 的行号片段。
5. 导出 Markdown / XMind / PNG。

---

## 核心特性

- 解析后端可切换（`docling`、`marker`、`hybrid`），支持运行时配置。
- 配置中心包含模型档案、解析参数与高级引擎参数。
- 高级参数支持防抖自动保存。
- 任务超时可运行时调整（`60` 到 `7200` 秒）。
- 支持 source index 树与节点源码摘录接口。
- 支持配置导入/导出，后端持久化配置加密存储。
- 前端支持工作区和设置页路由（`/workspace`、`/settings`）。

---

## 环境要求

- Python `3.12.x`（`pyproject.toml` 固定 `==3.12.*`）
- Node.js `>= 18`
- Git

---

## 快速开始

### 1. 克隆项目

```bash
git clone https://github.com/aitangmy/filesMind.git
cd filesMind
```

### 2. 安装 Python 依赖（uv）

```bash
python -m pip install -U uv
uv sync
```

### 3. 启动后端

```bash
cd backend
uv run uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

后端地址：`http://localhost:8000`

### 4. 启动前端

另开一个终端：

```bash
cd frontend
npm install
npm run dev
```

前端地址：`http://localhost:5173`

---

## 首次使用必做配置

上传 PDF 前，请先进入 **Settings** 完成：

1. `API Base URL`
2. `Model`
3. `API Key`（Ollama 可为空）
4. 点击 **测试连接**
5. 点击 **保存全部配置**

若跳过该步骤，任务处理会失败。

---

## 解析与高级参数

### 解析参数

- `parser_backend`：`docling` / `marker` / `hybrid`
- `task_timeout_seconds`：`60 ~ 7200`
- `hybrid_noise_threshold`：`0 ~ 1`
- `hybrid_docling_skip_score`：`0 ~ 100`
- `hybrid_switch_min_delta`：`0 ~ 50`
- `hybrid_marker_min_length`：`0 ~ 1000000`
- `marker_prefer_api`：`true/false`

### 高级引擎参数

- `engine_concurrency`：`1 ~ 10`
- `engine_temperature`：`0 ~ 1`
- `engine_max_tokens`：`1000 ~ 16000`

说明：

- 高级面板参数会触发防抖自动保存。
- 任务超时由后端任务执行器在运行时生效。

---

## 可选环境变量

- `PARSER_BACKEND`（默认 `docling`）
- `HYBRID_NOISE_THRESHOLD`（默认 `0.20`）
- `HYBRID_DOCLING_SKIP_SCORE`（默认 `70.0`）
- `HYBRID_SWITCH_MIN_DELTA`（默认 `2.0`）
- `HYBRID_MARKER_MIN_LENGTH`（默认 `200`）
- `MARKER_PREFER_API`（默认 `false`）
- `FILESMIND_PARSE_WORKERS`（解析进程池 worker 数）

---

## 后端 API 概览

主要接口（前端通过 `/api/*` 代理访问）：

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

## 数据与持久化目录

运行数据保存在 `backend/data/`：

- `pdfs/`
- `mds/`
- `images/`
- `source_mds/`
- `source_indexes/`
- `history.json`
- `config.json` + `config.key`

---

## 项目结构

```text
filesMind/
  backend/
    app.py                # FastAPI API 与任务编排
    parser_service.py     # PDF 解析与解析后端路由
    cognitive_engine.py   # 大模型接入与高级引擎运行时限制
    structure_utils.py    # 层级重建辅助
    data/                 # 运行期持久化数据
    tests/                # 后端测试
  frontend/
    src/WorkspaceShell.vue
    src/components/MindMap.vue
    src/router/index.js
    package.json
  scripts/test_all.sh     # 本地一键检查脚本
  pyproject.toml
  uv.lock
```

---

## 开发自检

执行完整本地检查：

```bash
./scripts/test_all.sh
```

如需跳过 e2e：

```bash
SKIP_E2E=1 ./scripts/test_all.sh
```

---

## 生产部署（最小方案）

1. 构建前端：

```bash
cd frontend
npm run build
```

2. 后端无热重载启动：

```bash
cd backend
uv run uvicorn app:app --host 0.0.0.0 --port 8000 --workers 4
```

3. 使用 Nginx（或同类网关）统一处理：

- 前端静态资源
- `/api/*` 反向代理到后端
- `/images/*` 反向代理到后端

---

## 常见问题

1. 依赖安装失败：
- 确认 Python 为 `3.12.x`。
- 在仓库根目录重新执行 `uv sync`。

2. 前端启动失败：
- 确认 Node `>= 18`。
- 重新安装 `frontend` 依赖。

3. 任务执行时间过长：
- 查看后端日志。
- 在 Settings 中提高 `task_timeout_seconds`。
- 按需调整解析后端与 worker 数。

4. 模型连接测试失败：
- 检查地址、模型名、密钥。
- 检查网络可达性与服务商限流。

---

## 贡献

欢迎提交 Issue 和 PR。

仓库协作规范见 `CONTRIBUTING.md`。

---

## 许可证

MIT License，详见 [LICENSE](LICENSE)。
