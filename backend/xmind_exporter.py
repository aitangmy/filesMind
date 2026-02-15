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
    """
    lines = markdown.strip().split('\n')
    root = {"id": "root", "title": "思维导图", "children": []}
    
    current_node = root
    parent_nodes = [root]
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # 计算缩进级别
        indent = len(line) - len(line.lstrip())
        
        # 确定标题级别
        if line.startswith('# '):
            root['title'] = line[2:].strip()
            continue
        elif line.startswith('## '):
            level = 2
            content = line[3:].strip()
        elif line.startswith('- '):
            level = 3
            content = line[2:].strip()
        else:
            continue
        
        # 清理内容
        content = re.sub(r'^\d+\.\s*', '', content)
        content = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', content)
        content = re.sub(r'\*\*([^*]+)\*\*', r'\1', content)
        content = re.sub(r'\*([^*]+)\*', r'\1', content)
        
        if not content:
            continue
        
        # 创建新节点
        new_node = {
            "id": f"node_{len(parent_nodes)}_{len(parent_nodes[-1].get('children', []))}",
            "title": content,
            "children": []
        }
        
        # 根据缩进添加到正确的父节点
        # 简单逻辑：添加到最后一个节点
        if parent_nodes:
            parent_nodes[-1].setdefault('children', [])
            parent_nodes[-1]['children'].append(new_node)
        
        # 更新父节点链
        if level > 2:
            parent_nodes.append(new_node)
            # 限制深度
            if len(parent_nodes) > 5:
                parent_nodes.pop(1)  # 保持 root
    
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
    
    # 构建 XMind content.json - 简化版，兼容 XMind 8
    content = {
        "meta": {
            "generator": "FilesMind",
            "appName": "FilesMind",
            "appVersion": "1.0",
            "platform": "Mac",
            "creationTime": "2024-01-01T00:00:00.000Z",
            "creator": {
                "name": "FilesMind",
                "email": ""
            },
            "theme": "fresh-gray",
            "language": "zh_CN"
        },
        "rootTopic": {
            "id": tree.get("id", "root"),
            "title": tree.get("title", "中心主题"),
            "children": {
                "attached": []
            },
            "position": "root",
            "branch": "root",
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
        },
        "structure": "org.xmind.ui.map",
        "theme": "fresh-gray",
        "firstChildId": all_ids[0] if len(all_ids) > 0 else None,
        "childId": all_ids[1:] if len(all_ids) > 1 else [],
        "childDefaultWidth": 0,
        "childDefaultHeight": 0,
        "rootTopicLayout": {
            "layout": "org.xmind.ui.map",
            "childrenLayout": "org.xmind.ui.map",
            "alignment": "center",
            "orientation": "horizontal",
            "levelSpace": 40,
            "topicSpacing": 20,
            "lineColor": "#000000",
            "lineWidth": 2,
            "lineStyle": "solid"
        },
        "showTopicNumber": False,
        "showChildIndex": False,
        "showChildCount": False,
        "autoLayout": True,
        "fitMaxWidth": False,
        "fitMaxHeight": False,
        "title": filename
    }
    
    # 添加子主题
    for child in tree.get('children', []):
        topic_node = create_topic_node(child)
        content["rootTopic"]["children"]["attached"].append(topic_node)
    
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
        "appName": "XMind",
        "appVersion": "8.0",
        "platform": "Mac",
        "displayTimeZone": "Asia/Shanghai",
        "calendars": ["gregorian"],
        "productID": "8",
        "version": "8"
    }
    
    # 创建 ZIP 文件
    buffer = BytesIO()
    
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
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
