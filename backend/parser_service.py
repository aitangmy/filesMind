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
    智能设备配置：
    - Mac (MPS): 禁用公式识别以兼容 MPS，优化内存
    - Windows/Linux (CUDA): 启用全功能加速
    - CPU: 降级运行
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
    pipeline_opts.do_ocr = True
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
