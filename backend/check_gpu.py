import torch
import sys

def check_gpu():
    print("=" * 30)
    print("PyTorch Environment Information")
    print("=" * 30)
    print(f"Python: {sys.version.split(' ')[0]}")
    print(f"PyTorch: {torch.__version__}")
    
    cuda_available = torch.cuda.is_available()
    print(f"CUDA Available: {cuda_available}")
    
    if cuda_available:
        print(f"CUDA Version: {torch.version.cuda}")
        device_count = torch.cuda.device_count()
        print(f"Device Count: {device_count}")
        for i in range(device_count):
            print(f"- Device {i}: {torch.cuda.get_device_name(i)}")
            
        try:
            # Simple tensor operation test
            x = torch.rand(5, 3)
            print("\nTensor Test (CPU): Success")
            x = x.cuda()
            print("Tensor Test (GPU): Success")
        except Exception as e:
            print(f"Tensor Test Failed: {e}")
    else:
        print("\nPossible Issues:")
        print("1. PyTorch CPU-only version installed (checking version string...)")
        if "+cpu" in torch.__version__:
            print("   -> CONFIRMED: You have a CPU-only version installed.")
        else:
            print("   -> Version string looks generic, but CUDA might not be found.")
            
        print("2. CUDA Toolkit missing or incompatible.")
        
    print("=" * 30)

if __name__ == "__main__":
    check_gpu()
