该方案将从根本上解决“层级丢失”问题，并显著提升思维导图的逻辑性和结构感。

### 核心理念 (Architecture)

将原本的“单次线性处理（切块 -> 总结 -> 拼接）”重构为 **“双流（Two-Pass）处理架构”**：

1. **Pass 1 - 宏观骨架 (The Skeleton)**：先“看森林”。提取全文档的目录树结构，构建一个不含细节的、层级正确的 JSON 树。
2. **Pass 2 - 微观填充 (The Refinement)**：后“看树木”。将文档按骨架节点切分，并行让 AI 填充每个节点的详细子项。

---

### 1. 数据结构设计 (Standardized Schema)

为了实现程序化合并，必须放弃纯 Markdown 文本拼接，改用 **JSON** 作为中间数据交换格式。

**标准节点对象 (Node Schema):**

```json
{
  "id": "uuid-or-path",      // 唯一标识，如 "1.2.3" 或 UUID
  "topic": "节点标题",        // 如 "1.1 核心算法"
  "level": 2,                // 标题层级 H1=1, H2=2...
  "content_chunk": "...",    // (中间态) 该节点对应的原文切片
  "children": []             // 子节点列表
}
```

### 2. 核心流程详解

#### 阶段一：骨架提取 (Skeleton Extraction)

**目标**：生成一颗只有 H1-H3 主干的空树，确保层级绝对正确。

- **输入**：`parser_service.py` 解析出的完整 Markdown。
- **策略**：
  - **方法 A (低成本/推荐)**：直接使用 Python 正则表达式扫描所有 `#` 开头的行，构建层级树。这比 LLM 更精准且零成本。
  - **方法 B (智能/容错强)**：如果 PDF OCR 质量差（标题没被识别为 Markdown Header），提取前 5000 tokens 或目录页，发送给 LLM：“请分析目录结构，输出 JSON 骨架”。
- **产出**：`skeleton_tree` (JSON 对象)。

#### 阶段二：上下文切分 (Context-Aware Chunking)

**目标**：将原文切片精确分配给骨架上的节点。

**逻辑**：

- 遍历 Markdown 原文。
- 当遇到 `# 标题` 时，查找 `skeleton_tree` 中对应的节点 ID。
- 将该标题下的所有正文文本，暂存到该节点的 `content_chunk` 字段中。
- *注意*：如果正文过长（超过 LLM 窗口），则对该节点进行内部二次切分（Sub-chunking），但在逻辑上它们都属于这个 ID。

#### 阶段三：并行填充 (Parallel Refinement)

**目标**：为骨架长出“血肉”。

- **并发处理**：遍历 `skeleton_tree` 中有 `content_chunk` 的节点。
- **LLM 请求**：
  - **System Prompt**: "你是一个思维导图专家。请将给定的文本转换为结构化的思维导图节点（JSON格式）。"
  - **User Prompt**: "上下文标题：【{node.topic}】\n 内容：\n {node.content_chunk} \n\n 请列出该内容的关键点（子节点），不要重复父标题。"
- **输出**：该节点专属的 `children` 列表 (JSON)。

#### 阶段四：组装 (Assembly)

**目标**：合并。

- 将阶段三 LLM 返回的 `children` 数据，直接挂载到 `skeleton_tree` 对应节点的 `children` 字段中。
- 最终遍历 JSON 树，导出为 XMind 或 Markdown。

---

### 3. 代码改造指南

你需要修改以下核心文件。

#### Step 1: `backend/app.py` (修改主流程)

```py
# 伪代码逻辑示意

async def generate_mindmap(file_path):
    # 1. 解析 PDF 为 Markdown (现有逻辑)
    md_content = await parse_pdf(file_path)
    
    # 2. 【新增】构建骨架树
    # 使用正则快速提取所有 Headers，生成嵌套字典
    skeleton_tree = build_hierarchy_tree(md_content) 
    
    # 3. 【新增】将正文内容挂载到骨架叶子节点上
    # 这一步将大段文本拆解到了对应的 Header 节点下
    skeleton_tree_with_content = assign_content_to_nodes(skeleton_tree, md_content)
    
    # 4. 【修改】并行生成细节 (Refinement)
    # 不再是简单的 summarize_chunk，而是针对特定节点的 refine_node
    tasks = []
    for node in traverse_nodes(skeleton_tree_with_content):
        if node.content:
            tasks.append(cognitive_engine.refine_node_content(node))
            
    # 等待所有节点填充完毕
    completed_nodes = await asyncio.gather(*tasks)
    
    # 5. 【新增】组装最终树
    final_tree = assemble_tree(skeleton_tree, completed_nodes)
    
    # 6. 导出
    return export_xmind(final_tree)
```

#### Step 2: `backend/cognitive_engine.py` (新增 Prompt 策略)

你需要新增一个专门用于“填充细节”的函数，并强制 JSON 输出。

```py
async def refine_node_content(node_title: str, content_chunk: str):
    """
    针对特定节点生成子级详情，强制 JSON 输出
    """
    system_prompt = """
    你是一个专业的文档分析助手。你的任务是根据给定的段落内容，
    生成该章节下的详细思维导图分支。
    
    输出必须是严格的 JSON 格式 (List of Objects)，结构如下：
    [
      {"topic": "子论点1", "details": ["细节1", "细节2"]},
      {"topic": "子论点2", "details": []}
    ]
    """
    
    user_prompt = f"""
    【当前章节】：{node_title}
    【待分析内容】：
    {content_chunk}
    
    请提取关键信息作为子节点。忽略与本章节无关的内容。
    """
    
    # 调用 LLM，建议开启 response_format={"type": "json_object"} (如果模型支持)
    # 或者在 Prompt 里强力约束
    response = await call_llm(system_prompt, user_prompt)
    return parse_json(response)
```

#### Step 3: 工具函数 (正则构建骨架)

在 `backend/parser_service.py` 或新文件中添加：

```py
import re

def build_hierarchy_tree(markdown_text):
    lines = markdown_text.split('\n')
    root = {"id": "root", "topic": "Root", "level": 0, "children": []}
    stack = [root] # 栈用于追踪父级
    
    for line in lines:
        match = re.match(r'^(#+)\s+(.*)', line)
        if match:
            level = len(match.group(1))
            topic = match.group(2).strip()
            node = {"topic": topic, "level": level, "children": [], "content_lines": []}
            
            # 找到正确的父级（栈顶元素的 level 必须小于当前 node 的 level）
            while len(stack) > 1 and stack[-1]['level'] >= level:
                stack.pop()
            
            parent = stack[-1]
            parent['children'].append(node)
            stack.append(node)
        else:
            # 这是正文内容，归属到最近的标题下
            if len(stack) > 1: # 排除 root
                stack[-1].setdefault('content_lines', []).append(line)
                
    return root
```

### 4. 方案优缺点评估

#### 优点 (Pros)

1. **层级绝对稳固**：骨架是由正则生成的，H1 就是 H1，H2 就是 H2，AI 无法篡改父级结构。
2. **上下文隔离**：每个 AI 任务只关注一个具体的章节（比如只关注 "3.1 节"），幻觉率大幅降低。
3. **可展示性好**：JSON 结构天然适合前端渲染（Vue组件）和 XMind 导出。

#### 缺点 (Cons)

1. **依赖 Markdown 规范性**：如果 PDF 转出来的 Markdown 标题没有 `#` 标记（全是纯文本），正则会失效。
   - *对策*：在 parser 阶段增加“OCR 标题修正”步骤，或者如果正则提取失败，回退到纯 AI 骨架提取。
2. **碎片化风险**：如果一个章节的内容非常非常长（超过 LLM 窗口），依然需要切分，可能导致该节点下的子节点逻辑不连贯。
   - *对策*：对于超长节点，使用 map-reduce 摘要后再生成子节点。

### 5. 推荐行动路径

1. **验证解析器**：先检查 `parser_service.py` 产出的 `md_content`，确认 `docling` 是否正确保留了 markdown headers (`#`, `##`)。如果是，该方案 100% 可行。
2. **实现树构建器**：写好上面的 `build_hierarchy_tree` 函数，打印一下 JSON 树，看看骨架是否清晰。
3. **接入 LLM 填充**：替换原有的 `summarize_chunk` 逻辑。

这个方案将把你的项目从“文本摘要工具”升级为真正的“结构化知识提取引擎”。