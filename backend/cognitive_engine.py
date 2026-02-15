"""
认知引擎 - DeepSeek AI 处理模块
优化版：适配付费 API + 正确的 temperature + 修复信号量泄漏 + 支持动态配置
"""
import asyncio
import os
import atexit
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

# DeepSeek API 配置 - 使用全局客户端，支持动态更新
_client = None

def get_client():
    """获取或创建全局客户端"""
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        )
    return _client

def update_client_config(config: dict):
    """
    动态更新客户端配置
    """
    global _client
    base_url = config.get("base_url", "https://api.deepseek.com")
    api_key = config.get("api_key", "")
    model = config.get("model", "deepseek-chat")
    
    if not api_key:
        raise ValueError("API Key 不能为空")
    
    # 清理 base_url：去掉末尾的 /v1，避免重复
    base_url = base_url.rstrip('/')
    if base_url.endswith('/v1'):
        base_url = base_url[:-3]  # 去掉 /v1
    
    print(f"更新配置: base_url={base_url}, model={model}")
    
    # 创建新客户端
    _client = AsyncOpenAI(
        api_key=api_key,
        base_url=base_url  # AsyncOpenAI 会自动添加 /v1
    )
    # 更新模型
    set_model(model)
    print(f"Client updated: base_url={base_url}, model={model}")

async def test_connection(config: dict) -> dict:
    """
    测试配置是否可用 - 增强版
    """
    base_url = config.get("base_url", "https://api.deepseek.com")
    api_key = config.get("api_key", "")
    model = config.get("model", "deepseek-chat")
    
    if not api_key:
        return {"success": False, "message": "API Key 不能为空"}
    
    # 清理 base_url：去掉末尾的 /v1，避免重复
    base_url = base_url.rstrip('/')
    if base_url.endswith('/v1'):
        base_url = base_url[:-3]
    
    print(f"测试连接: base_url={base_url}, model={model}")
    
    # 创建临时客户端测试
    test_client = AsyncOpenAI(
        api_key=api_key,
        base_url=base_url  # AsyncOpenAI 会自动添加 /v1
    )
    
    try:
        # 发送一个简单的测试请求
        response = await test_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Reply with exactly: 'OK'"}
            ],
            max_tokens=10,
            timeout=30  # 30秒超时
        )
        
        # 验证响应有效
        if response and response.choices and len(response.choices) > 0:
            content = response.choices[0].message.content
            print(f"测试响应: {content}")
            return {
                "success": True, 
                "message": f"连接成功！模型响应: {content[:50]}...", 
                "model": model
            }
        else:
            return {"success": False, "message": "API 响应格式异常"}
            
    except Exception as e:
        error_msg = str(e)
        print(f"测试连接失败: {error_msg}")
        
        # 提供更友好的错误信息
        if "401" in error_msg or "authentication" in error_msg.lower():
            return {"success": False, "message": "API Key 无效或已过期，请检查"}
        elif "403" in error_msg:
            return {"success": False, "message": "API Key 没有权限访问该模型"}
        elif "404" in error_msg:
            return {"success": False, "message": "模型不存在，请检查模型名称"}
        elif "429" in error_msg:
            return {"success": False, "message": "请求频率超限，请稍后重试"}
        elif "timeout" in error_msg.lower():
            return {"success": False, "message": "请求超时，请检查网络"}
        else:
            return {"success": False, "message": f"连接失败: {error_msg[:100]}"}

# 保留向后兼容的 client 引用
client = property(lambda self: get_client())

# 全局模型配置
_current_model = "deepseek-chat"

def set_model(model: str):
    """设置当前模型"""
    global _current_model
    _current_model = model

def get_model() -> str:
    """获取当前模型"""
    return _current_model

# ==================== 付费版优化配置 ====================
# DeepSeek 付费版不限制并发
# 建议值：10-15（根据实际情况调整）

# 使用 asyncio 的信号量（而非 multiprocessing）
_semaphore = None
REQUEST_DELAY = 0.3

def get_semaphore():
    """获取或创建信号量（延迟初始化）"""
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(10)
    return _semaphore

# 清理函数
def cleanup():
    global _semaphore
    _semaphore = None

atexit.register(cleanup)

# 任务超时配置
TASK_TIMEOUT = 600  # 10分钟，与 DeepSeek 文档一致

SYSTEM_PROMPT = """
You are a professional Knowledge Architect. Your task is to extract a structured Mind Map from technical documentation.
Your output MUST be a valid Markdown list.

Rules:
1. Use only Markdown list syntax (- Node).
2. Hierarchy depth should be reasonable (max 4 levels).
3. Focus on "Concepts", "Relations", and "Key Data".
4. Remove conversational fillers.
5. If the chunk is empty or irrelevant, return nothing.
"""

async def summarize_chunk(text_chunk: str, chunk_id: int, task=None, process_info: dict = None):
    """
    处理单个文本块
    """
    # 提取章节标题（第一行）
    lines = text_chunk.strip().split('\n')
    title = lines[0] if lines else f"章节 {chunk_id + 1}"
    
    # 清理标题（去掉 # 符号，保留文字）
    title = title.strip().lstrip('#').strip()
    if not title:
        title = f"章节 {chunk_id + 1}"
    
    semaphore = get_semaphore()
    async with semaphore:
        try:
            # 添加延迟，避免瞬间过高并发
            await asyncio.sleep(REQUEST_DELAY)
            
            client = get_client()
            response = await client.chat.completions.create(
                model=get_model(), 
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"Analyze the following text and convert it into a Markdown Mind Map branch:\n\n{text_chunk}"}
                ],
                # 数据抽取/分析场景，使用 1.0
                temperature=1.0,
                max_tokens=2000
            )
            
            ai_content = response.choices[0].message.content
            
            # 将标题作为父节点，AI 内容作为子节点
            # 这样可以保留原始章节结构
            if ai_content and ai_content.strip():
                # 如果 AI 输出已经是列表格式，直接添加标题作为父节点
                result = f"- {title}\n  {ai_content.strip()}"
            else:
                result = f"- {title}"
            
            # 更新进度（如果有 task 对象）
            if task and process_info:
                completed = process_info['completed'] + 1
                total = process_info['total']
                process_info['completed'] = completed
                
                # 计算进度：50% -> 95%
                # progress = base (50) + (completed / total) * range (45)
                progress = 50 + int((completed / total) * 45)
                task.progress = min(95, progress)
                task.message = f"AI 正在处理章节 {completed}/{total}..."
            
            return chunk_id, result
            
        except Exception as e:
            print(f"Error processing chunk {chunk_id}: {e}")
            await asyncio.sleep(1)
            return chunk_id, None

async def generate_root_summary(full_markdown: str):
    """
    生成根节点摘要
    """
    try:
        client = get_client()
        response = await client.chat.completions.create(
            model="deepseek-reasoner",
            messages=[
                {"role": "system", "content": "You are an expert at synthesizing complex information into a single root node and main branches for a Mind Map."},
                {"role": "user", "content": f"Based on the following detailed branches, generate a Root Node and the top-level structure (Level 1 only).\n\nbranches:\n{full_markdown[:4000]}..."}
            ],
            # 数据抽取/分析场景，使用 1.0
            temperature=1.0,
            max_tokens=1000
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"Error generating root summary: {e}")
        return "# Document Analysis"

async def generate_mindmap_structure(chunks, task=None):
    """
    Map-Reduce 实现
    - MAP: 并发处理各个章节
    - REDUCE: 汇总生成最终结构
    """
    if not chunks:
        return "# Empty Document"
    
    total_chunks = len(chunks)
    
    # ==================== MAP Phase ====================
    # 共享进度信息
    process_info = {'completed': 0, 'total': total_chunks}
    
    tasks = [summarize_chunk(chunk, i, task, process_info) for i, chunk in enumerate(chunks)]
    
    # 并发执行（受 semaphore 控制）
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # 处理结果
    valid_results = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            print(f"Chunk {i} failed: {result}")
            continue
        chunk_id, content = result
        if content and content.strip():
            valid_results.append((chunk_id, content))
    
    # 排序保持顺序
    sorted_results = sorted(valid_results, key=lambda x: x[0])
    branch_contents = [r[1] for r in sorted_results]
    
    if not branch_contents:
        return "# No valid content extracted"
    
    full_branches = "\n".join(branch_contents)
    
    # ==================== REDUCE Phase ====================
    if task:
        task.message = "正在生成知识结构..."
    
    try:
        root_structure = await generate_root_summary(full_branches)
        final_output = f"{root_structure}\n\n{full_branches}"
    except Exception as e:
        print(f"Reduce phase error: {e}")
        final_output = f"# Generated Knowledge Graph\n{full_branches}"
    
    return final_output
