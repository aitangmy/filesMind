import re
import json

class TreeNode:
    def __init__(self, topic, level, parent=None):
        self.id = str(id(self))
        self.topic = topic
        self.level = level
        self.content_lines = []  # 存储正文行
        self.children = []
        self.ai_details = []     # 存储 AI 返回的 [{"topic":..., "details":...}]
        self.parent = parent

    @property
    def full_content(self):
        """获取合并后的正文内容"""
        return "\n".join(self.content_lines).strip()

    def add_child(self, node):
        self.children.append(node)
        node.parent = self

    def get_breadcrumbs(self):
        """生成面包屑路径：Root > Chapter 1 > Section 1.1"""
        chain = []
        curr = self
        while curr:
            if curr.level > 0: # 忽略 Root 显示
                chain.append(curr.topic)
            curr = curr.parent
        return " > ".join(reversed(chain))

    def to_dict(self):
        """调试用"""
        return {
            "topic": self.topic,
            "level": self.level,
            "content_length": len(self.full_content),
            "children": [child.to_dict() for child in self.children]
        }

def build_hierarchy_tree(markdown_text):
    """
    解析 Markdown 为 TreeNode 树。
    处理逻辑：
    1. 遇到 Header -> 创建新节点，根据 level 调整栈
    2. 遇到非 Header -> 归属到当前栈顶节点（即最近的父级）
    """
    lines = markdown_text.split('\n')
    
    # 初始化 Root 节点 (Level 0)
    root = TreeNode("Root", 0)
    
    # 栈用于追踪当前的父级链 [Root, H1, H2...]
    # 栈顶永远是当前内容的归属节点
    stack = [root] 

    for line in lines:
        # 匹配标准 Markdown 标题 (# 标题)
        header_match = re.match(r'^(#+)\s+(.*)', line)
        
        if header_match:
            level = len(header_match.group(1))
            topic = header_match.group(2).strip()
            
            new_node = TreeNode(topic, level)
            
            # 【核心逻辑】回溯栈：找到新节点的直接父级
            # 如果栈顶节点的层级 >= 新节点层级，说明栈顶节点结束了，弹出
            while len(stack) > 1 and stack[-1].level >= level:
                stack.pop()
            
            parent_node = stack[-1]
            parent_node.add_child(new_node)
            
            # 将新节点压入栈，成为后续内容的潜在父级
            stack.append(new_node)
        else:
            # 非标题行，作为内容追加到当前栈顶节点
            # 这自动处理了“孤儿内容”：如果还没遇到任何标题，内容会加到 Root
            line = line.strip()
            if line:
                 stack[-1].content_lines.append(line)
            
    return root

def tree_to_markdown(node, depth=0):
    """
    将树递归导出为 Markdown
    """
    lines = []
    
    # 1. 渲染标题 (Root 除外)
    if node.level > 0:
        indent_hash = "#" * node.level
        lines.append(f"{indent_hash} {node.topic}")
    
    # 2. 渲染 AI 生成的细节 (如果有)
    # 假设 ai_details 是 list of dict: {"topic": "子项", "details": ["细项1"]}
    if node.ai_details:
        for item in node.ai_details:
            # 这里的格式取决于你希望最终 Markdown 长什么样
            # 方案 A: 简单的无序列表
            lines.append(f"- **{item.get('topic', '')}**")
            for det in item.get('details', []):
                lines.append(f"  - {det}")
    
    # 3. (可选) 渲染原始内容，或者只保留 AI 总结？
    # 通常生成思维导图时，我们只保留 AI 总结的结构化信息，而不保留大段原文
    
    # lines.append("") # 空行分隔
    
    # 4. 递归渲染子节点
    if node.children:
        lines.append("") # 子节点前加空行
        for child in node.children:
            result = tree_to_markdown(child, depth + 1)
            if result:
                 lines.append(result)
        
    return "\n".join(lines).strip()
