import logging

logger = logging.getLogger("HardwareUtils")

try:
    import torch
except Exception:
    torch = None

def get_hardware_info():
    """
    检测当前硬件环境
    返回: dict with keys 'device_type', 'name', 'details'
    """
    if torch is None:
        device_type = "cpu"
        device_name = "CPU"
    elif torch.cuda.is_available():
        device_type = "gpu"
        device_name = torch.cuda.get_device_name(0)
    elif torch.backends.mps.is_available():
        device_type = "mps"
        device_name = "Apple Silicon (MPS)"
    else:
        device_type = "cpu"
        device_name = "CPU"
    
    return {
        "device_type": device_type,
        "name": device_name,
        "details": f"Running on {device_name}"
    }

def is_accelerator_available():
    """如果可用 GPU 或 MPS，返回 True"""
    info = get_hardware_info()
    return info["device_type"] in ["gpu", "mps"]
