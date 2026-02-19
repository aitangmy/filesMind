import sys
import gc
import re
import logging
import os
import shutil
import subprocess
# 解决 Windows 下 OpenMP 多重加载冲突 (OMP: Error #15)
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

import ssl
import urllib.request
from pathlib import Path
from typing import Any, Dict

# 配置 HuggingFace 镜像（解决国内网络访问问题）
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ["HF_HOME"] = os.path.expanduser("~/.cache/huggingface")
# os.environ["TRANSFORMERS_CACHE"] = os.path.expanduser("~/.cache/huggingface/transformers") # Deprecated
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


def _env_float(name: str, default: float, min_value: float | None = None, max_value: float | None = None) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning(f"{name}={raw!r} 不是有效数字，使用默认值 {default}")
        return default
    if min_value is not None and value < min_value:
        logger.warning(f"{name}={value} 小于最小值 {min_value}，使用默认值 {default}")
        return default
    if max_value is not None and value > max_value:
        logger.warning(f"{name}={value} 大于最大值 {max_value}，使用默认值 {default}")
        return default
    return value


def _env_int(name: str, default: int, min_value: int | None = None, max_value: int | None = None) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning(f"{name}={raw!r} 不是有效整数，使用默认值 {default}")
        return default
    if min_value is not None and value < min_value:
        logger.warning(f"{name}={value} 小于最小值 {min_value}，使用默认值 {default}")
        return default
    if max_value is not None and value > max_value:
        logger.warning(f"{name}={value} 大于最大值 {max_value}，使用默认值 {default}")
        return default
    return value


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = str(raw).strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    logger.warning(f"{name}={raw!r} 不是有效布尔值，使用默认值 {default}")
    return default


# 解析后端控制:
# - docling: 仅使用当前 Docling 流水线
# - marker: 仅使用 Marker (Surya-based)
# - hybrid: 先 Docling，质量不达标时自动回退 Marker
PARSER_BACKEND = os.getenv("PARSER_BACKEND", "docling").strip().lower()
HYBRID_NOISE_THRESHOLD = _env_float("HYBRID_NOISE_THRESHOLD", 0.20, min_value=0.0, max_value=1.0)
HYBRID_DOCLING_SKIP_SCORE = _env_float("HYBRID_DOCLING_SKIP_SCORE", 70.0, min_value=0.0, max_value=100.0)
HYBRID_SWITCH_MIN_DELTA = _env_float("HYBRID_SWITCH_MIN_DELTA", 2.0, min_value=0.0, max_value=50.0)
HYBRID_MARKER_MIN_LENGTH = _env_int("HYBRID_MARKER_MIN_LENGTH", 200, min_value=0, max_value=1000000)
MARKER_PREFER_API = _env_bool("MARKER_PREFER_API", False)

_parser_runtime_config: Dict[str, Any] = {
    "parser_backend": PARSER_BACKEND,
    "hybrid_noise_threshold": HYBRID_NOISE_THRESHOLD,
    "hybrid_docling_skip_score": HYBRID_DOCLING_SKIP_SCORE,
    "hybrid_switch_min_delta": HYBRID_SWITCH_MIN_DELTA,
    "hybrid_marker_min_length": HYBRID_MARKER_MIN_LENGTH,
    "marker_prefer_api": MARKER_PREFER_API,
}

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

def _normalize_parser_backend(value: str) -> str:
    backend = (value or "").strip().lower()
    if backend in {"docling", "marker", "hybrid"}:
        return backend
    logger.warning(f"未知 PARSER_BACKEND={value!r}，回退为 docling")
    return "docling"


def _coerce_float(name: str, value: Any, min_value: float, max_value: float, default: float) -> float:
    try:
        converted = float(value)
    except (TypeError, ValueError):
        logger.warning(f"{name}={value!r} 无效，使用默认值 {default}")
        return default
    if converted < min_value or converted > max_value:
        logger.warning(f"{name}={converted} 超出范围 [{min_value}, {max_value}]，使用默认值 {default}")
        return default
    return converted


def _coerce_int(name: str, value: Any, min_value: int, max_value: int, default: int) -> int:
    try:
        converted = int(value)
    except (TypeError, ValueError):
        logger.warning(f"{name}={value!r} 无效，使用默认值 {default}")
        return default
    if converted < min_value or converted > max_value:
        logger.warning(f"{name}={converted} 超出范围 [{min_value}, {max_value}]，使用默认值 {default}")
        return default
    return converted


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    lowered = str(value).strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    return default


def get_parser_runtime_config() -> Dict[str, Any]:
    return dict(_parser_runtime_config)


def update_parser_runtime_config(config: Dict[str, Any]):
    if not isinstance(config, dict):
        return

    backend = _normalize_parser_backend(str(config.get("parser_backend", _parser_runtime_config["parser_backend"])))
    _parser_runtime_config["parser_backend"] = backend
    _parser_runtime_config["hybrid_noise_threshold"] = _coerce_float(
        "hybrid_noise_threshold",
        config.get("hybrid_noise_threshold", _parser_runtime_config["hybrid_noise_threshold"]),
        0.0,
        1.0,
        HYBRID_NOISE_THRESHOLD,
    )
    _parser_runtime_config["hybrid_docling_skip_score"] = _coerce_float(
        "hybrid_docling_skip_score",
        config.get("hybrid_docling_skip_score", _parser_runtime_config["hybrid_docling_skip_score"]),
        0.0,
        100.0,
        HYBRID_DOCLING_SKIP_SCORE,
    )
    _parser_runtime_config["hybrid_switch_min_delta"] = _coerce_float(
        "hybrid_switch_min_delta",
        config.get("hybrid_switch_min_delta", _parser_runtime_config["hybrid_switch_min_delta"]),
        0.0,
        50.0,
        HYBRID_SWITCH_MIN_DELTA,
    )
    _parser_runtime_config["hybrid_marker_min_length"] = _coerce_int(
        "hybrid_marker_min_length",
        config.get("hybrid_marker_min_length", _parser_runtime_config["hybrid_marker_min_length"]),
        0,
        1000000,
        HYBRID_MARKER_MIN_LENGTH,
    )
    _parser_runtime_config["marker_prefer_api"] = _coerce_bool(
        config.get("marker_prefer_api", _parser_runtime_config["marker_prefer_api"]),
        MARKER_PREFER_API,
    )

    logger.info(
        "Parser runtime config updated: backend=%s, noise=%.2f, skip=%.1f, delta=%.1f, min_len=%d, marker_prefer_api=%s",
        _parser_runtime_config["parser_backend"],
        _parser_runtime_config["hybrid_noise_threshold"],
        _parser_runtime_config["hybrid_docling_skip_score"],
        _parser_runtime_config["hybrid_switch_min_delta"],
        _parser_runtime_config["hybrid_marker_min_length"],
        _parser_runtime_config["marker_prefer_api"],
    )


def _resolve_data_dir(output_dir: str) -> Path:
    output_path = Path(output_dir)
    return output_path.parent if output_path.name in ["mds", "pdfs"] else output_path


def _is_marker_available() -> bool:
    return shutil.which("marker_single") is not None


def _evaluate_markdown_noise(md_content: str) -> dict:
    """
    粗粒度质量度量:
    - invalid_heading_ratio 越高，说明版面噪声越多
    - heading_count 太低且正文较长，可能标题提取失败
    """
    from structure_utils import is_valid_heading

    lines = md_content.split("\n")
    heading_lines = []
    invalid = 0

    for line in lines:
        m = re.match(r"^(#+)\s+(.*)", line.strip())
        if not m:
            continue
        topic = m.group(2).strip()
        heading_lines.append(topic)
        if not is_valid_heading(topic):
            invalid += 1

    heading_count = len(heading_lines)
    invalid_ratio = (invalid / heading_count) if heading_count else 0.0
    text_len = len(md_content.strip())

    return {
        "heading_count": heading_count,
        "invalid_heading_count": invalid,
        "invalid_heading_ratio": invalid_ratio,
        "text_length": text_len,
    }


def _needs_marker_fallback(md_content: str, noise_threshold: float | None = None) -> bool:
    metrics = _evaluate_markdown_noise(md_content)
    heading_count = metrics["heading_count"]
    invalid_ratio = metrics["invalid_heading_ratio"]
    text_len = metrics["text_length"]
    threshold = (
        float(noise_threshold)
        if noise_threshold is not None
        else float(_parser_runtime_config.get("hybrid_noise_threshold", HYBRID_NOISE_THRESHOLD))
    )

    # 条件 1: 标题数量足够多但无效比例偏高
    if heading_count >= 20 and invalid_ratio >= threshold:
        logger.info(
            f"Hybrid fallback: invalid heading ratio {invalid_ratio:.1%} "
            f">= threshold {threshold:.1%}"
        )
        return True

    # 条件 2: 文本很长但标题很少，可能版面分析失败
    if text_len > 5000 and heading_count <= 3:
        logger.info("Hybrid fallback: long text with very few headings")
        return True

    return False


def _compute_quality_score(md_content: str) -> dict:
    """
    多维度质量评分（0-100），用于双引擎结果对比。

    维度:
    - valid_heading_ratio: 有效标题占比（越高越好）
    - heading_density: 标题密度是否合理（太少/太多都扣分）
    - structure_depth: 标题层级深度（有多级层级说明结构识别好）
    - content_per_heading: 每个标题下平均内容量（太少说明碎片化）
    """
    from structure_utils import is_valid_heading

    lines = md_content.split("\n")
    text_len = len(md_content.strip())

    # 收集标题信息
    total_headings = 0
    valid_headings = 0
    heading_levels = set()
    for line in lines:
        m = re.match(r"^(#+)\s+(.*)", line.strip())
        if not m:
            continue
        total_headings += 1
        level = len(m.group(1))
        topic = m.group(2).strip()
        heading_levels.add(level)
        if is_valid_heading(topic):
            valid_headings += 1

    # --- 维度 1: 有效标题比例 (0-30 分) ---
    valid_ratio = (valid_headings / total_headings) if total_headings else 0.0
    score_valid = valid_ratio * 30

    # --- 维度 2: 标题密度合理性 (0-25 分) ---
    # 理想密度: 每 500-2000 字符一个标题
    density_band = "none"
    chars_per_heading = 0.0
    if text_len > 0 and valid_headings > 0:
        chars_per_heading = text_len / valid_headings
        if 500 <= chars_per_heading <= 2000:
            score_density = 25  # 理想范围
            density_band = "ideal"
        elif 200 <= chars_per_heading < 500 or 2000 < chars_per_heading <= 5000:
            score_density = 15  # 可接受
            density_band = "acceptable"
        else:
            score_density = 5   # 太稀或太密
            density_band = "poor"
    elif text_len > 0:
        score_density = 0  # 没有标题
        density_band = "no_heading"
    else:
        score_density = 0

    # --- 维度 3: 结构深度 (0-25 分) ---
    depth = len(heading_levels)
    depth_band = "none"
    if depth >= 3:
        score_depth = 25
        depth_band = "deep"
    elif depth == 2:
        score_depth = 18
        depth_band = "mid"
    elif depth == 1:
        score_depth = 10
        depth_band = "flat"
    else:
        score_depth = 0

    # --- 维度 4: 内容充实度 (0-20 分) ---
    non_empty_lines = sum(1 for l in lines if l.strip() and not l.strip().startswith('#'))
    content_band = "none"
    content_per_h = 0.0
    if valid_headings > 0:
        content_per_h = non_empty_lines / valid_headings
        if content_per_h >= 5:
            score_content = 20
            content_band = "rich"
        elif content_per_h >= 2:
            score_content = 12
            content_band = "ok"
        else:
            score_content = 5
            content_band = "thin"
    elif non_empty_lines > 10:
        score_content = 8  # 有内容但无结构
        content_band = "unstructured"
    else:
        score_content = 0

    total_score = score_valid + score_density + score_depth + score_content

    result = {
        "score": round(total_score, 1),
        "valid_heading_ratio": round(valid_ratio, 3),
        "total_headings": total_headings,
        "valid_headings": valid_headings,
        "heading_levels": sorted(heading_levels),
        "text_length": text_len,
        "chars_per_heading": round(chars_per_heading, 2),
        "content_lines": non_empty_lines,
        "content_per_heading": round(content_per_h, 2),
        "signals": {
            "density_band": density_band,
            "depth_band": depth_band,
            "content_band": content_band,
        },
        "breakdown": {
            "valid": round(score_valid, 1),
            "density": round(score_density, 1),
            "depth": round(score_depth, 1),
            "content": round(score_content, 1),
        },
    }
    return result



def _find_marker_markdown(output_root: Path, file_stem: str) -> Path | None:
    preferred = output_root / f"{file_stem}.md"
    if preferred.exists():
        return preferred

    markdown_files = sorted(output_root.rglob("*.md"))
    if not markdown_files:
        return None

    # 优先同名文件，其次选择体积最大的 markdown（通常是主文档）
    for md in markdown_files:
        if md.stem == file_stem:
            return md
    return max(markdown_files, key=lambda p: p.stat().st_size)


def _copy_marker_images_and_rewrite(md_content: str, marker_root: Path, data_dir: Path, file_id: str) -> str:
    images_dir = data_dir / "images" / file_id
    images_dir.mkdir(parents=True, exist_ok=True)

    source_images = []
    for ext in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
        source_images.extend(marker_root.rglob(ext))

    if not source_images:
        return md_content

    remap = {}
    for idx, src in enumerate(sorted(source_images)):
        dst_name = f"marker_{idx}{src.suffix.lower()}"
        dst = images_dir / dst_name
        shutil.copy2(src, dst)

        # 保留多种 key 以匹配 markdown 中不同写法
        rel_from_root = src.relative_to(marker_root).as_posix()
        remap[rel_from_root] = f"/images/{file_id}/{dst_name}"
        remap[src.name] = f"/images/{file_id}/{dst_name}"

    def _replace(match):
        alt = match.group(1) or "image"
        ref = match.group(2).strip()
        ref_key = ref.split("#")[0].split("?")[0]
        ref_key = ref_key.lstrip("./")
        mapped = remap.get(ref_key) or remap.get(Path(ref_key).name)
        if not mapped:
            return match.group(0)
        return f"![{alt}]({mapped})"

    return re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", _replace, md_content)


def _is_marker_api_available() -> bool:
    try:
        from marker.converters.pdf import PdfConverter  # noqa: F401
        return True
    except Exception:
        return False


def _extract_marker_markdown(rendered: Any) -> str:
    if rendered is None:
        return ""
    if isinstance(rendered, str):
        return rendered
    if isinstance(rendered, dict):
        for key in ("markdown", "md", "text"):
            value = rendered.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return ""
    value = getattr(rendered, "markdown", None)
    if isinstance(value, str) and value.strip():
        return value
    if isinstance(rendered, (list, tuple)):
        for item in rendered:
            content = _extract_marker_markdown(item)
            if content:
                return content
    return ""


def _copy_marker_api_images_and_rewrite(md_content: str, rendered: Any, data_dir: Path, file_id: str) -> str:
    images = None
    if isinstance(rendered, dict):
        images = rendered.get("images") or rendered.get("image_dict")
    else:
        images = getattr(rendered, "images", None) or getattr(rendered, "image_dict", None)

    if not isinstance(images, dict) or not images:
        return md_content

    images_dir = data_dir / "images" / file_id
    images_dir.mkdir(parents=True, exist_ok=True)
    remap = {}

    for idx, (name, payload) in enumerate(images.items()):
        ext = ".png"
        if isinstance(name, str):
            suffix = Path(name).suffix.lower()
            if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
                ext = suffix

        dst_name = f"marker_api_{idx}{ext}"
        dst = images_dir / dst_name
        saved = False

        try:
            if hasattr(payload, "save"):
                payload.save(dst)
                saved = True
            elif isinstance(payload, (bytes, bytearray)):
                dst.write_bytes(payload)
                saved = True
            elif isinstance(payload, str) and os.path.exists(payload):
                shutil.copy2(payload, dst)
                saved = True
        except Exception:
            saved = False

        if not saved:
            continue

        web_path = f"/images/{file_id}/{dst_name}"
        name_str = str(name)
        remap[name_str] = web_path
        remap[Path(name_str).name] = web_path
        remap[name_str.lstrip("./")] = web_path

    if not remap:
        return md_content

    def _replace(match):
        alt = match.group(1) or "image"
        ref = match.group(2).strip()
        ref_key = ref.split("#")[0].split("?")[0].lstrip("./")
        mapped = remap.get(ref_key) or remap.get(Path(ref_key).name)
        if not mapped:
            return match.group(0)
        return f"![{alt}]({mapped})"

    return re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", _replace, md_content)


def _run_marker_pipeline_api(file_path: Path, output_dir: str, file_id: str, do_ocr: bool):
    if not _is_marker_api_available():
        raise RuntimeError("marker-pdf Python API 不可用")

    data_dir = _resolve_data_dir(output_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    from marker.converters.pdf import PdfConverter

    rendered = None
    errors = []

    # 尝试 API 变体 1：默认构造器
    try:
        converter = PdfConverter()
        if hasattr(converter, "convert"):
            rendered = converter.convert(str(file_path))
        else:
            rendered = converter(str(file_path))
    except Exception as e:
        errors.append(f"default_ctor: {e}")

    # 尝试 API 变体 2：artifact_dict 构造器
    if rendered is None:
        try:
            from marker.models import create_model_dict
            converter = PdfConverter(artifact_dict=create_model_dict())
            if hasattr(converter, "convert"):
                rendered = converter.convert(str(file_path))
            else:
                rendered = converter(str(file_path))
        except Exception as e:
            errors.append(f"artifact_ctor: {e}")

    if rendered is None:
        raise RuntimeError("Marker API 调用失败: " + " | ".join(errors)[:500])

    md_content = _extract_marker_markdown(rendered)
    if not md_content or not md_content.strip():
        raise RuntimeError("Marker API 未返回有效 markdown")

    md_content = _copy_marker_api_images_and_rewrite(md_content, rendered, data_dir, file_id)
    md_content = fix_markdown_hierarchy(md_content)

    output_file = Path(output_dir) / f"{file_id}.md"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(md_content, encoding="utf-8")
    logger.info(f"Marker API 解析完成，输出至: {output_file}")
    return md_content, data_dir


def _run_marker_pipeline_cli(file_path: Path, output_dir: str, file_id: str, do_ocr: bool):
    if not _is_marker_available():
        raise RuntimeError("marker_single 不可用，请先安装 marker-pdf")

    data_dir = _resolve_data_dir(output_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    marker_root = data_dir / "marker_out" / file_id
    marker_root.mkdir(parents=True, exist_ok=True)

    base_command = [
        "marker_single",
        str(file_path),
        "--output_dir",
        str(marker_root),
    ]
    command_variants = [
        base_command + ["--output_format", "markdown"],
        base_command,
    ]
    if do_ocr:
        command_variants[0].append("--force_ocr")
        command_variants[1].append("--force_ocr")

    last_error = ""
    for command in command_variants:
        logger.info(f"Marker 解析开始: {' '.join(command)}")
        proc = subprocess.run(command, capture_output=True, text=True)
        if proc.returncode == 0:
            break

        stderr = (proc.stderr or "").strip()
        stdout = (proc.stdout or "").strip()
        details = stderr or stdout or "Unknown marker error"
        last_error = details[:500]

        # 常见兼容场景：旧版本 marker_single 不支持 --output_format
        if "--output_format" in command:
            logger.warning("Marker CLI 可能不支持 --output_format，尝试兼容命令")
            continue

        raise RuntimeError(f"Marker 解析失败: {last_error}")
    else:
        raise RuntimeError(f"Marker 解析失败: {last_error}")

    markdown_path = _find_marker_markdown(marker_root, file_path.stem)
    if not markdown_path:
        raise RuntimeError("Marker 输出中未找到 Markdown 文件")

    md_content = markdown_path.read_text(encoding="utf-8", errors="ignore")
    md_content = _copy_marker_images_and_rewrite(md_content, marker_root, data_dir, file_id)
    md_content = fix_markdown_hierarchy(md_content)

    output_file = Path(output_dir) / f"{file_id}.md"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(md_content, encoding="utf-8")

    logger.info(f"Marker 解析完成，输出至: {output_file}")
    return md_content, data_dir


def _run_marker_pipeline(file_path: Path, output_dir: str, file_id: str, do_ocr: bool):
    settings = get_parser_runtime_config()
    prefer_api = bool(settings.get("marker_prefer_api", False))
    order = ("api", "cli") if prefer_api else ("cli", "api")
    last_error = None

    for mode in order:
        try:
            if mode == "api":
                return _run_marker_pipeline_api(file_path, output_dir, file_id, do_ocr)
            return _run_marker_pipeline_cli(file_path, output_dir, file_id, do_ocr)
        except Exception as e:
            last_error = e
            logger.warning(f"Marker {mode.upper()} 解析失败，将尝试其他通道: {e}")

    raise RuntimeError(f"Marker 所有通道均失败: {last_error}")


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


def _run_docling_pipeline(file_path: Path, output_dir: str, file_id: str, do_ocr: bool):
    """
    分块处理逻辑，防止 OOM
    :param file_id: 文件唯一ID，用于隔离图片存储
    :param do_ocr: 是否开启 OCR (建议纯文本 PDF 关闭)
    """
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
        data_dir = _resolve_data_dir(output_dir)
        
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
        logger.error(f"Docling 解析失败: {e}")
        return None, None


def process_pdf_safely(
    file_path: str,
    output_dir: str = "./output",
    file_id: str = None,
    do_ocr: bool = True,
    parser_backend: str | None = None,
):
    """
    统一 PDF 解析入口。
    parser_backend:
      - docling: 仅 Docling
      - marker: 仅 Marker
      - hybrid: 先 Docling，质量不达标自动回退 Marker
    """
    path = Path(file_path)
    effective_file_id = file_id or path.stem
    settings = get_parser_runtime_config()
    backend = _normalize_parser_backend(parser_backend or settings.get("parser_backend", PARSER_BACKEND))
    hybrid_skip_score = float(settings.get("hybrid_docling_skip_score", HYBRID_DOCLING_SKIP_SCORE))
    hybrid_switch_delta = float(settings.get("hybrid_switch_min_delta", HYBRID_SWITCH_MIN_DELTA))
    hybrid_marker_min_len = int(settings.get("hybrid_marker_min_length", HYBRID_MARKER_MIN_LENGTH))

    if backend == "docling":
        return _run_docling_pipeline(path, output_dir, effective_file_id, do_ocr)

    if backend == "marker":
        return _run_marker_pipeline(path, output_dir, effective_file_id, do_ocr)

    # hybrid mode: 双向质量评分选优
    docling_md, docling_data_dir = _run_docling_pipeline(path, output_dir, effective_file_id, do_ocr)
    if not docling_md:
        logger.warning("Hybrid: Docling 失败，尝试 Marker")
        try:
            return _run_marker_pipeline(path, output_dir, effective_file_id, do_ocr)
        except Exception as e:
            logger.error(f"Hybrid: Marker 也失败，任务终止: {e}")
            return None, None

    docling_score = _compute_quality_score(docling_md)
    logger.info(
        "Hybrid: Docling 评分={score:.1f}, breakdown={breakdown}, "
        "signals={signals}, 标题={valid}/{total}, 层级={levels}, chars/heading={cph}, "
        "skip_threshold={skip}, switch_delta={delta}".format(
            score=docling_score["score"],
            breakdown=docling_score["breakdown"],
            signals=docling_score["signals"],
            valid=docling_score["valid_headings"],
            total=docling_score["total_headings"],
            levels=docling_score["heading_levels"],
            cph=docling_score["chars_per_heading"],
            skip=hybrid_skip_score,
            delta=hybrid_switch_delta,
        )
    )

    # 如果 Docling 质量足够好，直接返回，不浪费资源跑 Marker
    if docling_score["score"] >= hybrid_skip_score:
        logger.info(f"Hybrid: Docling 质量优秀 (>={hybrid_skip_score})，跳过 Marker")
        return docling_md, docling_data_dir

    # Docling 质量不理想，用 Marker 对比
    if not (_is_marker_available() or _is_marker_api_available()):
        logger.warning("Hybrid: Docling 质量偏低且 Marker API/CLI 均不可用，继续使用 Docling 结果")
        return docling_md, docling_data_dir

    try:
        marker_md, marker_data_dir = _run_marker_pipeline(path, output_dir, effective_file_id, do_ocr)
        if not marker_md or len(marker_md.strip()) < hybrid_marker_min_len:
            logger.warning(
                f"Hybrid: Marker 输出过短 (<{hybrid_marker_min_len} chars)，保留 Docling 结果"
            )
            return docling_md, docling_data_dir

        marker_score = _compute_quality_score(marker_md)
        logger.info(
            "Hybrid: Marker 评分={score:.1f}, breakdown={breakdown}, "
            "signals={signals}, 标题={valid}/{total}, 层级={levels}, chars/heading={cph}".format(
                score=marker_score["score"],
                breakdown=marker_score["breakdown"],
                signals=marker_score["signals"],
                valid=marker_score["valid_headings"],
                total=marker_score["total_headings"],
                levels=marker_score["heading_levels"],
                cph=marker_score["chars_per_heading"],
            )
        )

        # 择优: marker 分数必须超过最小切换差值，避免小波动导致频繁切换
        if marker_score["score"] > docling_score["score"] + hybrid_switch_delta:
            delta = marker_score["score"] - docling_score["score"]
            logger.info(
                f"Hybrid: 选择 Marker (评分比 Docling 高 {delta:.1f} 分: "
                f"{marker_score['score']:.1f} vs {docling_score['score']:.1f})"
            )
            return marker_md, marker_data_dir
        else:
            delta = marker_score["score"] - docling_score["score"]
            logger.info(
                f"Hybrid: 保留 Docling (delta={delta:.1f}，未达到切换阈值 {hybrid_switch_delta:.1f}; "
                f"Docling={docling_score['score']:.1f}, Marker={marker_score['score']:.1f})"
            )
            return docling_md, docling_data_dir

    except Exception as e:
        logger.warning(f"Hybrid: Marker 回退失败，保留 Docling 结果: {e}")

    return docling_md, docling_data_dir

if __name__ == "__main__":
    # 验证测试
    process_pdf_safely("your_test_doc.pdf")
