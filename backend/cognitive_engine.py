"""
认知引擎 - DeepSeek AI 处理模块
优化版：适配付费 API + 正确的 temperature + 修复信号量泄漏 + 支持动态配置
"""
import asyncio
import os
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
You are a professional Knowledge Architect. Your task is to extract a structured Mind Map from technical documentation.
Your output MUST be a valid Markdown list with proper hierarchical nesting.

CRITICAL RULES:
1. Use ONLY Markdown list syntax starting with "- " (dash followed by space).
2. Use EXACTLY 2 spaces per indentation level to show hierarchy.
3. NEVER use Markdown headers (#) in your output - use only list items.
4. Start your response DIRECTLY with the first list item - no intro text, no "Here is the mind map:" prefix.
5. Hierarchy depth should be reasonable (max 4 levels).
6. Focus on "Concepts", "Relations", and "Key Data".
7. Remove all conversational fillers and explanations.
8. If the chunk is empty or irrelevant, return nothing.

Example correct output:
- Main Category
  - Subcategory 1
    - Detail item A
    - Detail item B
  - Subcategory 2
    - Detail item C

WRONG examples (DO NOT do this):
✗ Here is the mind map: - Category
✗ # Category
  - Subcategory
✗ Category (missing dash)
✗ - Category (tab indentation - use spaces only)
"""

async def summarize_chunk(text_chunk: str, chunk_id: int, task=None, process_info: dict = None):
    """
    处理单个文本块
    修改：修复分层结构问题 - 保持 AI 生成的多层级缩进
    """
    # 提取章节标题（第一行）
    lines = text_chunk.strip().split('\n')
    title = lines[0] if lines else f"章节 {chunk_id + 1}"

    # 清理标题（去掉 # 符号，保留文字）
    title = title.strip().lstrip('#').strip()
    if not title:
        title = f"章节 {chunk_id + 1}"

    # 提取内容（去掉标题行，只保留内容部分给 AI 处理）
    content = '\n'.join(lines[1:]) if len(lines) > 1 else text_chunk

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
                    {"role": "user", "content": f"Convert the following section into a hierarchical Markdown mind map structure:\n\n{content}"}
                ],
                # 数据抽取/分析场景，使用 1.0
                temperature=1.0,
                max_tokens=2000
            )

            ai_content = response.choices[0].message.content

            # 关键修改：保持 AI 生成的多层级结构
            # 不要在 AI 内容前添加固定的缩进，而是保持其原有的层级关系
            if ai_content and ai_content.strip():
                # 将标题作为第一级节点，AI 生成的内容作为其子节点
                # 保持 AI 内容的缩进格式，只在整个内容前加 2 空格
                ai_lines = ai_content.strip().split('\n')
                indented_lines = []
                for line in ai_lines:
                    # 只对非空行添加缩进，空行保持原样
                    if line.strip():
                        # 保留原有缩进，并额外添加 2 空格使其成为 title 的子项
                        indented_lines.append('  ' + line)
                    # 空行直接跳过，不添加到结果中
                result = f"- {title}\n" + '\n'.join(indented_lines)
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
        model = get_model()
        
        # 如果当前是 deepseek-chat，且支持 deepseek-reasoner，可以特殊处理
        # 但为了通用性，默认使用当前选定的模型
        target_model = model
        if "deepseek" in model and "chat" in model:
            target_model = "deepseek-reasoner"
            
        response = await client.chat.completions.create(
            model=target_model,
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
        # 如果特殊模型失败，回退到主模型
        try:
            client = get_client()
            response = await client.chat.completions.create(
                model=get_model(),
                messages=[
                    {"role": "system", "content": "You are an expert at synthesizing complex information into a single root node and main branches for a Mind Map."},
                    {"role": "user", "content": f"Based on the following detailed branches, generate a Root Node and the top-level structure (Level 1 only).\n\nbranches:\n{full_markdown[:4000]}..."}
                ],
                temperature=1.0,
                max_tokens=1000
            )
            return response.choices[0].message.content
        except:
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
