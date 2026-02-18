"""
XMind 格式导出工具 - 兼容 XMind 8 和 XMind Zen
将 Markdown 思维导图转换为 XMind 兼容格式
"""
import json
import re
import zipfile
import os
import hashlib
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
    
    # ====== 修复: 清理孤立括号 ======
    # 移除只有括号和空白字符的行
    text = re.sub(r'^\s*[\(\)\）】\]]+\s*$', '', text)
    # 移除行首的孤立括号
    text = re.sub(r'^[\(\)\）】\]]+(?=\S)', '', text)
    # 移除行尾的孤立括号
    text = re.sub(r'(?<=\s)[\(\)\）】\]]+$', '', text)
    # 移除不完整的括号配对
    text = re.sub(r'\([^)]*$', '', text)
    text = re.sub(r'^[^)]*\)', '', text)
    
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
       - 列表项：基于最近标题的 level + 1 + indent，确保相对于父标题定位
    3. 关键修复：列表项 level 基于 last_header_level 而非 stack top，防止层级漂移
    """
    lines = markdown.strip().split('\n')
    root = {"id": "root", "title": "思维导图", "children": []}

    # stack 存储元组 (level, node, is_header)
    stack = [(0, root, False)]
    
    # 跟踪最近一个标题的级别，用于列表项定位
    last_header_level = 1  # 默认 H1 (root)

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
                    last_header_level = 1
                    continue

                # H2-H6: level = header 数量
                level = len(h_mark)
                is_header = True
                last_header_level = level  # 更新最近标题级别

        elif stripped.startswith(('-', '*', '+')):
            # 列表项处理
            next_char = stripped[1:2]
            if next_char == ' ' or next_char == '':
                # 提取列表内容
                node_text = stripped.lstrip('-*+').lstrip()
                # 关键修复：基于 last_header_level 而非 stack top 定位
                # 无缩进列表项 = last_header_level + 1（作为当前标题的子节点）
                # 每缩进 2 空格再增加 1 级
                indent_level = raw_indent // 2
                level = last_header_level + 1 + indent_level
            else:
                node_text = stripped
                indent_level = raw_indent // 2
                level = last_header_level + 1 + indent_level
        else:
            # 普通文本行，按缩进处理
            node_text = stripped
            indent_level = raw_indent // 2
            level = last_header_level + 1 + indent_level

        # 如果节点文本为空，跳过
        if not node_text:
            continue

        # 提取图片路径
        image_match = re.search(r'!\[(.*?)\]\((.*?)\)', node_text)
        image_path = None
        if image_match:
            # 获取图片路径
            image_alt = image_match.group(1)  # Capture Alt Text
            image_path = image_match.group(2)
            
            # 从标题中移除图片引用字符串
            node_text = node_text.replace(image_match.group(0), " ")

        # 清理文本
        node_text = clean_node_text(node_text)
        
        # ====== 修复: 跳过无效节点 ======
        # 如果清理后文本为空或只有空白，跳过此节点
        if not node_text or node_text.strip() == "":
            # 但如果之前有提取到图片路径，仍需创建节点
            if not image_path:
                continue
        
        # 移除纯数字和点的标题（如 "1.2.3." 这种没有实际内容的）
        if re.match(r'^[\d\.\s]+$', node_text):
            if not image_path:
                continue
        
        # 如果文本被情况（例如只有图片），使用 Alt Text 或默认值
        if (not node_text or node_text.strip() == "") and image_path:
            node_text = image_alt if image_alt else "Image"
            
        # ==================== 栈操作：找到父节点 ====================
        # 统一处理：弹出所有 >= 当前 level 的节点，栈顶即为父节点
        while len(stack) > 1 and stack[-1][0] >= level:
            stack.pop()

        parent = stack[-1][1]

        # 创建新节点
        new_node = {
            "id": f"node_{abs(hash(node_text + str(len(parent.get('children', [])))))}_{id(stack)}",
            "title": node_text,
            "children": [],
            "level": level  # 保存原始层级信息，便于调试
        }
        
        if image_path:
            # 去除可能存在的 URL query/hash
            if '?' in image_path:
                image_path = image_path.split('?')[0]
            new_node['image_path'] = image_path

        parent.setdefault('children', []).append(new_node)

        # 所有节点都入栈，供后续节点挂载
        stack.append((level, new_node, is_header))

    return root


def generate_xmind_content(markdown: str, filename: str = "mindmap", images_dir: str = None) -> bytes:
    """
    生成 XMind 格式的 ZIP 文件内容
    :param images_dir: 图片存储目录 (e.g. data/images/{file_id})
    """
    tree = parse_markdown_to_tree(markdown)
    
    # 准备资源列表
    resources = {}  # { local_filename: (md5_hash, file_bytes, media_type) }
    
    if images_dir and os.path.exists(images_dir):
        # 预先加载所有可能的图片，或者按需加载
        pass

    # 递归处理节点，收集图片引用并重写为 xap:resources/
    def process_node_images(node):
        if 'image_path' in node and images_dir:
            # 读取图片
            img_name = os.path.basename(node['image_path'])  # pic_0.png
            local_path = os.path.join(images_dir, img_name)
            
            if os.path.exists(local_path):
                # 读取并计算 Hash
                with open(local_path, 'rb') as f:
                    img_data = f.read()
                
                md5 = hashlib.md5(img_data).hexdigest()
                ext = os.path.splitext(img_name)[1].lower()
                resource_name = f"{md5}{ext}"
                
                # 记录资源
                resources[resource_name] = img_data
                
                # 添加 image 字段到节点
                node['image'] = {
                    "src": f"xap:resources/{resource_name}",
                }

        for child in node.get('children', []):
            process_node_images(child)

    process_node_images(tree)

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
    
    # Add root image if exists
    if 'image' in tree:
        root_topic['image'] = tree['image']

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

    # 生成 manifest.json - 严格按照 XMind 格式要求
    manifest = {
        "file-entries": {
            "content.json": {
                "path": "content.json",
                "media-type": "application/json",
                "isModified": True
            },
            "metadata.json": {
                "path": "metadata.json",
                "media-type": "application/json",
                "isModified": False
            },
            "manifest.json": {
                "path": "manifest.json",
                "media-type": "application/json",
                "isModified": False
            },
            "design.json": {
                "path": "design.json",
                "media-type": "application/json",
                "isModified": True
            }
        }
    }
    
    # 添加资源目录声明（XMind 需要）
    if resources:
        manifest["file-entries"]["resources/"] = {
            "path": "resources/",
            "media-type": "application/x-xmind-directory"
        }
    
    # 添加图片资源到 manifest - 每个资源都需要完整的条目
    for res_name, res_data in resources.items():
        # 简单推断 mimetype
        ext = os.path.splitext(res_name)[1].lower()
        mime = "image/png" if ext == ".png" else "image/jpeg" if ext in [".jpg", ".jpeg"] else "application/octet-stream"
        manifest["file-entries"][f"resources/{res_name}"] = {
            "path": f"resources/{res_name}",
            "media-type": mime,
            "isModified": True
        }

    # 生成 metadata.json
    metadata = {
        "creator": {
            "name": "FilesMind",
            "version": "1.0"
        }
    }
    
    # 生成 design.json
    design = {
        "id": "design_1",
        "theme": {
            "id": "theme_classic",
            "name": "Classic",
            "type": "classic"
        },
        "model": {
            "fill": "#FFFFFF",
            "border": {"color": "#000000", "width": 1, "style": "solid"},
            "color": "#000000",
            "font": {"family": "微软雅黑", "size": 14, "style": "normal", "weight": "normal"},
            "textAlignment": "left",
            "verticalAlignment": "middle"
        },
        "relationships": {"default": {"color": "#000000", "width": 1, "style": "solid"}},
        "summary": {"fill": "#FFF8DC", "border": {"color": "#DAA520", "width": 1, "style": "solid"}}
    }


    # 创建 ZIP 文件
    buffer = BytesIO()

    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('content.json', json.dumps(content, ensure_ascii=False, indent=2))
        zf.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
        zf.writestr('metadata.json', json.dumps(metadata, ensure_ascii=False, indent=2))
        zf.writestr('design.json', json.dumps(design, ensure_ascii=False, indent=2))
        
        # 写入图片资源
        for res_name, res_data in resources.items():
            zf.writestr(f"resources/{res_name}", res_data)

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
    
    # Add image if exists
    if 'image' in node:
        topic['image'] = node['image']

    # 递归添加子节点
    for child in node.get('children', []):
        child_topic = create_topic_node(child)
        topic["children"]["attached"].append(child_topic)

    return topic
