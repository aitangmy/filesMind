"""
XMind 格式导出工具 - 兼容 XMind 8 和 XMind Zen
将 Markdown 思维导图转换为 XMind 兼容格式
"""
import json
import re
import zipfile
from io import BytesIO
from typing import Dict, Any, List


def clean_node_text(text: str) -> str:
    """清理节点文本，移除 Markdown 格式"""
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)  # 去除链接
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)          # 去除加粗
    text = re.sub(r'\*([^*]+)\*', r'\1', text)              # 去除斜体
    text = re.sub(r'`([^`]+)`', r'\1', text)                # 去除代码块
    text = re.sub(r'__([^_]+)__', r'\1', text)              # 去除下划线加粗
    text = re.sub(r'_([^_]+)_', r'\1', text)                # 去除下划线斜体
    return text.strip()


def parse_markdown_to_tree(markdown: str) -> Dict[str, Any]:
    """
    将 Markdown 转换为树结构
    修复：正确处理多层级结构，避免"根节点 + 无数二级节点"的扁平化问题

    核心逻辑：
    1. 使用栈来维护层级关系
    2. 统一层级计算规则：
       - H1 (#): level 1 (根节点)
       - H2 (##): level 2 (主分支)
       - H3 (###): level 3 (子分支)
       - H4 (####): level 4 (细节)
       - 列表项：基于缩进，无缩进列表项 level=2，每缩进 2 空格增加 1 级
    3. 关键修复：所有节点统一使用栈管理，标题和列表项都能正确嵌套
    """
    lines = markdown.strip().split('\n')
    root = {"id": "root", "title": "思维导图", "children": []}

    # stack 存储元组 (level, node, is_header)
    stack = [(0, root, False)]

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # 计算原始缩进
        raw_indent = len(line) - len(line.lstrip())

        node_text = ""
        level = 0
        is_header = False

        # ==================== 识别类型 ====================
        if stripped.startswith('#'):
            # Header 处理
            match = re.match(r'^(#{1,6})\s*(.*)', stripped)
            if match:
                h_mark = match.group(1)
                node_text = match.group(2).strip() if match.group(2) else "Untitled"

                if not node_text:
                    node_text = "Untitled"

                # H1 作为根节点标题
                if h_mark == '#':
                    root['title'] = node_text
                    stack = [(0, root, False)]
                    continue

                # H2-H6: level = header 数量
                level = len(h_mark)
                is_header = True

                # 清理文本
                node_text = clean_node_text(node_text)

        elif stripped.startswith(('-', '*', '+')):
            # 列表项处理
            next_char = stripped[1:2]
            if next_char == ' ' or next_char == '':
                # 提取列表内容
                node_text = stripped.lstrip('-*+').lstrip()
                # 列表的 level = 基础级别 + 缩进级别
                # 无缩进的列表项 level=2（与 H2 同级或作为当前标题的子节点）
                # 每缩进 2 空格增加 1 级
                indent_level = raw_indent // 2
                level = 2 + indent_level
            else:
                node_text = stripped
                level = 2 + (raw_indent // 2)
        else:
            # 普通文本行，按缩进处理
            node_text = stripped
            level = 2 + (raw_indent // 2)

        # 如果节点文本为空，跳过
        if not node_text:
            continue

        # 清理文本
        node_text = clean_node_text(node_text)

        # ==================== 栈操作：找到父节点 ====================
        # 统一处理：弹出所有 >= 当前 level 的节点，栈顶即为父节点
        while len(stack) > 1 and stack[-1][0] >= level:
            stack.pop()

        parent = stack[-1][1]

        # 创建新节点
        new_node = {
            "id": f"node_{abs(hash(node_text + str(len(parent.get('children', [])))))}_{id(stack)}",
            "title": node_text,
            "children": []
        }

        parent.setdefault('children', []).append(new_node)

        # 所有节点都入栈，供后续节点挂载
        stack.append((level, new_node, is_header))

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

    # 1. 构造 Sheet 对象
    sheet_content = {
        "id": "sheet_1",
        "class": "sheet",
        "title": filename,
        "rootTopic": root_topic,
        "topicPositioning": "fixed",
        "designId": "design_1"  # 引用 design.json
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

    # 生成 design.json - XMind 样式设计文件
    # 参考 XMind 格式规范，提供默认主题和颜色配置
    design = {
        "id": "design_1",
        "theme": {
            "id": "theme_classic",
            "name": "Classic",
            "type": "classic"
        },
        "model": {
            "fill": "#FFFFFF",
            "border": {
                "color": "#000000",
                "width": 1,
                "style": "solid"
            },
            "color": "#000000",
            "font": {
                "family": "微软雅黑",
                "size": 14,
                "style": "normal",
                "weight": "normal"
            },
            "textAlignment": "left",
            "verticalAlignment": "middle"
        },
        "relationships": {
            "default": {
                "color": "#000000",
                "width": 1,
                "style": "solid"
            }
        },
        "summary": {
            "fill": "#FFF8DC",
            "border": {
                "color": "#DAA520",
                "width": 1,
                "style": "solid"
            }
        }
    }

    # 更新 manifest，添加 design.json 条目
    manifest["file-entries"]["design.json"] = {
        "path": "design.json",
        "media-type": "application/json",
        "isModified": True
    }

    # 创建 ZIP 文件
    buffer = BytesIO()

    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('content.json', json.dumps(content, ensure_ascii=False, indent=2))
        zf.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
        zf.writestr('metadata.json', json.dumps(metadata, ensure_ascii=False, indent=2))
        zf.writestr('design.json', json.dumps(design, ensure_ascii=False, indent=2))

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
