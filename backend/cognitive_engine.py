"""
认知引擎 - DeepSeek AI 处理模块
优化版：适配付费 API + 正确的 temperature + 修复信号量泄漏 + 支持动态配置
"""
import asyncio
import os
import re
import atexit
from openai import AsyncOpenAI

# DeepSeek API 配置 - 使用全局客户端，支持动态更新
_client = None

def get_client():
    """获取或创建全局客户端"""
    global _client
    if _client is None:
        # 默认使用空配置，等待 update_client_config 注入
        _client = AsyncOpenAI(
            api_key="",
            base_url="https://api.deepseek.com"
        )
    return _client

def update_client_config(config: dict):
    """
    动态更新客户端配置
    """
    global _client
    base_url = config.get("base_url", "https://api.minimaxi.com/v1")
    api_key = config.get("api_key", "")
    model = config.get("model", "MiniMax-M2.5")
    
    if not api_key:
        raise ValueError("API Key 不能为空")
    
    # 移除错误的 base_url 清理逻辑，保持用户输入的原始 URL
    base_url = base_url.rstrip('/')
    
    print(f"更新配置: base_url={base_url}, model={model}")
    
    # 创建新客户端
    _client = AsyncOpenAI(
        api_key=api_key,
        base_url=base_url
    )
    # 更新模型
    set_model(model)
    print(f"Client updated: base_url={base_url}, model={model}")

async def test_connection(config: dict) -> dict:
    """
    测试配置是否可用 - 增强版
    """
    base_url = config.get("base_url", "https://api.minimaxi.com/v1")
    api_key = config.get("api_key", "")
    model = config.get("model", "MiniMax-M2.5")
    
    if not api_key:
        return {"success": False, "message": "API Key 不能为空"}
    
    # 移除错误的 base_url 清理逻辑
    base_url = base_url.rstrip('/')
    
    print(f"测试连接: base_url={base_url}, model={model}")
    
    # 创建临时客户端测试
    test_client = AsyncOpenAI(
        api_key=api_key,
        base_url=base_url
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
    global _current_model, _semaphore
    _current_model = model
    
    # 当模型切换时，重置信号量以应用新的限制配置
    _semaphore = None
    get_semaphore()  # 重新初始化信号量

def get_model() -> str:
    """获取当前模型"""
    return _current_model

# ==================== MiniMax 2.5 速率限制配置 ====================
# MiniMax 2.5 文本模型速率限制 (RPM: 每分钟请求数)
# 免费用户: 20 RPM
# 充值用户: 500 RPM
MINIMAX_2_5_RATE_LIMITS = {
    "free": {"rpm": 20, "tpm": 1000000},
    "paid": {"rpm": 500, "tpm": 20000000}
}

# MiniMax 2.5 模型标识（支持多种命名）
MINIMAX_2_5_MODELS = [
    "MiniMax-M2.5",
    "MiniMax-M2.5-highspeed",
    "abab6.5s-chat",
    "abab6.5g-chat"
]

def is_minimax_2_5_model(model: str) -> bool:
    """检查是否为 MiniMax 2.5 系列模型"""
    if not model:
        return False
    model_lower = model.lower()
    # 检查是否匹配已知模型名称
    return any(m.lower() in model_lower or model_lower in m.lower() for m in MINIMAX_2_5_MODELS)


# 账户类型配置（默认免费用户）
_current_account_type = "free"

def set_account_type(account_type: str):
    """设置账户类型（free/paid）"""
    global _current_account_type
    if account_type in ["free", "paid"]:
        _current_account_type = account_type
        # 重置信号量以应用新配置
        global _semaphore
        _semaphore = None
        get_semaphore()

def get_account_type() -> str:
    """获取当前账户类型"""
    return _current_account_type


# ==================== 付费版优化配置 ====================
# DeepSeek 付费版不限制并发
# 建议值：10-15（根据实际情况调整）

# 使用 asyncio 的信号量（而非 multiprocessing）
_semaphore = None
REQUEST_DELAY = 0.3

def get_semaphore():
    """获取或创建信号量（延迟初始化），根据模型类型动态调整"""
    global _semaphore
    if _semaphore is None:
        current_model = get_model()
        
        # MiniMax 2.5 模型：限制并发以符合速率限制
        if is_minimax_2_5_model(current_model):
            # 根据 MiniMax 2.5 速率限制和账户类型设置
            account_type = get_account_type()
            rate_limit = MINIMAX_2_5_RATE_LIMITS.get(account_type, MINIMAX_2_5_RATE_LIMITS["free"])
            rpm = rate_limit["rpm"]
            
            # 并发设置：免费用户 2（留有余量），付费用户 10
            # 确保并发 * 延迟时间 <= 60秒 / RPM
            if account_type == "free":
                concurrency = 2  # 20 RPM，设置为 2
                global REQUEST_DELAY
                REQUEST_DELAY = 0.5  # 增加请求间隔
            else:
                concurrency = 10  # 500 RPM，可设置较高并发
                REQUEST_DELAY = 0.3
            
            _semaphore = asyncio.Semaphore(concurrency)
            print(f"检测到 MiniMax 2.5 模型，账户类型: {account_type}, 并发限制: {concurrency}, 请求间隔: {REQUEST_DELAY}s")
        else:
            # 其他模型使用默认配置
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
You are a professional Knowledge Architect. Your task is to extract a comprehensive, structured Mind Map from a large document section.
The input text is a significant portion of a document (e.g., multiple pages).

CRITICAL RULES:
1. **Structure**: Identify the main hierarchy. Use Markdown headers (##, ###) for sections and subsections.
   - Start with Level 2 headers (##) for the main topics in this section.
   - Use Level 3 (###) and Level 4 (####) for deeper nesting.
2. **Content**: Use Markdown lists (-) for details under headers.
   - Do NOT just list keywords. Use complete, meaningful phrases.
   - Capture ALL key concepts, definitions, data points, and relationships.
   - Depth is good. Do not over-summarize.
3. **Format**:
   - output MUST be valid Markdown.
   - No "Here is the mind map" preamble.
   - Use standard indentation (2 spaces).

Example Output:
## Main Section Title
### Subsection 1.1
- Key Concept A
  - Definition: ...
  - Example: ...
### Subsection 1.2
- Key Concept B
  - Data point: 85% growth
"""

async def summarize_chunk(text_chunk: str, chunk_id: int, task=None, process_info: dict = None):
    """
    处理单个文本块 (Large Chunk Optimized)
    """
    # 提取章节标题（第一行）仅作为元数据，不强制使用
    lines = text_chunk.strip().split('\n')
    title = lines[0] if lines else f"Section {chunk_id + 1}"
    title = title.strip().lstrip('#').strip()

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
                    {"role": "user", "content": f"Analyze and structure the following text into a detailed Markdown mind map:\n\n{text_chunk}"}
                ],
                # 提高温度以增加多样性，但保持结构
                temperature=0.3,
                max_tokens=4096  # 增加输出长度限制
            )

            ai_content = response.choices[0].message.content

            # 验证结果并处理
            if ai_content and ai_content.strip():
                # 强制降级 Level 1 标题 -> Level 2
                # 避免 AI 只有 # Title 的情况破坏整体结构
                # 替换开头的 # (Space) 为 ## (Space)
                ai_content = re.sub(r'(^|\n)#\s', r'\1## ', ai_content)
                
                # 检查 AI 是否生成了标题 (## 或 ###...)
                # 如果 AI 输出是纯列表（没有 headers），我们需要补一个标题
                if not re.search(r'^#{2,6}\s', ai_content, re.MULTILINE):
                    result = f"## {title}\n{ai_content}"
                else:
                    # AI 生成了结构，直接使用
                    result = ai_content
            else:
                result = f"## {title}\n- (No content extracted)"

            # 更新进度（如果有 task 对象）
            if task and process_info:
                completed = process_info['completed'] + 1
                total = process_info['total']
                process_info['completed'] = completed
                progress = 50 + int((completed / total) * 45)
                task.progress = min(95, progress)
                task.message = f"AI 正在深入分析章节 {completed}/{total}..."

            return chunk_id, result

        except Exception as e:
            print(f"Error processing chunk {chunk_id}: {e}")
            await asyncio.sleep(1)
            # 失败时至少保留原文标题
            return chunk_id, f"## {title}\n- Error extracting content"

async def generate_root_summary(full_markdown: str):
    """
    生成根节点摘要 - 基于全文档结构
    """
    try:
        # 1. 提取大纲 (Table of Contents) 而不是截断文本
        # 提取所有 headers
        toc_lines = [line for line in full_markdown.split('\n') if line.strip().startswith('#')]
        toc_content = "\n".join(toc_lines)
        
        # 如果 TOC 太长，再进行截断（但保留了结构概览）
        if len(toc_content) > 15000:
             toc_content = toc_content[:15000] + "\n...(truncated)..."

        client = get_client()
        model = get_model()
        
        target_model = model
        if "deepseek" in model and "chat" in model:
            target_model = "deepseek-reasoner"
            
        response = await client.chat.completions.create(
            model=target_model,
            messages=[
                {"role": "system", "content": "You are an expert Knowledge Architect."},
                {"role": "user", "content": f"Based on the following document outline (Table of Contents), generate a single Root Node title (Level 1 #) and a high-level summary structure if needed.\n\nOutline:\n{toc_content}"}
            ],
            temperature=0.3,
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
    
    # 使用双换行分隔不同章节，保持结构清晰
    full_branches = "\n\n".join(branch_contents)
    
    # ==================== REDUCE Phase ====================
    if task:
        task.message = "正在生成知识结构..."
    
    try:
        root_structure = await generate_root_summary(full_branches)
        # 确保根节点只有一个 #，章节使用 ##
        # 先去掉 AI 输出中可能存在的多余 # 
        clean_branches = full_branches.replace('\n# ', '\n## ')
        final_output = f"{root_structure}\n\n{clean_branches}"
    except Exception as e:
        print(f"Reduce phase error: {e}")
        final_output = f"# 知识图谱\n\n{full_branches}"
    
    return final_output
