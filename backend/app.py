"""
FilesMind 服务协议
支持异步任务、进度追踪和文件历史记录
"""
import os
import uuid
import asyncio
import logging
import hashlib
import json
from datetime import datetime
import re

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("FilesMind")


from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel
from typing import Optional, Dict, List
import shutil

# 导入扩展模块
from parser_service import process_pdf_safely
from cognitive_engine import generate_mindmap_structure, update_client_config, test_connection, set_model, set_account_type
from xmind_exporter import generate_xmind_content



# ==================== 辅助函数 ====================
def count_headers(text: str) -> Dict[str, int]:
    """统计 Markdown 文本中各级标题数量"""
    counts = {"h1": 0, "h2": 0, "h3": 0, "h4": 0, "h5": 0, "h6": 0, "total": 0}
    for line in text.split('\n'):
        stripped = line.strip()
        if stripped.startswith('#'):
            match = re.match(r'^(#{1,6})\s', stripped)
            if match:
                level = len(match.group(1))
                counts[f"h{level}"] += 1
                counts["total"] += 1
    return counts

# ==================== 智能分块函数 ====================
def parse_markdown_chunks(md_content: str) -> List[Dict]:
    """
    智能分块：基于大小和结构的动态分块
    目标：将文档合并为较大的语义块（约 15k 字符），减少碎片化，提升 AI 上下文理解能力。
    
    关键修复：
    1. 引入标题栈 (Header Stack) 维护层级上下文
    2. 返回结构改为 List[Dict] 以携带 context
    """
    if not md_content or not md_content.strip():
        return []

    TARGET_CHUNK_SIZE = 6000
    lines = md_content.split('\n')
    
    chunks = []
    current_chunk_lines = []
    current_size = 0
    
    # 核心：维护标题栈 [{'level': 1, 'text': 'Chapter 1'}, ...]
    header_stack = [] 
    header_pattern = re.compile(r'^(#{1,6})\s+(.*)')

    for line in lines:
        stripped = line.strip()
        header_match = header_pattern.match(stripped)
        
        # --- 1. 维护上下文栈 ---
        if header_match:
            level = len(header_match.group(1))
            text = header_match.group(2).strip()
            
            # 弹出所有级别 >= 当前级别的标题（保持层级树的正确性）
            while header_stack and header_stack[-1]['level'] >= level:
                header_stack.pop()
            
            header_stack.append({'level': level, 'text': text})

        # --- 2. 决定是否切分 ---
        line_len = len(line) + 1 # +1 for newline
        
        # 触发切分的条件：
        # 1. 大小超标 
        # 2. 且当前行是标题（尽量在章节处切断）
        # 3. 或者当前块实在太大了（超过 2 倍目标），强制切分
        flag_split_at_header = (current_size >= TARGET_CHUNK_SIZE and header_match)
        flag_force_split = (current_size >= TARGET_CHUNK_SIZE * 2)

        if flag_split_at_header or flag_force_split:
            if current_chunk_lines:
                # 生成当前块的 Context String
                # 策略调整：
                # 如果是 Header 触发的切分，stack 包含了新 Header，Context 应为新 Header 的父级 (stack[:-1])
                # 如果是强制切分，stack 是当前上下文，Context 应为完整 stack (stack[:]) 以保留当前位置
                
                # 用户原始逻辑使用 stack[:-1]，我们在此微调以增强鲁棒性：
                # 但遵循用户的 Draft 代码为主，此处稍微优化 'split reason' 判断
                
                use_parent_context = True if header_match else False
                
                eff_stack = header_stack[:-1] if (use_parent_context and len(header_stack) > 1) else header_stack
                # 注意 user code: context_str = " > ".join([h['text'] for h in header_stack[:-1]]) if len(header_stack) > 1 else ""
                # if not context_str...
                
                # 采用用户提供的稳健逻辑 (Original User Code Path)
                # 使用切分时刻的 stack (包含了新头)。
                # 之前块的 Context: 理论上是新头之前的状态。
                # 但如果我们已经 update 了 stack...
                # User Code update stack BEFORE split check.
                # So header_stack includes the NEW header.
                # The Previous Chunk (which we are saving now) ENDS right before this new header.
                # So its context is indeed best described by the PARENT of the new header (if siblings).
                # Example: Old=1.1, New=1.2. Stack=[1, 1.2]. Context=[1]. Chunk 1.1 -> under 1. Correct.
                
                context_source = header_stack[:-1] if len(header_stack) > 1 else []
                context_str = " > ".join([h['text'] for h in context_source])
                
                if not context_str and header_stack:
                     # 顶层或者是只有一级
                     # 注意：如果是 [H1, H2]，source=[H1]，context="H1"
                     # 如果是 [H1]，source=[]，context="" -> Fallback to H1
                     context_str = header_stack[0]['text']

                # 计算 context 深度和建议的起始标题级别
                context_depth = len(context_source) if context_source else (1 if header_stack else 0)
                expected_start_level = min(context_depth + 2, 6)  # H1=root, context占用后续级别

                chunks.append({
                    "content": '\n'.join(current_chunk_lines),
                    "context": context_str,
                    "context_depth": context_depth,
                    "expected_start_level": expected_start_level
                })
                current_chunk_lines = []
                current_size = 0
        
        current_chunk_lines.append(line)
        current_size += line_len

    # 处理最后一个块
    if current_chunk_lines:
        context_str = " > ".join([h['text'] for h in header_stack])
        context_depth = len(header_stack)
        expected_start_level = min(context_depth + 2, 6)
        chunks.append({
            "content": '\n'.join(current_chunk_lines),
            "context": context_str,
            "context_depth": context_depth,
            "expected_start_level": expected_start_level
        })

    # 标题统计日志
    total_headers = count_headers(md_content)
    logger.info(f"智能分块完成，共 {len(chunks)} 个章节 (Target: {TARGET_CHUNK_SIZE} chars)")
    logger.info(f"原文标题统计: H1={total_headers['h1']}, H2={total_headers['h2']}, H3={total_headers['h3']}, H4={total_headers['h4']}, H5={total_headers['h5']}, H6={total_headers['h6']}, 总计={total_headers['total']}")
    for i, chunk in enumerate(chunks):
        chunk_headers = count_headers(chunk.get('content', ''))
        ctx = chunk.get('context', 'N/A')
        esl = chunk.get('expected_start_level', '?')
        if chunk_headers['total'] > 0:
            logger.info(f"Chunk {i}: {chunk_headers['total']} 个标题 (H2={chunk_headers['h2']}, H3={chunk_headers['h3']}, H4={chunk_headers['h4']}) | Context=[{ctx[:40]}] | StartLevel=H{esl}")
    return chunks


def fallback_chunking(md_content: str, chunk_size: int = 15000) -> list:
    """备用分块方案：按字符长度均分，尽量在段落处分割"""
    if len(md_content) <= chunk_size:
        return [md_content] if md_content.strip() else []

    chunks = []
    # 按双换行（段落）分割
    paragraphs = md_content.split('\n\n')
    current_chunk = ""

    for para in paragraphs:
        # 如果加上这段会超长
        if len(current_chunk) + len(para) > chunk_size:
            # 如果当前块不为空，先保存当前块
            if current_chunk.strip():
                chunks.append(current_chunk.strip())
                current_chunk = ""

            # 如果单个段落本身就超长，强制切分
            if len(para) > chunk_size:
                # 递归切分超长段落
                sub_chunks = [para[i:i+chunk_size] for i in range(0, len(para), chunk_size)]
                chunks.extend(sub_chunks)
            else:
                current_chunk = para + "\n\n"
        else:
            current_chunk += para + "\n\n"

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks


app = FastAPI()

# ==================== 启动时配置 ====================
@app.on_event("startup")
async def startup_event():
    """启动时加载配置"""
    config = load_config()
    if config.get("api_key"):
        try:
            update_client_config(config)
            # 加载账户类型
            set_account_type(config.get("account_type", "free"))
            logger.info("配置已加载并应用到运行时")
        except Exception as e:
            logger.warning(f"启动时加载配置失败：{e}")
    else:
        logger.info("未配置 API Key，请在前端设置")

# ==================== 配置管理 ====================
# 使用绝对路径，确保在任何目录启动都能找到配置
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "data", "config.json")

def load_config() -> Dict:
    """加载配置"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {
        "base_url": "https://api.minimaxi.com/v1",
        "model": "MiniMax-M2.5",
        "api_key": "",
        "account_type": "free"
    }

def save_config(config: Dict):
    """保存配置"""
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from fastapi.staticfiles import StaticFiles

# ==================== 目录定义 ====================
# 文件存储目录 - 使用绝对路径
# BASE_DIR 已在配置管理部分定义
DATA_DIR = os.path.join(BASE_DIR, "data")
PDF_DIR = os.path.join(DATA_DIR, "pdfs")
MD_DIR = os.path.join(DATA_DIR, "mds")
IMAGES_DIR = os.path.join(DATA_DIR, "images")  # 新增图片目录
HISTORY_FILE = os.path.join(DATA_DIR, "history.json")

# 确保目录存在
os.makedirs(PDF_DIR, exist_ok=True)
os.makedirs(MD_DIR, exist_ok=True)
os.makedirs(IMAGES_DIR, exist_ok=True)

# 挂载静态图片目录 (Step 2)
app.mount("/images", StaticFiles(directory=IMAGES_DIR), name="images")

# ==================== 数据模型 ====================

class TaskStatus(str):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

class Task:
    def __init__(self, task_id: str):
        self.task_id = task_id
        self.status = TaskStatus.PENDING
        self.progress = 0
        self.message = "等待处理..."
        self.result = None
        self.error = None

class FileRecord(BaseModel):
    file_id: str
    task_id: Optional[str] = None
    filename: str
    file_hash: str
    pdf_path: str
    md_path: str
    created_at: str
    status: str  # "completed", "processing", "failed"

# ... (skip history management)

# ==================== 后台任务 ====================

async def process_document_task(task_id: str, file_location: str, file_id: str, original_filename: str):
    """
    异步处理文档任务 - Skeleton-Refinement Strategy
    """
    logger.info(f"开始处理任务：{task_id}")
    task = get_task(task_id)

    if not task:
        logger.error(f"任务不存在：{task_id}")
        return

    try:
        # 阶段 1: PDF 解析 (0-10%)
        task.status = TaskStatus.PROCESSING
        task.progress = 5
        task.message = "正在解析 PDF 文档..."
        logger.info(f"任务 {task_id}: 开始解析 PDF")

        # Update: process_pdf_safely returns (md_content, images_dir)
        md_content, _ = process_pdf_safely(file_location, file_id=file_id)

        if not md_content:
            logger.error(f"PDF 解析失败: {file_location}")
            raise Exception("PDF 解析失败")

        task.progress = 10
        task.message = "文档解析完成，正在构建知识骨架..."
        logger.info(f"任务 {task_id}: PDF 解析完成")
        
        # 阶段 2: 构建骨架 (10-20%)
        from structure_utils import build_hierarchy_tree, tree_to_markdown
        
        root_node = build_hierarchy_tree(md_content)
        
        # 收集需要 Refinement 的节点
        nodes_to_refine = []
        
        def collect_nodes(node):
            # 策略：只处理有内容的叶子节点或包含大量文本的中间节点
            # 以及 Root 下的"孤儿内容"
            content_len = len(node.full_content)
            
            # Refinement 1: Empty Node Handling (Skip small container nodes)
            if content_len > 50:
                nodes_to_refine.append(node)
            
            for child in node.children:
                collect_nodes(child)
                
        collect_nodes(root_node)
        
        task.progress = 20
        task.message = f"知识骨架构建完成，共发现 {len(nodes_to_refine)} 个关键章节..."
        logger.info(f"Tree built. Nodes to refine: {len(nodes_to_refine)}")

        # 阶段 3: 并行 Refinement (20-95%)
        from cognitive_engine import refine_node_content
        
        # Refinement 2: Concurrency Control
        semaphore = asyncio.Semaphore(5)
        total_nodes = len(nodes_to_refine)
        completed_count = 0
        
        async def process_node(node):
            nonlocal completed_count
            async with semaphore:
                try:
                    # Refinement 3: Context Breadcrumbs
                    context_path = node.get_breadcrumbs()
                    
                    details = await refine_node_content(
                        node_title=node.topic,
                        content_chunk=node.full_content,
                        context_path=context_path
                    )
                    
                    if details:
                        node.ai_details = details
                    
                    # 更新进度
                    completed_count += 1
                    current_progress = 20 + int((completed_count / total_nodes) * 75)
                    task.progress = min(95, current_progress)
                    if completed_count % 5 == 0:
                        task.message = f"AI 正在深入分析章节 ({completed_count}/{total_nodes})..."
                        
                except Exception as e:
                    logger.error(f"Node processing failed: {e}")
                    
        if nodes_to_refine:
            tasks_list = [process_node(n) for n in nodes_to_refine]
            await asyncio.gather(*tasks_list)
        else:
            logger.warning("No nodes required refinement.")

        # 阶段 4: 组装与导出 (95-100%)
        task.progress = 98
        task.message = "正在组装最终图谱..."
        
        final_md = tree_to_markdown(root_node)
        
        # 添加根节点标题 (如果 Root 没有显示)
        # tree_to_markdown 默认不打印 Root，我们手动加一个 H1
        doc_title = original_filename.replace('.pdf', '')
        if not final_md.startswith('# '):
            final_md = f"# {doc_title}\n\n{final_md}"

        # 保存 MD 文件
        md_path = os.path.join(MD_DIR, f"{file_id}.md")
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(final_md)

        # 更新文件记录状态
        update_file_status(file_id, 'completed', md_path)

        task.status = TaskStatus.COMPLETED
        task.progress = 100
        task.message = "处理完成！"
        task.result = final_md
        logger.info(f"任务 {task_id}: 处理完成")

    except Exception as e:
        logger.error(f"任务 {task_id} 处理失败：{e}", exc_info=True)
        task.status = TaskStatus.FAILED
        task.error = str(e)
        task.message = f"处理失败：{str(e)}"
        update_file_status(file_id, 'failed')

# ==================== API 路由 ====================

class TaskResponse(BaseModel):
    task_id: str
    status: str
    progress: int
    message: str
    result: Optional[str] = None
    error: Optional[str] = None

class UploadResponse(BaseModel):
    task_id: str
    file_id: str
    status: str
    message: str
    is_duplicate: bool = False
    existing_md: Optional[str] = None

class HistoryItem(BaseModel):
    file_id: str
    filename: str
    file_hash: str
    md_path: str
    created_at: str
    status: str

@app.post("/upload", response_model=UploadResponse)
async def upload_document(file: UploadFile = File(...)):
    """
    上传文档，创建异步任务
    """
    # 生成唯一 ID
    file_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())

    logger.info(f"收到上传请求：{file_id}, 文件名：{file.filename}")

    # 保存文件
    temp_file = os.path.join(DATA_DIR, "temp", f"{file_id}_{file.filename}")
    os.makedirs(os.path.dirname(temp_file), exist_ok=True)

    try:
        with open(temp_file, "wb+") as buffer:
            shutil.copyfileobj(file.file, buffer)
        logger.info(f"文件已保存：{temp_file}")
    except Exception as e:
        logger.error(f"文件保存失败：{e}")
        raise HTTPException(status_code=500, detail=f"文件保存失败：{str(e)}")

    # 计算文件 Hash
    file_hash = get_file_hash(temp_file)
    logger.info(f"文件 Hash: {file_hash}")

    # 检查是否重复
    existing = check_file_exists(file_hash)
    if existing:
        existing_status = existing.get('status')

        if existing_status == 'completed':
            # 情况 1: 已完成，直接复用 MD 结果
            # 删除临时文件
            os.remove(temp_file)

            # 获取已存在的 MD
            existing_md = ""
            if os.path.exists(existing['md_path']):
                with open(existing['md_path'], 'r', encoding='utf-8') as f:
                    existing_md = f.read()

            logger.info(f"检测到重复文件（已完成）：{file.filename}")
            return UploadResponse(
                task_id=task_id,
                file_id=existing['file_id'],
                status="completed",
                message="文件已存在，直接加载",
                is_duplicate=True,
                existing_md=existing_md
            )

        elif existing_status == 'failed':
            # 情况 2: 之前处理失败，复用 PDF 文件，重新创建任务
            old_file_id = existing['file_id']
            pdf_path = existing.get('pdf_path')

            if not pdf_path or not os.path.exists(pdf_path):
                # PDF 文件不存在，删除临时文件并当作新文件处理
                logger.warning(f"失败任务的 PDF 文件不存在：{pdf_path}")
                # 继续执行后续逻辑，当作新文件处理
            else:
                # 复用现有 PDF 文件，删除临时文件
                os.remove(temp_file)

                # 更新原记录状态为 processing
                md_path = os.path.join(MD_DIR, f"{old_file_id}.md")
                add_file_record(old_file_id, existing['filename'], file_hash, pdf_path, md_path, "processing", task_id=task_id)

                # 创建新任务，使用原有 PDF 路径
                task = create_task(task_id)
                asyncio.create_task(process_document_task(task_id, pdf_path, old_file_id, existing['filename']))

                logger.info(f"检测到失败任务，重新处理：{file.filename}, file_id={old_file_id}")
                return UploadResponse(
                    task_id=task_id,
                    file_id=old_file_id,
                    status="processing",
                    message="检测到之前处理失败，正在重新处理..."
                )

    # 新文件：移动到正式目录
    pdf_path = os.path.join(PDF_DIR, f"{file_id}_{file.filename}")
    shutil.move(temp_file, pdf_path)

    # 创建文件记录
    md_path = os.path.join(MD_DIR, f"{file_id}.md")
    add_file_record(file_id, file.filename, file_hash, pdf_path, md_path, "processing", task_id=task_id)

    # 创建任务
    task = create_task(task_id)

    # 启动后台任务
    asyncio.create_task(process_document_task(task_id, pdf_path, file_id, file.filename))
    logger.info(f"后台任务已创建：{task_id}")

    return UploadResponse(
        task_id=task_id,
        file_id=file_id,
        status="processing",
        message="任务已创建，正在处理..."
    )

@app.get("/task/{task_id}", response_model=TaskResponse)
async def get_task_status(task_id: str):
    """
    获取任务状态，支持重启后查询
    """
    task = get_task(task_id)

    if not task:
        logger.warning(f"任务不存在：{task_id}")
        raise HTTPException(status_code=404, detail="任务不存在")

    return TaskResponse(
        task_id=task.task_id,
        status=task.status,
        progress=task.progress,
        message=task.message,
        result=task.result,
        error=task.error
    )

@app.get("/history", response_model=List[HistoryItem])
async def get_history():
    """
    获取文件历史列表
    """
    history = load_history()
    # 只需要关键字段
    return [
        HistoryItem(
            file_id=item['file_id'],
            filename=item['filename'],
            file_hash=item['file_hash'],
            md_path=item['md_path'],
            created_at=item['created_at'],
            status=item['status']
        )
        for item in history
    ]

@app.get("/file/{file_id}")
async def get_file_content(file_id: str):
    """
    获取文件的 MD 内容
    """
    history = load_history()
    for item in history:
        if item['file_id'] == file_id:
            if item['status'] != 'completed':
                raise HTTPException(status_code=400, detail="文件尚未处理完成")

            if not os.path.exists(item['md_path']):
                raise HTTPException(status_code=404, detail="文件内容不存在")

            with open(item['md_path'], 'r', encoding='utf-8') as f:
                content = f.read()

            return {"content": content, "filename": item['filename']}

    raise HTTPException(status_code=404, detail="文件记录不存在")

@app.delete("/file/{file_id}")
async def delete_file(file_id: str):
    """
    删除文件记录
    """
    if delete_file_record(file_id):
        return {"message": "文件已删除"}
    raise HTTPException(status_code=404, detail="文件不存在")

@app.get("/export/xmind/{file_id}")
async def export_xmind(file_id: str):
    """
    导出 XMind 格式
    """
    from fastapi.responses import Response

    history = load_history()
    for item in history:
        if item['file_id'] == file_id:
            if item['status'] != 'completed':
                raise HTTPException(status_code=400, detail="文件尚未处理完成")

            if not os.path.exists(item['md_path']):
                raise HTTPException(status_code=404, detail="文件内容不存在")

            with open(item['md_path'], 'r', encoding='utf-8') as f:
                content = f.read()

            # 生成 XMind
            # step 4: 传入图片目录
            images_dir = os.path.join(IMAGES_DIR, file_id)
            xmind_data = generate_xmind_content(content, item['filename'], images_dir=images_dir)

            filename = item['filename'].replace('.pdf', '') + '.xmind'

            return Response(
                content=xmind_data,
                media_type="application/octet-stream",
                headers={"Content-Disposition": f"attachment; filename={filename}"}
            )

    raise HTTPException(status_code=404, detail="文件记录不存在")

@app.post("/export/xmind")
async def export_xmind_from_content(request: Request):
    """
    直接从 Markdown 数据导出 XMind
    """
    request_data = await request.json()
    content = request_data.get('content', '')
    filename = request_data.get('filename', 'mindmap')

    if not content:
        raise HTTPException(status_code=400, detail="内容不能为空")

    xmind_data = generate_xmind_content(content, filename)

    return Response(
        content=xmind_data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename={filename}.xmind"}
    )

@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "tasks_count": len(tasks)}

# ==================== 配置 API ====================
@app.get("/config")
async def get_config():
    """获取当前配置"""
    config = load_config()
    # 隐藏部分 api_key
    config["api_key"] = "***" if config.get("api_key") else ""
    return config

@app.post("/config")
async def set_config(config: Dict):
    """设置配置"""
    # 如果 API Key 是保留符号，使用原有 Key
    if config.get("api_key") == "***":
        existing_config = load_config()
        config["api_key"] = existing_config.get("api_key", "")

    # 确保 account_type 存在
    if "account_type" not in config:
        existing_config = load_config()
        config["account_type"] = existing_config.get("account_type", "free")

    save_config(config)
    # 更新运行时配置
    update_client_config(config)
    set_model(config.get("model", "deepseek-chat"))
    # 设置账户类型
    set_account_type(config.get("account_type", "free"))
    return {"message": "配置已保存"}

@app.post("/config/test")
async def test_config(request: Request):
    """测试配置"""
    try:
        request_data = await request.json()

        # 如果 API Key 是保留符号，使用原有 Key 进行测试
        if request_data.get("api_key") == "***":
            existing_config = load_config()
            # 只有当原有配置有 Key 时才替换
            if existing_config.get("api_key"):
                request_data["api_key"] = existing_config.get("api_key")

        result = await test_connection(request_data)
        return result
    except Exception as e:
        logger.error(f"测试配置失败：{e}")
        return {"success": False, "message": f"内部错误：{str(e)}"}
