import sys
import gc
import re
import logging
import os
# 解决 Windows 下 OpenMP 多重加载冲突 (OMP: Error #15)
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

import ssl
import urllib.request
from pathlib import Path

# 配置 HuggingFace 镜像（解决国内网络访问问题）
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ["HF_HOME"] = os.path.expanduser("~/.cache/huggingface")
os.environ["TRANSFORMERS_CACHE"] = os.path.expanduser("~/.cache/huggingface/transformers")
os.environ["HF_HUB_OFFLINE"] = "0"
os.environ["HF_HUB_DISABLE_SYMLINKS"] = "1"


# 配置 SSL 证书（解决部分环境 SSL 问题）
import certifi
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()
os.environ["CURL_CA_BUNDLE"] = certifi.where()

# 尝试禁用 SSL 验证（仅作为备选）
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context


# ====== Markdown层级修复函数 ======
def fix_markdown_hierarchy(markdown_content):
    """
    根据章节编号修复Markdown标题层级
    Docling默认将所有标题识别为H2，此函数根据数字编号推断正确的层级
    
    规则:
    - 1.x → H2
    - 1.1.x → H3
    - 1.1.1.x → H4
    - 1.1.1.1.x → H5
    - 1.1.1.1.1.x → H6
    
    返回: 修复后的Markdown内容
    """
    lines = markdown_content.split('\n')
    fixed_lines = []
    
    # 章节编号匹配模式 - 支持有/无空格的情况
    chapter_pattern = re.compile(r'^(\d+(?:\.\d+)*)\.?\s*(.*)')
    
    for line in lines:
        stripped = line.strip()
        
        # 检查是否是标题行 (# 开头)
        header_match = re.match(r'^(#{1,6})\s+(.*)', stripped)
        if header_match:
            title = header_match.group(2)
            
            # 尝试匹配章节编号
            chapter_match = chapter_pattern.match(title)
            if chapter_match:
                num = chapter_match.group(1)
                
                # 根据编号确定层级
                num_parts = [p for p in num.split('.') if p]
                level = len(num_parts) + 1
                
                # 限制在H2-H6范围内
                level = min(max(level, 2), 6)
                
                # 生成新的标题
                new_header = '#' * level + ' ' + title
                fixed_lines.append(new_header)
            else:
                fixed_lines.append(stripped)
        else:
            fixed_lines.append(stripped)
    
    return '\n'.join(fixed_lines)
# ====== 层级修复函数结束 ======


from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.pipeline_options import PdfPipelineOptions, AcceleratorOptions, AcceleratorDevice
from docling.datamodel.base_models import InputFormat
import torch

# 设置日志，方便运维监控
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("MacMiniParser")

# ── docling-hierarchical-pdf 集成 ──────────────────────────────────────────
# 该库通过分析字体大小、加粗、PDF 书签来推断正确的标题层级，
# 解决 Docling 将所有标题识别为同一级别（全 ##）的问题。
# 安装：pip install docling-hierarchical-pdf
try:
    from hierarchical.postprocessor import ResultPostprocessor
    _HIERARCHICAL_AVAILABLE = True
    logger.info("docling-hierarchical-pdf 已加载，将自动修正标题层级")
except ImportError:
    _HIERARCHICAL_AVAILABLE = False
    logger.warning("docling-hierarchical-pdf 未安装，跳过层级后处理（pip install docling-hierarchical-pdf）")
# ──────────────────────────────────────────────────────────────────────────


def reclassify_furniture_by_position(result) -> int:
    """
    Method A: Universal header/footer detection using page coordinates.

    Docling's layout model sometimes misclassifies page headers and footers as
    BODY content.  This function corrects that by examining the bounding-box
    y-position of every text item relative to its page height:

      - Items whose centre y falls in the top    _HEADER_ZONE_RATIO of the page
        → reclassified as ContentLayer.FURNITURE (page header)
      - Items whose centre y falls in the bottom _FOOTER_ZONE_RATIO of the page
        → reclassified as ContentLayer.FURNITURE (page footer)

    Since export_to_markdown() defaults to ContentLayer.BODY only, reclassified
    items are automatically excluded from the Markdown output — no regex or
    keyword lists required.  Works for any document regardless of language or
    content.

    Returns the number of items reclassified.
    """
    try:
        from docling_core.types.doc.document import ContentLayer, DocItemLabel
    except ImportError:
        logger.warning("docling_core not available, skipping furniture reclassification")
        return 0

    # Fraction of page height treated as header / footer zone
    _HEADER_ZONE_RATIO = 0.08   # top 8 %
    _FOOTER_ZONE_RATIO = 0.08   # bottom 8 %

    # Labels that can legitimately be page headers/footers
    _CANDIDATE_LABELS = {
        DocItemLabel.PAGE_HEADER,
        DocItemLabel.PAGE_FOOTER,
        DocItemLabel.TEXT,
        DocItemLabel.PARAGRAPH,
        DocItemLabel.SECTION_HEADER,
    }

    doc = result.document
    reclassified = 0

    try:
        # Iterate over all items in the document body
        for item, _ in doc.iterate_items():
            # Skip items that are not in candidate labels
            if hasattr(item, 'label') and item.label not in _CANDIDATE_LABELS:
                continue

            # Get the provision (metadata)
            prov = item.prov[0] if item.prov else None
            if not prov:
                continue

            # Get page dimensions
            page = prov.page
            if not page:
                continue
            
            page_h = page.height
            if page_h <= 0:
                continue

            # Get bounding box(Docling uses bottom-left origin by default)
            bbox = prov.bbox
            if bbox is None:
                continue

            # Convert to top-left origin for intuitive top/bottom comparison
            # In bottom-left origin: y=0 is bottom, y=page_h is top
            # top-left origin: y=0 is top, y=page_h is bottom
            # centre_y_from_top = page_h - (bbox.t + bbox.b) / 2
            centre_y_from_top = page_h - (bbox.t + bbox.b) / 2.0

            is_header = centre_y_from_top < page_h * _HEADER_ZONE_RATIO
            is_footer = centre_y_from_top > page_h * (1.0 - _FOOTER_ZONE_RATIO)

            if is_header or is_footer:
                item.content_layer = ContentLayer.FURNITURE
                reclassified += 1

    except Exception as e:
        logger.warning(f"bbox-based furniture reclassification encountered an error: {e}")

    if reclassified:
        logger.info(
            f"[Method A] Reclassified {reclassified} items as FURNITURE "
            f"(top/bottom {_HEADER_ZONE_RATIO*100:.0f}% of page)"
        )
    return reclassified


def apply_hierarchy_postprocessor(result, file_path: str) -> None:
    """
    在 Docling 转换结果上运行层级后处理器，修正标题层级。

    后处理优先级（由库内部决定）：
      1. PDF 书签 / TOC（最准确）
      2. 字体大小聚类（scikit-learn K-Means）
      3. 加粗 + 字体大小组合
      4. 数字编号模式（兜底）

    注意：此函数直接修改 result.document（原地操作），无返回值。
    失败时静默回退，不影响主流程。
    """
    if not _HIERARCHICAL_AVAILABLE:
        return

    try:
        postprocessor = ResultPostprocessor(result=result, source=file_path)
        postprocessor.process()
        logger.info("层级后处理完成：标题层级已根据字体/书签修正")
    except Exception as e:
        # 后处理失败不应中断主流程，静默降级
        logger.warning(f"层级后处理失败（将使用原始 Docling 输出）: {e}")

from hardware_utils import get_hardware_info

def get_optimal_device():
    """
    自动检测最佳设备
    使用统一的硬件检测逻辑映射到 Docling 设备类型
    """
    info = get_hardware_info()
    device_type = info["device_type"]
    
    if device_type == "mps":
        logger.info("检测到 Apple Silicon MPS 加速可用 (from hardware_utils)")
        return AcceleratorDevice.MPS
    elif device_type == "gpu":
        logger.info("检测到 NVIDIA GPU 加速可用 (from hardware_utils)")
        return AcceleratorDevice.CUDA
    else:
        logger.warning("未检测到加速器，将使用 CPU (from hardware_utils)")
        return AcceleratorDevice.CPU

def get_optimized_converter(do_ocr: bool = True):
    """
    智能设备配置：
    - Mac (MPS): 禁用公式识别以兼容 MPS，优化内存
    - Windows/Linux (CUDA): 启用全功能加速
    - CPU: 降级运行
    :param do_ocr: 是否开启 OCR (默认开启，处理纯文本 PDF 可关闭以提升速度)
    """
    # 自动检测最佳设备
    device = get_optimal_device()
    
    # 动态设置线程数 (保留 2 个核心给系统/其他任务)
    cpu_count = os.cpu_count() or 4
    num_threads = max(4, cpu_count - 2)

    # 配置加速选项
    accel_options = AcceleratorOptions(
        num_threads=num_threads,
        device=device
    )

    pipeline_opts = PdfPipelineOptions()
    pipeline_opts.accelerator_options = accel_options
    pipeline_opts.do_ocr = do_ocr
    pipeline_opts.do_table_structure = True
    
    # 默认关闭高消耗功能以节省内存
    pipeline_opts.do_picture_classification = False 
    pipeline_opts.do_code_enrichment = False

    # ── 开启图片提取功能 (Step 1) ──────────────────────────────────────────
    pipeline_opts.generate_picture_images = True  # 提取内嵌图片
    pipeline_opts.generate_page_images = True     # 必须开启，TableItem.get_image() 依赖它
    pipeline_opts.images_scale = 2.0              # 提高清晰度 (2x)
    # ──────────────────────────────────────────────────────────────────────

    # 针对不同硬件的特性配置
    if device == AcceleratorDevice.CUDA:
        # NVIDIA GPU (3060Ti 等): 支持完整功能
        logger.info(f"配置 CUDA 加速: 启用公式识别, 线程数={num_threads}")
        pipeline_opts.do_formula_enrichment = True
    elif device == AcceleratorDevice.MPS:
        # Apple Silicon: 关闭公式识别以启用 MPS 加速（目前 MPS 对部分算子支持不全）
        logger.info(f"配置 MPS 加速: 禁用公式识别以确保存定性, 线程数={num_threads}")
        pipeline_opts.do_formula_enrichment = False
    else:
        # CPU 模式
        logger.info(f"配置 CPU 模式: 禁用公式识别以提升速度, 线程数={num_threads}")
        pipeline_opts.do_formula_enrichment = False

    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_opts)
        }
    )
    return converter


def extract_and_save_images(result, output_dir: Path, file_id: str) -> dict:
    """
    提取并保存文档中的图片和表格截图
    
    Returns:
        image_map (dict): 映射关系 { "ref_uri": "local_path" }
        key 是 Docling 内部引用的 URI/Ref
        value 是保存到本地的相对路径 (e.g. "images/{file_id}/pic_1.png")
    """
    from docling_core.types.doc import PictureItem, TableItem, ImageRefMode
    
    images_subdir = output_dir / "images" / file_id
    images_subdir.mkdir(parents=True, exist_ok=True)
    
    image_map = {}
    doc = result.document
    
    # 1. 提取图片 (PictureItem)
    pic_count = 0
    for item, _ in doc.iterate_items():
        if isinstance(item, PictureItem):
            # 获取图片数据 (PIL Image)
            try:
                img = item.get_image(doc)
                if img:
                    filename = f"pic_{pic_count}.png"
                    filepath = images_subdir / filename
                    img.save(filepath, "PNG")
                    
                    # 记录映射
                    web_path = f"/images/{file_id}/{filename}"
                    image_map[item.self_ref] = web_path
                    pic_count += 1
            except Exception as e:
                logger.warning(f"保存图片失败: {e}")

    # 2. 提取表格截图 (TableItem)
    table_count = 0
    for item, _ in doc.iterate_items():
        if isinstance(item, TableItem):
            try:
                img = item.get_image(doc)
                if img:
                    filename = f"table_{table_count}.png"
                    filepath = images_subdir / filename
                    img.save(filepath, "PNG")
                    
                    web_path = f"/images/{file_id}/{filename}"
                    image_map[item.self_ref] = web_path
                    table_count += 1
            except Exception as e:
                logger.warning(f"保存表格图片失败: {e}")
                
    logger.info(f"提取完成: {pic_count} 张图片, {table_count} 个表格截图")
    return image_map


def process_pdf_safely(file_path: str, output_dir: str = "./output", file_id: str = None, do_ocr: bool = True):
    """
    分块处理逻辑，防止 OOM
    :param file_id: 文件唯一ID，用于隔离图片存储
    :param do_ocr: 是否开启 OCR (建议纯文本 PDF 关闭)
    """
    file_path = Path(file_path)
    if not file_id:
        file_id = file_path.stem
        
    try:
        device = get_optimal_device()
        logger.info(f"开始解析: {file_path} on {device} Backend (OCR={do_ocr})")
        
        converter = get_optimized_converter(do_ocr=do_ocr)
        result = converter.convert(file_path)

        # ── Method A: 通用页眉/页脚过滤（坐标法）─────────────────────────────
        reclassify_furniture_by_position(result)
        # ──────────────────────────────────────────────────────────────────

        # ── 层级后处理：修正标题层级（字体大小/书签推断）──────────────────
        apply_hierarchy_postprocessor(result, str(file_path))
        # ──────────────────────────────────────────────────────────────────

        # ── 提取图片和表格 (Step 1) ───────────────────────────────────────
        data_dir = Path(output_dir).parent if Path(output_dir).name in ['mds', 'pdfs'] else Path(output_dir)
        
        image_map = extract_and_save_images(result, data_dir, file_id)
        # ──────────────────────────────────────────────────────────────────

        # ── 导出 Markdown ─────────────────────────────────────────────────
        # 使用 PLACEHOLDER 模式获取占位符，然后精确替换
        from docling_core.types.doc import ImageRefMode
        md_content = result.document.export_to_markdown(image_mode=ImageRefMode.PLACEHOLDER)
        
        # ── 精确替换图片引用 ────────────────────────────────────────────────
        # 方法：使用 image_map 中的键值对进行精确匹配替换
        # image_map 格式: { item.self_ref: "/images/{file_id}/pic_0.png" }
        
        # 创建用于替换的映射：按文件名中的数字排序
        sorted_image_items = sorted(
            image_map.items(),
            key=lambda x: int(re.search(r'_(pic|table)_(\d+)', x[1]).group(2)) if re.search(r'_(pic|table)_(\d+)', x[1]) else 0
        )
        
        # 用于跟踪已替换的图片（避免重复替换）
        replaced_refs = set()
        
        def replace_image_refs(match):
            """
            精确替换图片引用：
            1. 获取原始 markdown 中的引用（可能是占位符或原始URI）
            2. 在 image_map 中查找匹配的项
            3. 替换为本地保存的文件路径
            """
            nonlocal replaced_refs
            alt_text = match.group(1) if match.group(1) else "image"
            original_ref = match.group(2)  # 可能是 <!-- image --> 或原始 URI
            
            # 尝试在 image_map 中找到匹配的引用
            for doc_ref, local_path in sorted_image_items:
                if doc_ref not in replaced_refs:
                    # 匹配逻辑：
                    # 1. 完全匹配
                    # 2. 或者原始引用中包含 doc_ref 的一部分
                    # 3. 或者 doc_ref 包含原始引用的一部分
                    # 4. 对于占位符模式，使用顺序替换
                    if (doc_ref == original_ref or 
                        doc_ref in original_ref or 
                        original_ref in doc_ref or
                        "image" in original_ref.lower()):
                        
                        replaced_refs.add(doc_ref)
                        return f"![{alt_text}]({local_path})"
            
            # 如果找不到匹配，保留原始内容
            return match.group(0)
        
        # 替换所有图片引用
        md_content = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', replace_image_refs, md_content)
        
        # ──────────────────────────────────────────────────────────────────

        # ====== 修复标题层级 ======
        # Docling默认将所有标题识别为H2，根据章节编号推断正确层级
        md_content = fix_markdown_hierarchy(md_content)
        # ====== 层级修复完成 ======

        output_file = Path(output_dir) / f"{file_id}.md"
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(md_content)
            
        logger.info(f"解析完成，输出至: {output_file}")
        
        # 显式释放内存
        if hasattr(result.input, '_backend') and result.input._backend:
            result.input._backend.unload()
        del result
        del converter
        gc.collect()
        
        return md_content, data_dir
    except Exception as e:
        logger.error(f"解析失败: {e}")
        return None, None

if __name__ == "__main__":
    # 验证测试
    process_pdf_safely("your_test_doc.pdf")
