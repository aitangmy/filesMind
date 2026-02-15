# FilesMind: 智能文档解析与思维导图生成器

**基于 Docling (IBM) + DeepSeek (V3/R1) + Markmap (Vue3) 的下一代文档智能解决方案。**

## 📖 项目简介

FilesMind 是一个专门为深度学习和技术文档阅读设计的辅助工具。它不仅仅是一个 PDF 阅读器，更是一个**智能认知助手**。

通过结合 **IBM Docling** 的多模态布局分析能力和 **DeepSeek** 的长上下文推理能力，FilesMind 能够将数百页的复杂技术文档（如论文、手册、合同）自动转化为结构清晰、逻辑严密的**思维导图**。

## ✨ 核心特性

- **🚀 多模态精准解析**：利用 IBM Docling 技术，精确还原 PDF 中的表格、公式、阅读顺序，彻底告别乱码。
- **🧠 递归式深度推理**：采用 Map-Reduce 架构，利用 DeepSeek-V3 处理局部细节，DeepSeek-R1 进行全局逻辑统筹，生成有深度的知识结构。
- **⚡️ 硬件加速优化**：后端针对 Apple Silicon (M1/M2/M3/M4) 进行了 MPS 加速优化，同时支持 NVIDIA GPU。
- **📊 交互式可视化**：前端基于 Vue 3 + Markmap，支持节点折叠、缩放、漫游，提供流畅的知识探索体验。

## 🛠️ 技术栈

- **Backend**: Python 3.13, FastAPI, IBM Docling, DeepSeek SDK/OpenAI SDK
- **Frontend**: Vue 3, Vite, Markmap, TailwindCSS (Utility classes)
- **Infrastructure**: uv (Package Manager)

## 📦 快速开始

### 1. 环境准备

确保你已安装以下工具：
- **Python 3.10+** (推荐使用 `uv` 管理)
- **Node.js 18+**

### 2. 后端部署

```bash
# 进入后端目录
cd backend

# 安装依赖 (推荐使用 uv，速度更快)
# 如果没有 uv，可以使用 pip install -r requirements.txt (需自行导出)
uv sync

# 配置环境变量
# 将 .env.example 复制为 .env 并填入你的 DeepSeek API Key
cp .env .env  # 如果没有 .env.example，直接创建 .env
# 编辑 .env 文件:
# DEEPSEEK_API_KEY=sk-your-api-key-here

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

前端默认运行在 `http://localhost:5173`。

## 🧪 功能验证

确保后端已启动，运行以下命令验证核心逻辑：

```bash
# 在项目根目录下
python backend/test_pipeline.py
```

## 📝 配置说明

### 硬件加速配置

在 `backend/parser_service.py` 中，默认配置适配 **Apple Silicon (MPS)**：

```python
accel_options = AcceleratorOptions(
    num_threads=8, 
    device=AcceleratorDevice.MPS # 修改为 CUDA 以支持 NVIDIA 显卡
)
```

### 内存优化

对于小于 16GB 内存的设备，建议在 `parser_service.py` 中保持以下配置关闭：

```python
pipeline_opts.do_picture_classification = False 
pipeline_opts.do_code_enrichment = False
```

## 📄 许可证

本软件遵循 MIT 许可证。详见 LICENSE 文件。
