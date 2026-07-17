# GPU Environment Report

> Generated: 2026-07-17T09:10:43Z

## Summary

- Status: **❌ FAILED**
- Checks passed: 2
- Checks failed: 1

## System

- Python: 3.12.3
- Platform: Linux-6.18.33.2-microsoft-standard-WSL2-x86_64-with-glibc2.39
- CUDA libraries: 3

## GPU Hardware

- Driver: 566.03
- GPU: NVIDIA GeForce RTX 3050 Ti Laptop GPU
- VRAM: 4096 MiB
- Compute Capability: 8.6

## PaddlePaddle

- Imported: True
- Version: 3.3.1
- Compiled with CUDA: False

## PaddleOCR

- Imported: True
- Version: unknown

### Preflight Results

| ✅ | paddle import |
| ❌ | compiled_with_cuda |
| ❌ | cuda_device_count >= 1 |
| ❌ | paddle.utils.run_check |
| ❌ | tensor computation |
| ✅ | paddleocr import |