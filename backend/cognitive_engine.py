"""
认知引擎 - DeepSeek AI 处理模块
优化版：适配付费 API + 正确的 temperature + 修复信号量泄漏 + 支持动态配置
"""
import asyncio
import os
import re
import atexit
try:
    from openai import AsyncOpenAI
except ImportError:
    # Creating a dummy class for testing purposes if openai is not installed
    class AsyncOpenAI:
        def __init__(self, api_key=None, base_url=None):
            pass

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


import time

# ==================== API 策略配置 (Optimization Strategies) ====================
MODEL_STRATEGIES = {
    # DeepSeek: 高并发 + 指数退避 (Adaptive Concurrency)
    "deepseek": {
        "type": "adaptive",
        "initial_concurrency": 20,
        "min_concurrency": 2,
        "backoff_base": 2,      # 指数退避基数
        "max_retries": 5,       # 最大重试次数
        "base_delay": 1.0       # 初始重试延迟 (秒)
    },
    # MiniMax: 严格限流 (Strict Rate Limiting)
    "minimax": {
        "type": "static",
        "rpm": 120,            # 默认 RPM (每分钟请求数)
        "concurrency": 10      # 限制最大并发数，防止瞬间堆积
    }
}

class RateLimiter:
    """
    令牌桶/漏桶算法实现的简易限流器
    确保请求间隔满足 RPM 限制
    """
    def __init__(self, rpm):
        self.interval = 60.0 / rpm
        self.last_request_time = 0
        self.lock = asyncio.Lock()

    async def acquire(self):
        async with self.lock:
            now = time.time()
            # 计算自上次请求以来经过的时间
            elapsed = now - self.last_request_time
            
            # 如果经过时间小于最小间隔，则等待
            if elapsed < self.interval:
                wait_time = self.interval - elapsed
                await asyncio.sleep(wait_time)
            
            self.last_request_time = time.time()

# 全局限流器和信号量
_rate_limiter = None
_semaphore = None

def get_strategy(model_name: str) -> dict:
    """根据模型名称获取策略"""
    if "deepseek" in model_name.lower():
        return MODEL_STRATEGIES["deepseek"]
    else:
        # 默认为 MiniMax 策略 (涵盖 minimax, abab 等)
        return MODEL_STRATEGIES["minimax"]

def get_rate_limiter():
    """获取或初始化限流器和信号量"""
    global _rate_limiter, _semaphore
    
    if _semaphore is None:
        model = get_model()
        strategy = get_strategy(model)
        
        if strategy["type"] == "static": # MiniMax
            # 获取账户类型以调整 RPM
            account_type = get_account_type()
            # 免费版更严格
            if account_type == "free":
                rpm = 20  # 极度保守
                concurrency = 2
            else:
                rpm = strategy["rpm"] # 默认 120
                concurrency = strategy["concurrency"]
            
            _rate_limiter = RateLimiter(rpm)
            _semaphore = asyncio.Semaphore(concurrency)
            print(f"策略应用: MiniMax (Strict Limit), RPM={rpm}, Concurrency={concurrency}")
            
        else: # DeepSeek (Adaptive)
            # DeepSeek 不需要严格的 RateLimiter，只需信号量控制并发
            _rate_limiter = None 
            concurrency = strategy["initial_concurrency"]
            _semaphore = asyncio.Semaphore(concurrency)
            print(f"策略应用: DeepSeek (Adaptive), Start Concurrency={concurrency}")
            
    return _semaphore, _rate_limiter

def cleanup():
    global _semaphore, _rate_limiter
    _semaphore = None
    _rate_limiter = None

atexit.register(cleanup)

# 任务超时配置
TASK_TIMEOUT = 900  # 15分钟，给予更多重试时间

SYSTEM_PROMPT = """
You are a professional Knowledge Architect. Your task is to extract a comprehensive, structured Mind Map from a large document section.
The input text is a significant portion of a document (e.g., multiple pages).

CRITICAL RULES - MUST FOLLOW EXACTLY:

1. **Structure Hierarchy (MOST IMPORTANT)**:
   - **Respect the Output Context**: If provided, nest your output under the specified Parent Context.
   - **Flexible Headers**: Use Markdown headers (#, ##, ###, ####) to represent the document's natural hierarchy.
   - **DO NOT FORCE Level 2**: If a section is a subsection (e.g., 1.1.2), use the appropriate header level (e.g., ### or ####).
   - NEVER skip levels (e.g., don't go from ## directly to ####)

2. **List Indentation - DEEP NESTING REQUIRED**:
   - Under each header, use indented lists to capture details
   - Level 1 list:  "- Main point" (no leading spaces)
   - Level 2 list: "  - Sub-point" (2 spaces indent)
   - Level 3 list: "    - Detail" (4 spaces indent)
   - Level 4 list: "      - Fine detail" (6 spaces indent)
   - Aim for AT LEAST 3-4 levels of depth for comprehensive coverage

3. **Content Requirements**:
   - Capture ALL key concepts, definitions, data points, examples, and relationships
   - Use complete, meaningful phrases (NOT just single keywords)
   - Include specific numbers, dates, percentages when present in source
   - Preserve cause-effect relationships and logical connections
   - Do NOT over-summarize - depth and detail are PREFERRED

4. **Format Requirements**:
   - Output MUST be valid Markdown with proper indentation
   - NO preamble like "Here is the mind map"
   - Use consistent 2-space indentation for nested lists
   - Blank lines between major sections are OK

EXAMPLE OUTPUT (Flexible Hierarchy):
### 1.1. Background (Context: Chapter 1 > Section 1)
#### 1.1.1 Historical Context
- Key Event A
  - Date: 1990
    - Impact: Started the revolution
"""

async def summarize_chunk(text_chunk: str, chunk_id: int, task=None, process_info: dict = None, parent_context: str = ""):
    """
    处理单个文本块 (Large Chunk Optimized)
    :param parent_context: 上下文信息 (e.g., "Chapter 1 > Section 2")
    """
    # 提取章节标题（第一行）仅作为元数据
    lines = text_chunk.strip().split('\n')
    title = lines[0] if lines else f"Section {chunk_id + 1}"
    title = title.strip().lstrip('#').strip()

    # 【修复 P2-1】在 chunk 开始处理时也更新进度
    if task and process_info:
        current = process_info['completed']
        total = process_info['total']
        progress = 50 + int((current / total) * 45) + 2
        task.progress = min(95, progress)
        task.message = f"AI 正在分析章节 {current + 1}/{total}..."

    # 获取策略组件
    semaphore, rate_limiter = get_rate_limiter()
    model = get_model()
    strategy = get_strategy(model)
    
    max_retries = strategy.get("max_retries", 3) if strategy["type"] == "adaptive" else 1
    base_delay = strategy.get("base_delay", 1.0)

    async with semaphore:
        for attempt in range(max_retries + 1):
            try:
                # 1. 严格限流 (MiniMax)
                if rate_limiter:
                    await rate_limiter.acquire()
                
                # 2. 准备请求
                client = get_client()

                # 构建带上下文的用户提示 - 强化版
                user_prompt = f"""
CONTEXT: {parent_context if parent_context else "Document Root / Preamble"}

INSTRUCTION: 
The text below is a detailed section located under the path "{parent_context if parent_context else 'Document Root'}". 
You MUST start your Mind Map output by acknowledging this hierarchy. 
- If the context ends with a specific header (e.g., "Season 1"), your first node SHOULD be a child of that header (e.g., a sub-point or next level header).
- Do not create a new root node if it conflicts with the provided context.
- Maintain the depth. If the context is deep (e.g. ###), your content should likely start at #### or as a list item.

TEXT CONTENT:
{text_chunk}
"""
                # 3. 发送请求
                response = await client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=0.3,
                    max_tokens=4096
                )

                ai_content = response.choices[0].message.content

                # 验证结果并处理
                result = ""
                if ai_content and ai_content.strip():
                    # 简单清理：如果 AI 仍然输出了 Markdown 代码块标记
                    ai_content = ai_content.replace("```markdown", "").replace("```", "").strip()
                    result = ai_content
                else:
                    result = f"## {title}\n- (No content extracted)"

                # 更新进度（chunk 完成后）
                if task and process_info:
                    completed = process_info['completed'] + 1
                    total = process_info['total']
                    process_info['completed'] = completed
                    progress = 50 + int((completed / total) * 45)
                    task.progress = min(95, progress)
                    task.message = f"章节 {completed}/{total} 分析完成"

                return chunk_id, result

            except Exception as e:
                error_msg = str(e)
                print(f"Chunk {chunk_id} error (Attempt {attempt + 1}/{max_retries + 1}): {e}")
                
                # 如果是最后一次尝试，放弃
                if attempt == max_retries:
                    return chunk_id, f"## {title}\n- Error extracting content: {error_msg}"
                
                # 策略: 指数退避 (Adaptive / DeepSeek)
                if "429" in error_msg or "rate limit" in error_msg.lower():
                    # 计算退避时间: base * (2 ^ attempt)
                    # 例如: 1s, 2s, 4s, 8s, 16s
                    sleep_time = base_delay * (strategy.get("backoff_base", 2) ** attempt)
                    print(f"Rate limited (429). Retrying in {sleep_time}s...")
                    await asyncio.sleep(sleep_time)
                else:
                    # 其他错误 (500等)，也稍微等待
                    await asyncio.sleep(1)

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


async def extract_global_outline(full_text: str) -> dict:
    """
    Pass 1: 提取全局目录骨架
    返回结构: {chunk_index: "Context String"}
    """
    try:
        # 简单启发式：提取 Markdown 标题行
        headers = []
        for line in full_text.split('\n'):
            if line.strip().startswith('#'):
                headers.append(line.strip())
        
        if not headers:
            return {}

        # 如果标题太多，简化处理（避免 Token 超限）
        if len(headers) > 500:
            headers = headers[:500] + ["... (truncated)"]
        
        outline_text = "\n".join(headers)
        
        # 让 AI 分析每个 chunk 大致对应的章节
        # 注意：这里有一个难点，如何将 text chunk 映射回 outline
        # 简化策略：
        # 假设 chunks 是按顺序切分的。
        # 我们让 AI 浏览 Outline，并生成一个"章节导航图"
        
        return outline_text
    except Exception as e:
        print(f"Outline extraction failed: {e}")
        return ""

async def generate_mindmap_structure(chunks: list, task=None):
    """
    Map-Reduce 实现 - 层次感知增强版 (Hierarchy-Aware)
    """
    if not chunks:
        return "# Empty Document"

    total_chunks = len(chunks)
    
    # ==================== Pass 1: Global Context (Optional) ====================
    # 由于 chunks 已经被切分，我们很难精确还原每个 chunk 对应的具体章节
    # 但我们可以利用 chunk[0] 的第一行（通常 parser 会保留部分标题信息）
    # 或者，我们相信 `summarize_chunk` 内部的上下文提示
    
    # 策略调整：与其做复杂的 Outline Mapping，不如在 Map 阶段
    # 让 AI 自己根据 chunk 内容推断 context (Self-Contextualization)
    # 或者，如果 Parser 在切分时能保留 metadata 最好。
    # 鉴于目前 parser_service.py 传过来的是纯文本 list，我们采用 "Sliding Context" 策略
    # 但为了稳健，我们先采用 "独立处理 + 宽松层级" (已在 summarize_chunk 实现)
    
    # ==================== MAP Phase ====================
    process_info = {'completed': 0, 'total': total_chunks}
    
    # 构造任务，传入 Context
    tasks = []
    for i, chunk_data in enumerate(chunks):
        # 兼容旧代码（如果是字符串）和新代码（如果是字典）
        if isinstance(chunk_data, str):
            content = chunk_data
            context = ""
        else:
            content = chunk_data.get('content', '')
            context = chunk_data.get('context', '')
            
        tasks.append(summarize_chunk(content, i, task, process_info, parent_context=context))

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

    # 排序
    sorted_results = sorted(valid_results, key=lambda x: x[0])
    branch_contents = [r[1] for r in sorted_results]

    if not branch_contents:
        return "# No valid content extracted"

    # ==================== REDUCE Phase ====================
    if task:
        task.message = "正在生成知识结构..."

    normalized_branches = []
    for branch in branch_contents:
        # 清理多余空行
        branch = branch.strip()
        
        # 移除之前的 "强制转 ##" 逻辑
        # 只做最小程度的清理
        normalized_branches.append(branch)

    # 拼接
    full_branches = "\n\n".join(normalized_branches)

    try:
        # 生成根节点摘要
        root_structure = await generate_root_summary(full_branches)
        
        # 最终合并
        final_output = f"{root_structure}\n\n{full_branches}"
    except Exception as e:
        print(f"Reduce phase error: {e}")
        final_output = f"# 知识图谱\n\n{full_branches}"

    return final_output
