import json
import os
import logging

logger = logging.getLogger(__name__)

def generate_anchor_index(
    root_node,
    source_lines: list[str],
    pdf_index_path: str,
    anchor_index_path: str,
    parser_backend: str = "docling"
):
    """
    生成 node_id -> PDF物理位置 的映射索引 (Sidecar Index)
    这里由于我们已经在 structure_utils.py 阶段确定了准确血缘，所以只用递归输出即可。
    这里保留 source_lines 和 pdf_index_path 的入参只是为了兼容现有签名的调用。
    """
    mappings = {}
    
    def process_node(node):
        node_id = getattr(node, "id", None)
        pdf_page_no = getattr(node, "pdf_page_no", None)
        pdf_y_ratio = getattr(node, "pdf_y_ratio", None)
        
        if node_id and pdf_page_no is not None:
            mappings[node_id] = {
                "pdf_page_no": max(1, int(pdf_page_no)),
                "pdf_y_ratio": float(pdf_y_ratio) if pdf_y_ratio is not None else None
            }
            
        if hasattr(node, "children"):
            for child in getattr(node, "children", []):
                process_node(child)
                
    process_node(root_node)
    
    has_precise_anchor = len(mappings) > 0
    
    sidecar_data = {
        "version": "1.0",
        "parser_backend": parser_backend,
        "has_precise_anchor": has_precise_anchor,
        "mappings": mappings
    }
    
    temp_path = f"{anchor_index_path}.tmp"
    try:
        os.makedirs(os.path.dirname(os.path.abspath(anchor_index_path)), exist_ok=True)
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(sidecar_data, f, ensure_ascii=False, indent=2)
        os.replace(temp_path, anchor_index_path)
        logger.info(f"生成 Anchor 索引成功：{len(mappings)} 节点确定，输出路径：{anchor_index_path}")
    except Exception as e:
        logger.error(f"生成 Anchor 索引失败：{e}")
        if os.path.exists(temp_path):
            os.remove(temp_path)
