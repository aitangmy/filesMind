"""
认知引擎 - DeepSeek AI 处理模块
优化版：适配付费 API + 正确的 temperature + 修复信号量泄漏 + 支持动态配置
"""

import asyncio
import re
import atexit
import json

try:
    from openai import AsyncOpenAI
except ImportError:
    # Creating a dummy class for testing purposes if openai is not installed
    class AsyncOpenAI:
        def __init__(self, api_key=None, base_url=None):
            pass


# DeepSeek API 配置 - 使用全局客户端，支持动态更新
_client = None

# Advanced limits configuration
_engine_settings = {"concurrency": 5, "temperature": 0.3, "max_tokens": 8192}

ENGINE_LIMITS = {
    "concurrency": {"min": 1, "max": 10, "default": 5},
    "temperature": {"min": 0.0, "max": 1.0, "default": 0.3},
    "max_tokens": {"min": 1000, "max": 16000, "default": 8192},
}


def get_client():
    """获取或创建全局客户端"""
    global _client
    if _client is None:
        # 默认使用空配置，等待 update_client_config 注入
        _client = AsyncOpenAI(api_key="", base_url="https://api.deepseek.com")
    return _client


def update_client_config(config: dict):
    """
    动态更新客户端配置
    """
    global _client
    base_url = config.get("base_url", "https://api.minimaxi.com/v1")
    api_key = config.get("api_key", "")
    model = config.get("model", "MiniMax-M2.5")
    advanced = config.get("advanced", {})

    global _engine_settings
    if advanced:
        _engine_settings["concurrency"] = _clamp_int(
            advanced.get("engine_concurrency"),
            ENGINE_LIMITS["concurrency"]["default"],
            ENGINE_LIMITS["concurrency"]["min"],
            ENGINE_LIMITS["concurrency"]["max"],
        )
        _engine_settings["temperature"] = _clamp_float(
            advanced.get("engine_temperature"),
            ENGINE_LIMITS["temperature"]["default"],
            ENGINE_LIMITS["temperature"]["min"],
            ENGINE_LIMITS["temperature"]["max"],
        )
        _engine_settings["max_tokens"] = _clamp_int(
            advanced.get("engine_max_tokens"),
            ENGINE_LIMITS["max_tokens"]["default"],
            ENGINE_LIMITS["max_tokens"]["min"],
            ENGINE_LIMITS["max_tokens"]["max"],
        )
        _reset_engine_runtime_limiter()

    # 1. Base URL 规范化 (自动补全 /v1)
    if not base_url.endswith("/v1"):
        base_url = f"{base_url.rstrip('/')}/v1"

    if not api_key:
        # 针对 Ollama 允许空 Key
        if "ollama" in base_url.lower() or "11434" in base_url:
            api_key = "ollama"  # 占位符
        else:
            raise ValueError("API Key 不能为空")

    print(f"更新配置: base_url={base_url}, model={model}")

    # 创建新客户端
    _client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    # 更新模型
    set_model(model)
    print(f"Client updated: base_url={base_url}, model={model}")


def _clamp_int(raw, default, min_v, max_v):
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = int(default)
    return max(min_v, min(max_v, value))


def _clamp_float(raw, default, min_v, max_v):
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = float(default)
    return max(min_v, min(max_v, value))


def _reset_engine_runtime_limiter():
    global _semaphore, _rate_limiter
    _semaphore = None
    _rate_limiter = None


async def fetch_models_detailed(base_url: str, api_key: str = "") -> dict:
    """从 API 获取模型列表，返回结构化结果"""
    try:
        # 1. Base URL 规范化
        if not base_url.endswith("/v1"):
            base_url = f"{base_url.rstrip('/')}/v1"

        # 2. 针对 Ollama 的特殊处理
        if not api_key or "ollama" in base_url.lower() or "11434" in base_url:
            api_key = "ollama"

        temp_client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=5.0,  # 短超时防止卡死
        )

        response = await temp_client.models.list()
        models = sorted([model.id for model in response.data])
        return {"success": True, "models": models, "error": ""}
    except Exception as e:
        print(f"Fetch models failed: {e}")
        return {"success": False, "models": [], "error": str(e)}


async def fetch_models(base_url: str, api_key: str = "") -> list:
    """兼容旧调用：仅返回模型数组"""
    result = await fetch_models_detailed(base_url, api_key)
    return result.get("models", [])


async def test_connection(config: dict) -> dict:
    """
    测试配置是否可用 - 增强版
    """
    base_url = config.get("base_url", "https://api.minimaxi.com/v1")
    api_key = config.get("api_key", "")
    model = config.get("model", "MiniMax-M2.5")

    # 1. Base URL 规范化
    if not base_url.endswith("/v1"):
        base_url = f"{base_url.rstrip('/')}/v1"

    # 针对 Ollama 允许空 Key
    if not api_key:
        if "ollama" in base_url.lower() or "11434" in base_url:
            api_key = "ollama"
        else:
            return {"success": False, "message": "API Key 不能为空"}

    print(f"测试连接: base_url={base_url}, model={model}")

    # 创建临时客户端测试
    test_client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    try:
        # 发送一个简单的测试请求
        response = await test_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Reply with exactly: 'OK'"},
            ],
            max_tokens=10,
            timeout=30,  # 30秒超时
        )

        # 验证响应有效
        if response and response.choices and len(response.choices) > 0:
            content = response.choices[0].message.content
            print(f"测试响应: {content}")
            return {"success": True, "message": f"连接成功！模型响应: {content[:50]}...", "model": model}
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
        elif "econnrefused" in error_msg.lower() or "connection refused" in error_msg.lower():
            return {"success": False, "message": "连接被拒绝，请检查 Ollama 是否已启动 (ollama serve)"}
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
    _reset_engine_runtime_limiter()


def get_model() -> str:
    """获取当前模型"""
    return _current_model


# ==================== MiniMax 2.5 速率限制配置 ====================
# MiniMax 2.5 文本模型速率限制 (RPM: 每分钟请求数)
# 免费用户: 20 RPM
# 充值用户: 500 RPM
MINIMAX_2_5_RATE_LIMITS = {"free": {"rpm": 20, "tpm": 1000000}, "paid": {"rpm": 500, "tpm": 20000000}}

# MiniMax 2.5 模型标识（支持多种命名）
MINIMAX_2_5_MODELS = ["MiniMax-M2.5", "MiniMax-M2.5-highspeed", "abab6.5s-chat", "abab6.5g-chat"]


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
        _reset_engine_runtime_limiter()


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
        "backoff_base": 2,  # 指数退避基数
        "max_retries": 5,  # 最大重试次数
        "base_delay": 1.0,  # 初始重试延迟 (秒)
    },
    # MiniMax: 严格限流 (Strict Rate Limiting)
    "minimax": {
        "type": "static",
        "rpm": 120,  # 默认 RPM (每分钟请求数)
        "concurrency": 10,  # 限制最大并发数，防止瞬间堆积
    },
}


class RateLimiter:
    """
    令牌桶/漏桶算法实现的简易限流器
    确保请求间隔满足 RPM 限制
    """

    def __init__(self, rpm):
        self.interval = 60.0 / rpm
        self.last_request_time = 0.0
        self.lock = asyncio.Lock()

    async def acquire(self):
        async with self.lock:
            now = time.time()
            target_time = max(now, self.last_request_time + self.interval)
            self.last_request_time = target_time
            wait_time = target_time - now

        if wait_time > 0.001:
            await asyncio.sleep(wait_time)


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

        if strategy["type"] == "static":  # MiniMax
            # 获取账户类型以调整 RPM
            account_type = get_account_type()
            # 免费版更严格
            if account_type == "free":
                rpm = 20  # 极度保守
                concurrency = _engine_settings.get("concurrency", ENGINE_LIMITS["concurrency"]["default"])
            else:
                rpm = strategy.get("rpm", 120)
                concurrency = _engine_settings.get("concurrency", ENGINE_LIMITS["concurrency"]["default"])

            _rate_limiter = RateLimiter(rpm)
            _semaphore = asyncio.Semaphore(concurrency)
            print(f"策略应用: MiniMax (Strict Limit), RPM={rpm}, Concurrency={concurrency}")

        else:  # DeepSeek (Adaptive)
            # DeepSeek 不需要严格的 RateLimiter，只需信号量控制并发
            _rate_limiter = None
            concurrency = _engine_settings.get("concurrency", ENGINE_LIMITS["concurrency"]["default"])
            _semaphore = asyncio.Semaphore(concurrency)
            print(f"策略应用: DeepSeek (Adaptive), Start Concurrency={concurrency}")

    return _semaphore, _rate_limiter


def cleanup():
    global _semaphore, _rate_limiter
    _semaphore = None
    _rate_limiter = None


atexit.register(cleanup)

# (Task timeout is now managed by the frontend settings and injected into app.py's task runner)
SYSTEM_PROMPT = """
你是一位专业的知识架构师。你的任务是从文档段落中提取完整、结构化的思维导图。

【最高优先级规则 - 标题 1:1 保留】：
- 输入文本中出现的 **每一个** 标题（# / ## / ### / #### / ##### / ######）都 **必须** 在输出中保留
- **禁止省略、合并或删除** 任何标题，即使内容看似重复或不重要
- 如果输入有 N 个标题，你的输出也必须有 N 个标题

【最高优先级规则 - 保留原始标题级别】：
- **严格保留** 输入文本中标题的原始级别（# 的数量）
- 如果输入中有 ## 标题，输出中必须保持为 ##，不要改成 ### 或其他级别
- 不要升级（把 ### 变成 ##），也不要降级（把 ## 变成 ###）
- 绝对禁止生成 # （H1）标题，H1 只用于文档根节点

【结构层级规则】：
1. **尊重上下文路径**：如果提供了父级上下文（Context），将内容正确嵌套在该路径下
2. **保留原始标题级别**：用 Markdown 标题表示文档的自然层级，不要修改标题级别
3. **禁止跳级**：不要从 ## 直接跳到 ####
4. **context 中的标题不要重复**：上下文路径中已经包含的标题，不要在输出中再次创建

【列表缩进 - 要求深度嵌套】：
- 每个标题下使用缩进列表捕获细节
- 第 1 层列表："- 要点"（无前导空格）
- 第 2 层列表："  - 子要点"（2 个空格缩进）
- 第 3 层列表："    - 细节"（4 个空格缩进）
- 第 4 层列表："      - 更细节"（6 个空格缩进）
- 目标：至少 3-4 层深度

【输入噪声处理 - 重要】：
输入文本来自 PDF 自动解析，可能包含解析残留的噪声内容，请自动识别并忽略以下类型：
1. 页眉页脚残留（如重复出现的文档标题、公司名称、日期）
2. 页码（如 "-3-"、"Page 5"、"第3页"、"3 / 20"）
3. 水印文字（如 "CONFIDENTIAL"、"DRAFT"、"内部文件"、"仅供参考"）
4. 分隔线和装饰符号（如 "---"、"==="、"***"、"■ ▲ ● ◆"）
5. 版权声明和免责声明
6. 纯 URL 或文件路径
如果发现这些内容，直接跳过，只关注实质性的文档内容。不要将噪声内容作为节点输出。

【内容要求】：
- 捕获所有关键概念、定义、数据点、示例和关系
- 使用完整有意义的短语（不要只写单个关键词）
- 保留原文中的具体数字、日期、百分比
- 保留因果关系和逻辑联系
- **不要过度摘要** — 深度和细节优先

【格式要求】：
- 输出必须是有效的 Markdown
- 不要写任何前言（如"以下是思维导图"）
- 使用一致的 2 空格缩进
- 主要章节之间可以有空行

输出示例：
## 1. 软件工程概述
### 1.1 背景
#### 1.1.1 历史沿革
- 关键事件 A
  - 时间：1990 年
    - 影响：引发了变革
"""


async def summarize_chunk(
    text_chunk: str, chunk_id: int, task=None, process_info: dict = None, parent_context: str = ""
):
    """
    处理单个文本块 (Large Chunk Optimized)
    :param parent_context: 上下文信息 (e.g., "Chapter 1 > Section 2")
    """
    # 提取章节标题（第一行）仅作为元数据
    lines = text_chunk.strip().split("\n")
    title = lines[0] if lines else f"Section {chunk_id + 1}"
    title = title.strip().lstrip("#").strip()

    # 【修复 P2-1】在 chunk 开始处理时也更新进度
    if task and process_info:
        current = process_info["completed"]
        total = process_info["total"]
        progress = 50 + int((current / total) * 45) + 2
        task.progress = min(95, progress)
        task.message = f"AI 正在分析章节 {current + 1}/{total}..."

    # 获取策略组件
    semaphore, rate_limiter = get_rate_limiter()
    model = get_model()
    strategy = get_strategy(model)

    max_retries = strategy.get("max_retries", 3) if strategy["type"] == "adaptive" else 1
    base_delay = strategy.get("base_delay", 1.0)

    if task and getattr(task, "cancel_requested", False):
        raise asyncio.CancelledError("Task was cancelled by user")

    async with semaphore:
        for attempt in range(max_retries + 1):
            if task and getattr(task, "cancel_requested", False):
                raise asyncio.CancelledError("Task was cancelled by user")
            try:
                # 1. 严格限流 (MiniMax)
                if rate_limiter:
                    await rate_limiter.acquire()

                # 2. 准备请求
                client = get_client()

                # 构建带上下文的用户提示 - 中文强化版
                # 统计输入标题数量（用于验证）
                input_header_count = sum(1 for line in text_chunk.split("\n") if re.match(r"^#{1,6}\s", line.strip()))

                user_prompt = f"""
【当前位置】：{parent_context if parent_context else "文档根节点"}

【任务说明】：
以下文本位于路径 "{parent_context if parent_context else "文档根节点"}" 下。
请严格遵守以下要求：
1. 保留输入文本中标题的原始级别（# 的数量），不要修改标题级别
2. 输入文本中包含 {input_header_count} 个标题，你的输出中也必须包含这 {input_header_count} 个标题（1:1 保留）
3. context 路径中的标题已在全局存在，不要在输出中重复它们
4. 禁止生成 # (H1) 标题，H1 只用于文档根节点

【注意】：本段文本来自 PDF 自动解析，可能包含页眉页脚、水印、页码等噪声内容，请智能过滤，不要将它们作为节点输出。

【原文内容】：
{text_chunk}
"""
                # 3. 发送请求
                response = await client.chat.completions.create(
                    model=model,
                    messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_prompt}],
                    temperature=_engine_settings.get("temperature", 0.3),
                    max_tokens=_engine_settings.get("max_tokens", 8192),
                )

                ai_content = response.choices[0].message.content

                # 验证结果并处理
                result = ""
                if ai_content and ai_content.strip():
                    # 简单清理：如果 AI 仍然输出了 Markdown 代码块标记
                    ai_content = ai_content.replace("```markdown", "").replace("```", "").strip()
                    result = ai_content
                else:
                    result = f"## {title}\n- (未提取到内容)"

                # 标题计数验证
                output_header_count = sum(1 for line in result.split("\n") if re.match(r"^#{1,6}\s", line.strip()))
                if input_header_count > 0 and output_header_count > 0:
                    retention_rate = output_header_count / input_header_count
                    if retention_rate < 0.5:
                        print(
                            f"\u26a0\ufe0f Chunk {chunk_id} 标题保留率低: 输入 {input_header_count} \u2192 输出 {output_header_count} ({retention_rate:.0%})"
                        )
                    else:
                        print(
                            f"\u2705 Chunk {chunk_id} 标题保留: 输入 {input_header_count} \u2192 输出 {output_header_count} ({retention_rate:.0%})"
                        )

                # 更新进度（chunk 完成后）
                if task and process_info:
                    completed = process_info["completed"] + 1
                    total = process_info["total"]
                    process_info["completed"] = completed
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
    只生成 H1 标题 + 列表摘要，禁止生成 H2 等子标题
    """
    try:
        # 1. 提取大纲 (Table of Contents) 而不是截断文本
        # 提取所有 headers
        toc_lines = [line for line in full_markdown.split("\n") if line.strip().startswith("#")]
        toc_content = "\n".join(toc_lines)

        # 如果 TOC 太长，再进行截断（但保留了结构概览）
        if len(toc_content) > 15000:
            toc_content = toc_content[:15000] + "\n...(truncated)..."

        client = get_client()
        model = get_model()

        # 始终使用 deepseek-chat，不切换 reasoner（避免冗长思考链浪费 token）
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是一位专业的知识架构师。"},
                {
                    "role": "user",
                    "content": f"""根据以下文档目录大纲，生成一个根节点标题和简要的高层结构概述。

【输出格式要求】：
1. 第一行必须是一级标题 # （只能有一个 #）
2. 后面用无序列表（-）简要描述文档的主要模块/结构
3. **绝对禁止** 使用 ##、###、#### 等任何子标题
4. 只输出 Markdown，不要写前言

【正确示例】：
# 文档标题
- 模块一：xxx
- 模块二：xxx
- 模块三：xxx

目录大纲：
{toc_content}""",
                },
            ],
            temperature=_engine_settings.get("temperature", ENGINE_LIMITS["temperature"]["default"]),
            max_tokens=_engine_settings.get("max_tokens", ENGINE_LIMITS["max_tokens"]["default"]),
        )

        # 后置防护：移除 AI 可能误生成的 H2+ 标题
        result = response.choices[0].message.content
        sanitized_lines = []
        for line in result.split("\n"):
            stripped = line.strip()
            if re.match(r"^#{2,6}\s", stripped):
                # H2+ 标题转为列表项
                title_text = re.sub(r"^#{2,6}\s+", "", stripped)
                sanitized_lines.append(f"- {title_text}")
            else:
                sanitized_lines.append(line)
        return "\n".join(sanitized_lines)
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
        for line in full_text.split("\n"):
            if line.strip().startswith("#"):
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


def sanitize_branch(branch: str) -> str:
    """
    轻量级清理：只处理 AI 输出中的明显错误，不修改标题级别

    1. 将 H1 (#) 标题降级为 H2 (##)，因为 H1 只属于全局根节点
    2. 不平移其他标题级别，保留 AI 输出的原始层级
    """
    header_pattern = re.compile(r"^(#{1,6})\s+(.*)")
    result_lines = []
    for line in branch.split("\n"):
        m = header_pattern.match(line.strip())
        if m and len(m.group(1)) == 1:
            # H1 → H2
            result_lines.append(f"## {m.group(2)}")
        else:
            result_lines.append(line)
    return "\n".join(result_lines)


async def generate_mindmap_structure(chunks: list, task=None):
    """
    Map-Reduce 实现 - 层次感知增强版 (Hierarchy-Aware)
    """
    if not chunks:
        return "# Empty Document"

    total_chunks = len(chunks)

    # ==================== MAP Phase ====================
    process_info = {"completed": 0, "total": total_chunks}

    # 构造任务，传入 Context
    tasks_list = []
    for i, chunk_data in enumerate(chunks):
        # 兼容旧代码（如果是字符串）和新代码（如果是字典）
        if isinstance(chunk_data, str):
            content = chunk_data
            context = ""
        else:
            content = chunk_data.get("content", "")
            context = chunk_data.get("context", "")

        tasks_list.append(summarize_chunk(content, i, task, process_info, parent_context=context))

    results = await asyncio.gather(*tasks_list, return_exceptions=True)

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

    # ==================== REDUCE Phase: 轻量级清理 ====================
    if task:
        task.message = "正在生成知识结构..."

    sanitized_branches = []
    for branch in branch_contents:
        branch = branch.strip()
        # 只做轻量级清理：H1 → H2，不平移其他标题
        sanitized = sanitize_branch(branch)
        sanitized_branches.append(sanitized)

    # 拼接
    full_branches = "\n\n".join(sanitized_branches)

    try:
        # 生成根节点摘要
        root_structure = await generate_root_summary(full_branches)

        # 只提取 H1 标题行，丢弃列表项等描述性内容
        # 这些内容如果留在最终 Markdown 中，会在 parse_markdown_to_tree
        # 中变成树节点，干扰真正的文档层级结构
        h1_line = "# 知识图谱"  # 默认标题
        for line in root_structure.split("\n"):
            if line.strip().startswith("# ") and not line.strip().startswith("## "):
                h1_line = line.strip()
                break

        # 最终合并：H1 标题 + 各 chunk 的内容
        final_output = f"{h1_line}\n\n{full_branches}"
    except Exception as e:
        print(f"Reduce phase error: {e}")
        final_output = f"# 知识图谱\n\n{full_branches}"

    return final_output


def _is_minimax_backend(model: str, client) -> bool:
    """Detect MiniMax-compatible backend by model id or base_url."""
    model_lower = (model or "").lower()
    if "minimax" in model_lower or model_lower.startswith("abab"):
        return True
    if is_minimax_2_5_model(model):
        return True

    base_url = str(getattr(client, "base_url", "")).lower()
    return "minimaxi.com" in base_url


def _should_use_response_format(model: str, client) -> bool:
    """Use structured response format only for backends with better compatibility."""
    return not _is_minimax_backend(model, client)


def _is_response_format_error(error_message: str) -> bool:
    msg = (error_message or "").lower()
    if "response_format" in msg:
        return True
    return "expr_path=response_format" in msg


_REFINE_NOISE_RE = re.compile(
    r"^(?:"
    r"-\s*\d+\s*-"
    r"|page\s+\d+"
    r"|\d+\s*/\s*\d+"
    r"|\d+\s+of\s+\d+"
    r"|confidential|draft|internal"
    r"|内部|机密|仅供参考|草稿"
    r")$",
    re.IGNORECASE,
)
_REFINE_DECORATIVE_RE = re.compile(r"^[\s\-=_~*#★☆■▲●◆○△◇•·]{2,}$")
_REFINE_URL_RE = re.compile(r"^https?://", re.IGNORECASE)
_REFINE_PATH_RE = re.compile(r"^(?:[A-Z]:\\|/(?:usr|home|var|etc|opt|tmp)/)", re.IGNORECASE)
_REFINE_DIGIT_RE = re.compile(r"^\d{2,}$")
_REFINE_DIAGRAM_LABEL_RE = re.compile(r"^[A-Za-z]{1,4}\s*\([^)]{1,30}\)$")
_REFINE_MD_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")


def _normalize_refine_text(value: str) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    text = re.sub(r"^[\-*•\d\.\)\(]+", "", text).strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _is_refine_noise(text: str) -> bool:
    if not text:
        return True
    if len(text) < 2:
        return True
    if _REFINE_NOISE_RE.match(text):
        return True
    if _REFINE_DECORATIVE_RE.match(text):
        return True
    if _REFINE_URL_RE.match(text):
        return True
    if _REFINE_PATH_RE.match(text):
        return True
    if _REFINE_DIGIT_RE.match(text):
        return True
    if _REFINE_DIAGRAM_LABEL_RE.match(text):
        return True
    if _REFINE_MD_TABLE_SEPARATOR_RE.match(text):
        return True
    return False


def _sanitize_refine_items(items: list) -> list:
    sanitized = []
    seen_topics = set()
    for raw in items:
        if not isinstance(raw, dict):
            continue

        topic = _normalize_refine_text(str(raw.get("topic", "")))
        if _is_refine_noise(topic):
            continue
        if len(topic) > 120:
            topic = topic[:120].rstrip()

        topic_key = topic.lower()
        if topic_key in seen_topics:
            continue
        seen_topics.add(topic_key)

        details_raw = raw.get("details", [])
        if isinstance(details_raw, str):
            details_raw = [details_raw]
        if not isinstance(details_raw, list):
            details_raw = []

        details = []
        seen_details = set()
        for detail in details_raw:
            text = _normalize_refine_text(str(detail))
            if _is_refine_noise(text):
                continue
            if len(text) > 160:
                text = text[:160].rstrip()
            key = text.lower()
            if key in seen_details:
                continue
            seen_details.add(key)
            details.append(text)
            if len(details) >= 12:
                break

        sanitized.append({"topic": topic, "details": details})
        if len(sanitized) >= 30:
            break

    return sanitized


async def _create_refine_completion(client, request_kwargs: dict, use_response_format: bool):
    """
    Send refine request with optional response_format.
    Some providers reject response_format; if so, retry without it.
    """
    if not use_response_format:
        return await client.chat.completions.create(**request_kwargs)

    try:
        return await client.chat.completions.create(
            **request_kwargs,
            response_format={"type": "json_object"},
        )
    except Exception as e:
        if _is_response_format_error(str(e)):
            print("Refine node: response_format not supported, retrying without it.")
            return await client.chat.completions.create(**request_kwargs)
        raise


def _extract_first_json_payload(text: str) -> str:
    if not text:
        return ""

    start = -1
    for i, ch in enumerate(text):
        if ch in "[{":
            start = i
            break
    if start == -1:
        return ""

    stack = []
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue
        if ch in "[{":
            stack.append(ch)
            continue
        if ch in "]}":
            if not stack:
                return ""
            opener = stack.pop()
            if (opener == "[" and ch != "]") or (opener == "{" and ch != "}"):
                return ""
            if not stack:
                return text[start : i + 1]
    return ""


def _normalize_refine_response_text(content: str) -> str:
    if not isinstance(content, str):
        return ""

    cleaned = content.replace("```json", "").replace("```", "").strip()
    if not cleaned:
        return ""

    # MiniMax/OpenAI-compatible responses may carry chain-of-thought in <think> blocks.
    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", cleaned, flags=re.IGNORECASE).strip()
    if not cleaned:
        return ""

    payload = _extract_first_json_payload(cleaned)
    return payload or cleaned


def _parse_refine_response(content: str, node_title: str) -> list:
    """Parse model output to list[dict]."""
    if not content:
        return []

    cleaned = _normalize_refine_response_text(content)
    if not cleaned:
        return []

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        print(f"JSON Parse Error for node {node_title}: {cleaned[:100]}...")
        return []

    if isinstance(data, list):
        return _sanitize_refine_items(data)

    if isinstance(data, dict):
        for key in ["items", "nodes", "children", "data"]:
            value = data.get(key)
            if isinstance(value, list):
                return _sanitize_refine_items(value)
        if data.get("topic"):
            return _sanitize_refine_items([data])
        return []

    return []


async def refine_node_content(node_title: str, content_chunk: str, context_path: str = "") -> list:
    """
    Refinement Phase: 针对特定节点生成子级详情
    强制 JSON 输出

    :return: List[Dict] e.g. [{"topic": "...", "details": [...]}]
    """
    system_prompt = """
    你是一个专业的文档分析助手。你的任务是根据给定的段落内容，
    生成该章节下的详细思维导图分支。
    
    【输出格式要求】：
    1. 必须是严格的 JSON 格式 (List of Objects)
    2. 不要包含 Markdown 代码块标记（如 ```json），直接输出 JSON 字符串
    3. 结构如下：
    [
      {"topic": "关键子论点1", "details": ["细节1", "细节2"]},
      {"topic": "关键子论点2", "details": []}
    ]
    
    【内容原则】：
    - 只提取与当前章节标题【强相关】的内容
    - 如果文本包含列表、步骤、或者加粗定义的术语，请务必将其转换为独立的 topic
    - 保留所有具体的参数、数值、日期
    - topic 要简洁、可读、可独立理解；避免单字、纯数字或乱码
    - details 仅保留事实性信息，避免重复、空泛措辞
    
    【噪声过滤】：
    输入文本来自 PDF 自动解析，可能包含页眉页脚、页码、水印、分隔线等残留噪声。
    请自动忽略这些内容，不要将其作为 topic 或 details 输出。

    【质量约束】：
    - 不输出 “Page 3”“3 / 20”“CONFIDENTIAL”“仅供参考” 等噪声词
    - 不输出 URL、文件路径、纯符号行
    - 输出前请自检，确保 JSON 数组中的每个对象都包含 topic 字段
    """

    user_prompt = f"""
    【上下文路径】：{context_path}
    【当前章节】：{node_title}
    
    【待分析内容】：
    {content_chunk}
    
    请提取关键信息作为子节点。忽略与本章节无关的内容。
    """

    try:
        client = get_client()
        model = get_model()
        is_minimax = _is_minimax_backend(model, client)

        request_kwargs = {
            "model": model,
            "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            "temperature": 0.3,
            "max_tokens": 2000,
        }
        if is_minimax:
            extra_body = dict(request_kwargs.get("extra_body") or {})
            extra_body["reasoning_split"] = True
            request_kwargs["extra_body"] = extra_body

        use_response_format = _should_use_response_format(model, client)
        response = await _create_refine_completion(client, request_kwargs, use_response_format)
        content = response.choices[0].message.content
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict):
                    text = part.get("text") or part.get("content")
                    if isinstance(text, str) and text:
                        parts.append(text)
                elif isinstance(part, str):
                    parts.append(part)
            content = "\n".join(parts).strip()
        elif not isinstance(content, str):
            content = str(content or "")
        return _parse_refine_response(content, node_title)

    except Exception as e:
        print(f"Refine node {node_title} failed: {e}")
        return []
