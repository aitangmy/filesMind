"""
XMind 格式导出工具 - 兼容 XMind 8 和 XMind Zen
将 Markdown 思维导图转换为 XMind 兼容格式
"""
import json
import re
import zipfile
from io import BytesIO
from typing import Dict, Any, List

def parse_markdown_to_tree(markdown: str) -> Dict[str, Any]:
    """
    将 Markdown 转换为树结构
    核心逻辑：使用栈来维护层级关系
    """
    lines = markdown.strip().split('\n')
    root = {"id": "root", "title": "思维导图", "children": []}
    
    # stack 存储元组 (level, node)
    # level 定义：
    # - Root: 0
    # - H1 (#): 1
    # - H2 (##): 2
    # - ...
    # - List Item: (父Header Level 或 0) + 1 + 缩进层级
    stack = [(0, root)]
    current_header_level = 0
    
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # 计算缩进 (假设 2 空格或 1 tab 为一级缩进)
        raw_indent = len(line) - len(line.lstrip())
        indent = raw_indent // 2  # 2 space = 1 level
        
        node_text = ""
        level = 0
        
        # 识别类型
        if stripped.startswith('#'):
            parts = stripped.split(' ', 1)
            h_mark = parts[0]
            if all(c == '#' for c in h_mark):
                # Header
                level = len(h_mark)
                node_text = parts[1].strip() if len(parts) > 1 else "Untitled"
                
                if level == 1:
                    root['title'] = node_text
                    current_header_level = 1
                    # 清空栈直到 Root，因为 H1 通常是文档标题
                    stack = [(0, root)]
                    continue
                
                current_header_level = level
                
            else:
                # 非 Header，当作普通文本 -> 列表项
                node_text = stripped
                level = current_header_level + 1 + indent
        
        elif stripped.startswith(('-', '*', '+')) and stripped[1:2] == ' ':
            # 列表项
            node_text = stripped[2:].strip()
            level = current_header_level + 1 + indent
            
        else:
            # 普通文本
            node_text = stripped
            level = current_header_level + 1 + indent # 视为当前 Header 的子项
            
        # 清理文本
        node_text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', node_text) # 去除链接
        node_text = re.sub(r'\*\*([^*]+)\*\*', r'\1', node_text)       # 去除加粗
        node_text = re.sub(r'\*([^*]+)\*', r'\1', node_text)           # 去除斜体
        node_text = re.sub(r'`([^`]+)`', r'\1', node_text)             # 去除代码块
            
        # 栈操作：找到父节点
        # 弹出所有 Level >= 当前 Level 的节点，剩下的栈顶即为父节点
        while len(stack) > 1 and stack[-1][0] >= level:
            stack.pop()
            
        parent = stack[-1][1]
        
        new_node = {
            "id": f"node_{abs(hash(node_text))}_{len(parent.get('children', []))}", 
            "title": node_text,
            "children": []
        }
        
        parent.setdefault('children', []).append(new_node)
        stack.append((level, new_node))
        
    return root

def generate_xmind_content(markdown: str, filename: str = "mindmap") -> bytes:
    """
    生成 XMind 格式的 ZIP 文件内容
    """
    tree = parse_markdown_to_tree(markdown)
    
    # 生成所有节点 ID
    all_ids = []
    
    def collect_ids(node, ids_list):
        if 'id' in node:
            ids_list.append(node['id'])
        for child in node.get('children', []):
            collect_ids(child, ids_list)
    
    collect_ids(tree, all_ids)
    
    # 构造 Root Topic
    root_topic = {
        "id": tree.get("id", "root"),
        "title": tree.get("title", "中心主题"),
        "children": {
            "attached": []
        },
        "structure": "org.xmind.ui.map.unbalanced",  # 默认结构
        "style": {
            "properties": {
                "fill": "#FFFFFF",
                "border-color": "#000000",
                "border-width": 1,
                "border-style": "solid",
                "color": "#000000",
                "font-family": "微软雅黑",
                "font-size": 18,
                "font-weight": "bold",
                "text-align": "left",
                "text-v-align": "middle"
            }
        }
    }

    # 添加子主题
    for child in tree.get('children', []):
        topic_node = create_topic_node(child)
        root_topic["children"]["attached"].append(topic_node)

    # 1. 构造 Sheet 对象 (原本你是一个大字典，现在把它变成 sheet)
    sheet_content = {
        "id": "sheet_1",  # 必须有 ID
        "class": "sheet", # 必须声明类型
        "title": filename,
        "rootTopic": root_topic,
        "topicPositioning": "fixed", # 推荐加上
    }

    # 2. 构造 content.json (必须是列表)
    content = [sheet_content] 
    
    # 生成 manifest.json
    manifest = {
        "file-entries": {
            "content.json": {
                "path": "content.json",
                "media-type": "application/json",
                "isModified": True
            },
            "metadata.json": {
                "path": "metadata.json",
                "media-type": "application/json"
            },
            "manifest.json": {
                "path": "manifest.json",
                "media-type": "application/json"
            }
        }
    }
    
    # 生成 metadata.json
    metadata = {
        "creator": {
            "name": "FilesMind",
            "version": "1.0"
        }
    }
    
    # 创建 ZIP 文件
    buffer = BytesIO()
    
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        # 关键：XMind 要求 content.json 是一个 Sheet 数组
        zf.writestr('content.json', json.dumps(content, ensure_ascii=False, indent=2))
        zf.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
        zf.writestr('metadata.json', json.dumps(metadata, ensure_ascii=False, indent=2))
    
    return buffer.getvalue()

def create_topic_node(node: Dict) -> Dict:
    """
    递归创建主题节点
    """
    topic = {
        "id": node.get("id", "node"),
        "title": node.get("title", "主题"),
        "children": {
            "attached": []
        },
        "style": {
            "properties": {
                "fill": "#FFFFFF",
                "border-color": "#000000",
                "border-width": 1,
                "border-style": "solid",
                "color": "#000000",
                "font-family": "微软雅黑",
                "font-size": 14,
                "font-style": "normal",
                "font-weight": "normal",
                "text-align": "left",
                "text-v-align": "middle"
            }
        }
    }
    
    # 递归添加子节点
    for child in node.get('children', []):
        child_topic = create_topic_node(child)
        topic["children"]["attached"].append(child_topic)
    
    return topic
