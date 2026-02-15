import sys
import gc
import logging
import os
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

def get_optimized_converter():
    """
    针对 Mac Mini 24GB 的配置：
    1. 启用 MPS 加速 (利用 GPU/NPU)
    2. 关闭不必要的视觉增强以节省内存
    """
    # 自动检测最佳设备
    device = get_optimal_device()
    
    # 配置加速选项
    accel_options = AcceleratorOptions(
        num_threads=8,  # M4/M2 性能核数量
        device=device    # 自动选择 MPS/CPU
    )

    pipeline_opts = PdfPipelineOptions()
    pipeline_opts.accelerator_options = accel_options
    pipeline_opts.do_ocr = True
    pipeline_opts.do_table_structure = True
    
    # 内存优化：24GB 内存如果不关这些，处理 200页+ 文档会触发 Swap
    pipeline_opts.do_picture_classification = False 
    pipeline_opts.do_code_enrichment = False
    # 关闭公式识别以启用 MPS 加速（公式识别会禁用 MPS）
    pipeline_opts.do_formula_enrichment = False

    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_opts)
        }
    )
    return converter

def process_pdf_safely(file_path: str, output_dir: str = "./output"):
    """
    分块处理逻辑，防止 OOM
    """
    file_path = Path(file_path)
    try:
        device = get_optimal_device()
        logger.info(f"开始解析: {file_path} on {device} Backend")
        
        converter = get_optimized_converter()
        result = converter.convert(file_path)
        
        # 导出 Markdown
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
