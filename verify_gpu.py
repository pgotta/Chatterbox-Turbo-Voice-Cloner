import sys

import torch

print("PyTorch:", torch.__version__, "CUDA runtime:", torch.version.cuda)

if not torch.cuda.is_available():
    sys.exit("CUDA unavailable; this build requires a CUDA-capable NVIDIA GPU.")

name = torch.cuda.get_device_name(0)
cc = torch.cuda.get_device_capability(0)
arch = torch.cuda.get_arch_list()
print("GPU:", name)
print("Compute capability:", f"{cc[0]}.{cc[1]}")
print("PyTorch CUDA architectures:", arch)

x = torch.randn((16, 16), device="cuda")
_ = x @ x
torch.cuda.synchronize()
print("CUDA test PASSED")
