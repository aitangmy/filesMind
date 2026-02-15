# FilesMind: 智能文档解析与思维导图生成器

**基于 Docling (IBM) + DeepSeek/MiniMax + Markmap (Vue3) 的下一代文档智能解决方案。**

## 项目简介

FilesMind 是一个专门为深度学习和技术文档阅读设计的辅助工具。它不仅仅是一个 PDF 阅读器，更是一个**智能认知助手**。

通过结合 **IBM Docling** 的多模态布局分析能力和 **DeepSeek/MiniMax** 的长上下文推理能力，FilesMind 能够将数百页的复杂技术文档（如论文、手册、合同）自动转化为结构清晰、逻辑严密的**思维导图**。

## 核心特性

- **多模态精准解析**：利用 IBM Docling 技术，精确还原 PDF 中的表格、公式、阅读顺序，彻底告别乱码。
- **递归式深度推理**：采用 Map-Reduce 架构，利用 DeepSeek-V3/R1 或 MiniMax 2.5 处理局部细节，生成有深度的知识结构。
- **硬件加速优化**：后端针对 Apple Silicon (M1/M2/M3/M4) 进行了 MPS 加速优化，同时支持 NVIDIA GPU。
- **交互式可视化**：前端基于 Vue 3 + Markmap，支持节点折叠、缩放、漫游，提供流畅的知识探索体验。
- **多模型支持**：支持 DeepSeek、MiniMax、OpenAI、Anthropic、Moonshot、阿里云等多种 LLM 服务商。

## 技术栈

- **Backend**: Python 3.13, FastAPI, IBM Docling, OpenAI SDK
- **Frontend**: Vue 3, Vite, Markmap, TailwindCSS
- **Infrastructure**: uv (Package Manager)

## 快速开始

### 1. 环境准备

确保你已安装以下工具：
- **Python 3.10+** (推荐使用 `uv` 管理)
- **Node.js 18+**

### 2. 后端部署

```bash
# 进入后端目录
cd backend

# 安装依赖 (推荐使用 uv，速度更快)
uv sync

# 启动服务
uv run fastapi dev app.py --port 8000
```

### 3. 前端部署

```bash
# 进入前端目录
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

前端默认运行在 `http://localhost:5173`，会反向代理到后端 `/api` 路径。

## 配置说明

### LLM 模型配置

在设置页面中，你可以配置以下选项：

| 参数 | 说明 |
|------|------|
| 服务商 | 支持 MiniMax、DeepSeek、OpenAI、Anthropic、Moonshot、阿里云 |
| API Base URL | 服务商的 API 端点地址 |
| 模型 | 选择具体使用的 LLM 模型 |
| API Key | 你的 API 密钥 |

### MiniMax 2.5 速率限制

当使用 **MiniMax 2.5** 模型时，系统会根据账户类型自动调整 API 调用限制：

| 账户类型 | RPM (每分钟请求数) | 并发限制 | 请求间隔 |
|----------|-------------------|---------|---------|
| 免费用户 | 20 | 2 | 0.5秒 |
| 充值用户 | 500 | 10 | 0.3秒 |

在设置页面选择 MiniMax 2.5 模型后，会自动显示"账户类型"选项，请根据您的账户类型选择对应选项以获得最佳性能。

### 硬件加速配置

在 `backend/parser_service.py` 中，默认配置适配 **Apple Silicon (MPS)**：

```python
accel_options = AcceleratorOptions(
    num_threads=8, 
    device=AcceleratorDevice.MPS  # 修改为 CUDA 以支持 NVIDIA 显卡
)
```

### 内存优化

对于小于 16GB 内存的设备，建议在 `parser_service.py` 中保持以下配置关闭：

```python
pipeline_opts.do_picture_classification = False
pipeline_opts.do_code_enrichment = False
```

## 功能验证

确保后端已启动，运行以下命令验证核心逻辑：

```bash
# 在项目根目录下
python backend/test_pipeline.py
```

## 许可证

本软件遵循 MIT 许可证。详见 LICENSE 文件。
