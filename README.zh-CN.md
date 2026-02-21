# FilesMind - AI 驱动的深度知识导图构建工具

> [English](README.md) | [简体中文](README.zh-CN.md)

将长篇 PDF 转换为结构化思维导图，支持来源追溯、可编辑流程与可配置的大模型处理参数。

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Backend](https://img.shields.io/badge/Backend-FastAPI-009688.svg)
![Frontend](https://img.shields.io/badge/Frontend-Vue3-4FC08D.svg)

---

## 🌟 项目能力

FilesMind 是面向深度文档阅读的全栈应用：

1. 使用 `docling` / `marker` / `hybrid` 解析 PDF。
2. 通过大模型逐层细化，生成层级知识树。
3. 持久化任务结果与历史记录。
4. 支持节点回溯到源 Markdown 行号区间。
5. 导出 Markdown / XMind / PNG。

---

## 🧱 前端架构

当前前端采用“按功能域加载”的高鲁棒方案：

1. **异步能力加载**
- `MindMap` 与 `VirtualPdfViewer` 通过可恢复异步组件加载。
- 异步组件具备 `loading`、`error`、自动重试机制。

2. **按功能域拆包**
- `pdfjs`：`pdfjs-dist`
- `pdf-viewer`：`vue-pdf-embed`
- `mindmap-vendor`：`simple-mind-map` 核心
- `export-xmind`：仅 XMind 导出插件
- `vendor`：其他通用依赖

3. **意图驱动预取**
- 鼠标悬停/聚焦导出按钮时预取 XMind 导出依赖。
- 进入/悬停 PDF 详情区域时预取 PDF 相关依赖。

4. **动态 Chunk 失败自恢复**
- 监听 `vite:preloadError`，发布后出现旧 Chunk 引用时自动刷新恢复。

---

## 📦 体积预算门禁

预算校验脚本：`frontend/scripts/check-bundle-size.mjs`

当前 gzip 阈值：

- `app-shell`（`index-*.js`）: `<= 120 KB`
- `pdfjs`（`pdfjs-*.js`）: `<= 180 KB`
- `pdf-viewer`（`pdf-viewer-*.js`）: `<= 850 KB`
- `single-chunk`（其余 JS Chunk）: `<= 500 KB`

命令：

```bash
cd frontend
npm run analyze      # 构建并输出预算报告（不阻断）
npm run check:bundle # 严格预算校验（超限即失败）
```

---

## ✨ 核心特性

- 解析后端可切换（`docling`、`marker`、`hybrid`）且支持运行时配置。
- 配置中心包含模型档案、解析参数与高级引擎参数。
- 高级参数支持防抖自动保存。
- 任务超时支持运行时调整（`60` 到 `7200` 秒）。
- 支持 source index 树与节点源码摘录接口。
- 支持配置导入/导出，后端配置加密存储。
- 前端提供工作区与设置页路由（`/workspace`、`/settings`）。

---

## 🧰 环境要求

- Python `3.12.x`（`pyproject.toml` 固定 `==3.12.*`）
- Node.js `>= 18`
- Git

---

## 🚀 快速开始

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

## ⚙️ 首次使用必做配置

上传 PDF 前，请先进入 **Settings** 完成：

1. `API Base URL`
2. `Model`
3. `API Key`（Ollama 可为空）
4. 点击 **测试连接**
5. 点击 **保存全部配置**

跳过该步骤会导致任务处理失败。

---

## 🧪 解析与高级参数

### 解析参数

- `parser_backend`: `docling` / `marker` / `hybrid`
- `task_timeout_seconds`: `60 ~ 7200`
- `hybrid_noise_threshold`: `0 ~ 1`
- `hybrid_docling_skip_score`: `0 ~ 100`
- `hybrid_switch_min_delta`: `0 ~ 50`
- `hybrid_marker_min_length`: `0 ~ 1000000`
- `marker_prefer_api`: `true/false`

### 高级引擎参数

- `engine_concurrency`: `1 ~ 10`
- `engine_temperature`: `0 ~ 1`
- `engine_max_tokens`: `1000 ~ 16000`

---

## 🌍 可选环境变量

- `PARSER_BACKEND`（默认 `docling`）
- `HYBRID_NOISE_THRESHOLD`（默认 `0.20`）
- `HYBRID_DOCLING_SKIP_SCORE`（默认 `70.0`）
- `HYBRID_SWITCH_MIN_DELTA`（默认 `2.0`）
- `HYBRID_MARKER_MIN_LENGTH`（默认 `200`）
- `MARKER_PREFER_API`（默认 `false`）
- `FILESMIND_PARSE_WORKERS`（解析进程池 worker 数）

---

## 🔌 后端 API 概览

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

## 💾 数据与持久化目录

运行数据保存在 `backend/data/`：

- `pdfs/`
- `mds/`
- `images/`
- `source_mds/`
- `source_indexes/`
- `history.json`
- `config.json` + `config.key`

---

## 🗂️ 项目结构

```text
filesMind/
  backend/
    app.py
    parser_service.py
    cognitive_engine.py
    structure_utils.py
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

## ✅ 开发检查

前端检查：

```bash
cd frontend
npm run build
npm run test:unit
npm run test:e2e
npm run check:bundle
```

完整本地检查：

```bash
./scripts/test_all.sh
```

如需跳过 e2e：

```bash
SKIP_E2E=1 ./scripts/test_all.sh
```

---

## 🚢 生产部署（最小方案）

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

## ❓ Q&A

1. **为什么 `pdf-viewer` 预算是 `850 KB`？**  
`vue-pdf-embed` 当前运行时代码体积较大。我们先设定硬上限，防止继续膨胀，同时不影响 PDF 功能可用性。

2. **预算可以马上降到更低吗？**  
可以，但通常会立即触发失败。建议先跑 `npm run analyze`，定位增量来源后分阶段下调阈值。

3. **CI 是否必须启用 `check:bundle`？**  
建议必须启用。把它作为合并门禁，避免性能回退在主分支累积。

4. **为什么异步组件要自动重试？**  
可显著降低网络抖动、缓存窗口期导致的偶发加载失败，提升可用性。

---

## 🛠️ 常见问题

1. 前端启动失败：
- 确认 Node `>= 18`。
- 重新安装 `frontend` 依赖。

2. Windows 下 e2e 输出目录权限报错：
- 确认 Playwright 输出目录使用项目内路径。
- 确认当前 shell 对测试输出目录有写权限。

3. 构建提示大包：
- 先执行 `npm run analyze`。
- 检查 `manualChunks` 与动态导入点。
- 合并前保证 `npm run check:bundle` 通过。

4. 模型连接测试失败：
- 检查 Base URL、模型名、API Key。
- 检查网络可达性与服务商限流。

---

## 🤝 贡献

欢迎提交 Issue 和 PR。

仓库协作规范见 `CONTRIBUTING.md`。

---

## 📄 许可证

MIT License，详见 [LICENSE](LICENSE)。
