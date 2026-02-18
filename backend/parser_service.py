import sys
import gc
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
            # Only consider text-like items
            if not hasattr(item, 'label') or item.label not in _CANDIDATE_LABELS:
                continue
            # Already marked as furniture — skip
            if hasattr(item, 'content_layer') and item.content_layer == ContentLayer.FURNITURE:
                continue
            # Must have provenance (page + bbox)
            if not item.prov:
                continue

            prov = item.prov[0]
            page_no = prov.page_no

            # Get page dimensions
            if page_no not in doc.pages:
                continue
            page = doc.pages[page_no]
            if page.size is None:
                continue
            page_h = page.size.height
            if page_h <= 0:
                continue

            # Get bounding box (Docling uses bottom-left origin by default)
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

def get_optimal_device():
    """
    自动检测最佳设备
    M4/M3/M2/M1 系列优先使用 MPS
    """
    if torch.backends.mps.is_available():
        logger.info("检测到 Apple Silicon MPS 加速可用")
        return AcceleratorDevice.MPS
    elif torch.cuda.is_available():
        logger.info("检测到 NVIDIA GPU 加速可用")
        return AcceleratorDevice.CUDA
    else:
        logger.warning("未检测到 GPU 加速，将使用 CPU")
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

def process_pdf_safely(file_path: str, output_dir: str = "./output", do_ocr: bool = True):
    """
    分块处理逻辑，防止 OOM
    :param do_ocr: 是否开启 OCR (建议纯文本 PDF 关闭)
    """
    file_path = Path(file_path)
    try:
        device = get_optimal_device()
        logger.info(f"开始解析: {file_path} on {device} Backend (OCR={do_ocr})")
        
        converter = get_optimized_converter(do_ocr=do_ocr)
        result = converter.convert(file_path)

        # ── Method A: 通用页眉/页脚过滤（坐标法）─────────────────────────────
        # 将页面顶部/底部 8% 区域内的文本元素标记为 FURNITURE 层，
        # 这样 export_to_markdown() 默认只导出 BODY 层时会自动跳过它们。
        # 完全通用，不依赖任何关键词或文档特定规则。
        reclassify_furniture_by_position(result)
        # ──────────────────────────────────────────────────────────────────

        # ── 层级后处理：修正标题层级（字体大小/书签推断）──────────────────
        # 必须在 export_to_markdown() 之前调用，因为它直接修改 result.document
        apply_hierarchy_postprocessor(result, str(file_path))
        # ──────────────────────────────────────────────────────────────────

        # 导出 Markdown（此时标题层级已被修正）
        md_content = result.document.export_to_markdown()
        
        output_file = Path(output_dir) / f"{file_path.stem}.md"
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(md_content)
            
        logger.info(f"解析完成，输出至: {output_file}")
        
        # 关键：显式释放内存
        if hasattr(result.input, '_backend') and result.input._backend:
            result.input._backend.unload()
        
        # Explicitly delete large objects
        del result
        del converter
        gc.collect()
        
        return md_content
    except Exception as e:
        logger.error(f"解析失败: {e}")
        return None

if __name__ == "__main__":
    # 验证测试
    process_pdf_safely("your_test_doc.pdf")
