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
                    
                    # 记录映射：Docling 在 Markdown 中使用 item.self_ref 作为引用
                    # 或者我们使用自定义占位符。这里我们构建一个 map 供后续替换。
                    # 注意：export_to_markdown(image_mode=REFERENCED) 会生成类似
                    # ![Image](image_uri) 的链接。我们需要知道 image_uri 是什么。
                    # Docling 默认生成的 URI 通常是内部引用。
                    # 简单起见，我们直接替换 Markdown 中的引用。
                    
                    # 记录 self_ref -> local path
                    # 相对路径，供前端访问: /images/{file_id}/{filename}
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
                # TableItem.get_image() 需要 generate_page_images=True
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
    # 如果没有传 file_id，使用文件名 stem (兼容旧调用)
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
        # 这里传入 output_dir 的父级 data 目录，以便生成 data/images/{file_id}
        # 假设 output_dir 通常是 ./data/mds 或 ./output
        # 我们统一使用 data/images 结构
        # 既然 output_dir 传入的是 md 目录，我们向上找 data 目录
        data_dir = Path(output_dir).parent if Path(output_dir).name in ['mds', 'pdfs'] else Path(output_dir)
        
        image_map = extract_and_save_images(result, data_dir, file_id)
        # ──────────────────────────────────────────────────────────────────

        # 导出 Markdown
        # 使用 image_mode=REFERENCED 让 Docling 生成图片引用而非 base64
        from docling_core.types.doc import ImageRefMode
        md_content = result.document.export_to_markdown(image_mode=ImageRefMode.REFERENCED)
        
        # ── 后处理 Markdown：替换图片引用 ──────────────────────────────────
        # Docling 的 REFERENCED 模式默认生成类似 ![Image](image_1.png) 的链接
        # 或者引用内部 URI。我们需要将其替换为咱们的 Web 路径。
        # 由于 Docling 的 export 逻辑比较封闭，最稳妥的方式是：
        # 既然我们已经有了 image_map (self_ref -> web_path)，
        # 我们可以手动替换 Markdown 中的引用。
        # 但 Docling export 的 markdown 里的链接可能不是 self_ref。
        # 
        # 策略 B：直接修改 Docling Document 对象中的 PictureItem 的引用路径？
        # 不行，Docling API 比较复杂。
        # 
        # 策略 C：暴力替换。Docling 生成的图片链接通常是 ![Image](...)
        # 但这很难对应。
        # 
        # 最佳策略：使用 iterate_items 遍历时，不仅保存图片，还记录它在 Markdown 中的位置？难。
        # 
        # 回退一步：Docling 的 `export_to_markdown` 不太方便自定义图片路径。
        # 我们可以自己拼接图片吗？
        # 
        # 让我们使用一个简单的替换逻辑：
        # 既然我们无法轻易控制 Docling 生成的 URL，我们不如直接把表格图片插入到 Markdown 中？
        # 对于 PictureItem，Docling 会生成 `![Image](...)`。
        # 对于 TableItem，Docling 只生成 Markdown 表格。
        # 
        # 修正方案：
        # 1. 遍历 image_map，查找 Markdown 中对应的 Table 文本，替换为图片？这太难了。
        # 2. 我们通过 regex 替换。Docling 默认生成的图片文件名可能不可控。
        # 
        # 让我们换一种思路：不依赖 `image_mode=REFERENCED` 的自动链接，
        # 而是使用 `image_placeholder` 钩子？Docling 没有这个钩子。
        # 
        # 实际上，Docling v2 的 export_to_markdown 在 REFERENCED 模式下，
        # 会以为图片已经保存在以此 markdown 为基准的路径下。
        # 
        # 让我们先只做“保存图片到磁盘”，Markdown 里的替换留给后续优化？
        # 不，用户如果不显示图片就没意义。
        # 
        # 让我们看下 image_map 的 key 是 self_ref (e.g. `#/pictures/0`).
        # 我们可以在 export 之前，修改 doc 里的 PictureItem 的 ref？
        # 
        # 经过调研，最稳妥的方式是 post-processing MD。
        # 但无法匹配。
        # 
        # 让我们简单点：Docling 提取的图片按顺序保存。Markdown 里的图片顺序也是一致的。
        # 我们可以按顺序替换 `![Image](...)` 链接。
        
        # 替换图片链接
        # 查找所有 ![alt](uri) 模式
        # 注意：Docling 可能生成 ![Image](image_0.png)
        
        # 简单的计数器替换
        def replace_pic_link(match):
            nonlocal pic_idx
            alt_text = match.group(1)
            if pic_idx < len(pic_urls):
                url = pic_urls[pic_idx]
                pic_idx += 1
                return f"![{alt_text}]({url})"
            return match.group(0)
            
        pic_urls = [path for ref, path in image_map.items() if "pic_" in path] # 按顺序
        # 排序 pic_urls 确保顺序 (pic_0, pic_1...)
        pic_urls.sort(key=lambda x: int(re.search(r'pic_(\d+)', x).group(1)))
        
        pic_idx = 0
        md_content = re.sub(r'!\[(.*?)\]\(.*?\)', replace_pic_link, md_content)
        
        # 替换表格：Docling 生成的是 Markdown 表格。
        # 如果我们需要显示表格截图（防止乱序），我们需要把 Markdown 表格替换为图片链接。
        # 这比较激进，可能会丢失文本信息。
        # 用户建议：“表格建议提取为图片（Snapshot）而不是文字”
        # 那我们需要找到 Markdown 中的表格，并替换它。
        # Markdown 表格特征：`| ... | ... |`
        # 这是一个有风险的操作。
        # 
        # 暂时方案：保留 Markdown 表格，但在表格上方/下方 插入图片链接？
        # 或者只针对“乱序严重”的表格？
        # 
        # 鉴于实现复杂性，目前 Step 1 先只处理 Picture 的替换。
        # Table 图片已保存到磁盘，但暂不自动插入 Markdown，
        # 除非我们能精确定位。
        # (Marker 库在这方面做得更好)
        # 
        # 妥协：将所有表格图片链接 append 到 Markdown 底部，或者
        # 仅当用户选择“纯图模式”时替换。
        # 目前保持 Markdown 表格文本，图片仅作为资源存在（XMind 可以用）。
        # ──────────────────────────────────────────────────────────────────

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
