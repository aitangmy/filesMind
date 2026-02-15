"""
认知引擎 - DeepSeek AI 处理模块
优化版：适配付费 API + 正确的 temperature + 修复信号量泄漏
"""
import asyncio
import os
import atexit
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

# DeepSeek API 配置
client = AsyncOpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)

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

async def summarize_chunk(text_chunk: str, chunk_id: int, task=None):
    """
    处理单个文本块
    """
    semaphore = get_semaphore()
    async with semaphore:
        try:
            # 添加延迟，避免瞬间过高并发
            await asyncio.sleep(REQUEST_DELAY)
            
            response = await client.chat.completions.create(
                model="deepseek-chat", 
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"Analyze the following text and convert it into a Markdown Mind Map branch:\n\n{text_chunk}"}
                ],
                # 数据抽取/分析场景，使用 1.0
                temperature=1.0,
                max_tokens=2000
            )
            
            # 更新进度（如果有 task 对象）
            if task:
                task.message = f"AI 正在处理章节 {chunk_id + 1}..."
            
            return chunk_id, response.choices[0].message.content
            
        except Exception as e:
            print(f"Error processing chunk {chunk_id}: {e}")
            await asyncio.sleep(1)
            return chunk_id, None

async def generate_root_summary(full_markdown: str):
    """
    生成根节点摘要
    """
    try:
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
    tasks = [summarize_chunk(chunk, i, task) for i, chunk in enumerate(chunks)]
    
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
