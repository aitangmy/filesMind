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



# ==================== 智能分块函数 ====================
def parse_markdown_chunks(md_content: str) -> list:
    """
    智能分块：基于大小和结构的动态分块
    目标：将文档合并为较大的语义块（约 15k 字符），减少碎片化，提升 AI 上下文理解能力。

    关键修复：
    1. 确保分块时在标题处切分，避免在段落中间切断
    2. 每个块保留完整的层级上下文（父标题）
    3. 避免碎片化导致的层级丢失
    """
    if not md_content or not md_content.strip():
        return []

    # 目标块大小（字符数）- 约 5k-8k tokens，适配长窗口模型
    TARGET_CHUNK_SIZE = 15000

    # 1. 预处理：按行分割
    lines = md_content.split('\n')

    chunks = []
    current_chunk_lines = []
    current_size = 0

    # 标题识别正则（更精确的匹配）
    header_pattern = re.compile(r'^(#{1,6})\s+(.*)')

    for line in lines:
        stripped = line.strip()
        header_match = header_pattern.match(stripped)
        is_header = header_match is not None

        line_len = len(line) + 1  # +1 for newline

        # 决定是否切分：
        # 1. 当前块已经足够大
        # 2. 并且当前行是标题（避免在段落中间切断）
        # 3. 或者当前块实在太大了（超过 2 倍目标），强制切分
        if (current_size >= TARGET_CHUNK_SIZE and is_header) or (current_size >= TARGET_CHUNK_SIZE * 2):
            if current_chunk_lines:
                chunks.append('\n'.join(current_chunk_lines))
                current_chunk_lines = []
                current_size = 0

        current_chunk_lines.append(line)
        current_size += line_len

    # 添加最后一个块
    if current_chunk_lines:
        chunks.append('\n'.join(current_chunk_lines))

    # 如果只有一个块，且看起来没有按结构分割（原文档可能缺乏清晰标题），尝试强制长度分割
    if len(chunks) == 1 and len(md_content) > TARGET_CHUNK_SIZE * 1.5:
        logger.info("文档结构不清晰，启用备用长度分块")
        return fallback_chunking(md_content, TARGET_CHUNK_SIZE)

    logger.info(f"智能分块完成，共 {len(chunks)} 个章节 (Target: {TARGET_CHUNK_SIZE} chars)")
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
CONFIG_FILE = "./data/config.json"

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

# ==================== 目录定义 ====================
# 文件存储目录
DATA_DIR = "./data"
PDF_DIR = os.path.join(DATA_DIR, "pdfs")
MD_DIR = os.path.join(DATA_DIR, "mds")
HISTORY_FILE = os.path.join(DATA_DIR, "history.json")

# 确保目录存在
os.makedirs(PDF_DIR, exist_ok=True)
os.makedirs(MD_DIR, exist_ok=True)

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

# ==================== 历史记录管理 ====================

def load_history() -> List[Dict]:
    """加载历史记录"""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return []
    return []

def save_history(history: List[Dict]):
    """保存历史记录"""
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def get_file_hash(file_path: str) -> str:
    """计算文件 MD5 Hash"""
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def check_file_exists(file_hash: str) -> Optional[Dict]:
    """检查文件是否已存在"""
    history = load_history()
    for item in history:
        if item.get('file_hash') == file_hash and item.get('status') == 'completed':
            return item
    return None

def add_file_record(file_id: str, filename: str, file_hash: str, pdf_path: str, md_path: str, status: str = "processing", task_id: str = None):
    """添加文件记录"""
    history = load_history()
    record = {
        "file_id": file_id,
        "task_id": task_id,
        "filename": filename,
        "file_hash": file_hash,
        "pdf_path": pdf_path,
        "md_path": md_path,
        "created_at": datetime.now().isoformat(),
        "status": status
    }
    history.append(record)
    save_history(history)
    return record

def update_file_status(file_id: str, status: str, md_path: str = None):
    """更新文件状态"""
    history = load_history()
    for item in history:
        if item.get('file_id') == file_id:
            item['status'] = status
            if md_path:
                item['md_path'] = md_path
            break
    save_history(history)

def delete_file_record(file_id: str) -> bool:
    """删除文件记录"""
    history = load_history()
    new_history = []
    deleted = False
    for item in history:
        if item.get('file_id') == file_id:
            # 删除文件
            if os.path.exists(item.get('pdf_path', '')):
                try:
                    os.remove(item['pdf_path'])
                except:
                    pass
            if os.path.exists(item.get('md_path', '')):
                try:
                    os.remove(item['md_path'])
                except:
                    pass
            deleted = True
        else:
            new_history.append(item)
    save_history(new_history)
    return deleted

# ==================== 任务管理 ====================

tasks: Dict[str, Task] = {}

def create_task(task_id: str) -> Task:
    """创建任务对象"""
    tasks[task_id] = Task(task_id)
    logger.info(f"任务已创建：{task_id}, 当前任务数：{len(tasks)}")
    return tasks[task_id]

def get_task(task_id: str) -> Optional[Task]:
    """
    获取任务状态
    优先从内存获取，若内存不存在则从历史记录恢复状态
    """
    # 1. 尝试从内存获取
    if task_id in tasks:
        return tasks[task_id]

    # 2. 尝试从历史记录恢复
    history = load_history()
    for item in history:
        if item.get('task_id') == task_id:
            # 重建任务对象
            restored_task = Task(task_id)
            status = item.get('status', 'failed')

            if status == 'completed':
                restored_task.status = TaskStatus.COMPLETED
                restored_task.progress = 100
                restored_task.message = "处理完成，已从历史记录恢复"
                # 尝试加载结果
                if os.path.exists(item.get('md_path', '')):
                    try:
                        with open(item['md_path'], 'r', encoding='utf-8') as f:
                            restored_task.result = f.read()
                    except:
                        pass
            elif status == 'processing':
                # 如果任务状态为 processing 但内存中没有，说明服务重启了，判断为失败
                restored_task.status = TaskStatus.FAILED
                restored_task.progress = 0
                restored_task.message = "任务中断（服务器重启）。请重新上传。"
                restored_task.error = "Server restarted"
                # 同步更新历史记录状态，避免下次轮询仍为 processing
                update_file_status(item['file_id'], 'failed')
            else:
                restored_task.status = TaskStatus.FAILED
                restored_task.message = "任务执行失败"

            return restored_task

    return None

# ==================== 后台任务 ====================

async def process_document_task(task_id: str, file_location: str, file_id: str, original_filename: str):
    """
    异步处理文档任务
    """
    logger.info(f"开始处理任务：{task_id}")
    task = get_task(task_id)

    if not task:
        logger.error(f"任务不存在：{task_id}")
        return

    try:
        # 阶段 1: PDF 解析 (0-40%)
        task.status = TaskStatus.PROCESSING
        task.progress = 5
        task.message = "正在解析 PDF 文档..."
        logger.info(f"任务 {task_id}: 开始解析 PDF")

        md_content = process_pdf_safely(file_location)

        if not md_content:
            raise Exception("PDF 解析失败")

        task.progress = 40
        task.message = "文档解析完成，正在生成思维导图..."
        logger.info(f"任务 {task_id}: PDF 解析完成")
        # 阶段 2: 文本分块 (40-50%)
        task.progress = 45
        task.message = "正在分块处理内容..."

        # 使用智能分块函数，保留章节标题
        chunks = parse_markdown_chunks(md_content)

        task.progress = 50
        task.message = f"已分块，共 {len(chunks)} 个章节"

        # 阶段 3: DeepSeek AI 处理 (50-95%)
        task.progress = 50
        task.message = "正在调用 AI 生成知识结构..."

        mindmap_md = await generate_mindmap_structure(chunks, task)

        if not mindmap_md:
            raise Exception("AI 处理失败")

        # 保存 MD 文件
        md_path = os.path.join(MD_DIR, f"{file_id}.md")
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(mindmap_md)

        # 更新文件记录状态
        update_file_status(file_id, 'completed', md_path)

        # 阶段 4: 完成
        task.status = TaskStatus.COMPLETED
        task.progress = 100
        task.message = "处理完成！"
        task.result = mindmap_md
        logger.info(f"任务 {task_id}: 处理完成")

    except Exception as e:
        logger.error(f"任务 {task_id} 处理失败：{e}")
        task.status = TaskStatus.FAILED
        task.error = str(e)
        task.message = f"处理失败：{str(e)}"
        update_file_status(file_id, 'failed')

    finally:
        # 清理临时文件
        if os.path.exists(file_location):
            try:
                os.remove(file_location)
                logger.info(f"临时文件已删除：{file_location}")
            except Exception as e:
                logger.warning(f"清理临时文件失败：{e}")

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
        # 删除临时文件
        os.remove(temp_file)

        # 获取已存在的 MD
        existing_md = ""
        if os.path.exists(existing['md_path']):
            with open(existing['md_path'], 'r', encoding='utf-8') as f:
                existing_md = f.read()

        logger.info(f"检测到重复文件：{file.filename}")
        return UploadResponse(
            task_id=task_id,
            file_id=existing['file_id'],
            status="completed",
            message="文件已存在，直接加载",
            is_duplicate=True,
            existing_md=existing_md
        )

    # 移动到正式目录
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
            xmind_data = generate_xmind_content(content, item['filename'])

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
