# Detectron2 设置与训练方案

## 环境现状
- **GPU**: NVIDIA GeForce RTX 3050 (4GB VRAM) — **不足**以训练 Detectron2 标准模型
- **CUDA**: 12.7 / 驱动 565.57.01
- **PyTorch**: 2.13.0+cpu 已安装（CUDA 版本曾导致 bus error，可能与驱动/PyTorch CUDA 12.4 不兼容）
- **Detectron2**: 未安装（需从源码编译，编译过程内存消耗大，当前环境已出现内存溢出）

## 安装步骤（编译时 ≥8GB RAM 空闲）

```bash
# 1. 先确保 CUDA PyTorch 正常工作
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124

# 2. 验证 CUDA
python -c "import torch; print(torch.cuda.is_available())"

# 3. 安装 detectron2（从源码）
pip install -e "git+https://github.com/facebookresearch/detectron2.git#egg=detectron2"

# 或使用预编译 wheel（如果存在对应版本）
pip install detectron2 -f https://dl.fbaipublicfiles.com/detectron2/wheels/cu124/torch2.6/index.html
```

## 内存优化方案

4GB VRAM 的训练策略：
- 使用 **Faster R-CNN R50-FPN**（不是 R101 或更大的）
- batch size = 1-2
- 图像 resize 到 800×600
- 使用梯度累积（gradient accumulation steps=4）
- 冻结 backbone 前几层

## 训练配置（参考）

```python
from detectron2.config import get_cfg
from detectron2 import model_zoo

cfg = get_cfg()
cfg.merge_from_file(model_zoo.get_config_file(
    "COCO-Detection/faster_rcnn_R_50_FPN_3x.yaml"))
cfg.DATASETS.TRAIN = ("layout_train",)
cfg.DATASETS.TEST = ("layout_val",)
cfg.DATALOADER.NUM_WORKERS = 2
cfg.MODEL.WEIGHTS = model_zoo.get_checkpoint_url(
    "COCO-Detection/faster_rcnn_R_50_FPN_3x.yaml")
cfg.SOLVER.IMS_PER_BATCH = 1
cfg.SOLVER.BASE_LR = 0.00025
cfg.SOLVER.MAX_ITER = 3000
cfg.SOLVER.GAMMA = 0.1
cfg.SOLVER.STEPS = (2000, 2600)
cfg.MODEL.ROI_HEADS.NUM_CLASSES = 10  # 本项目 10 类
cfg.MODEL.ROI_HEADS.BATCH_SIZE_PER_IMAGE = 128
cfg.INPUT.MIN_SIZE_TRAIN = (600, 800)
cfg.INPUT.MAX_SIZE_TRAIN = 1200
```

## 训练数据准备

1. 12 页人工标注 → COCO JSON
2. 61 条伪标签作为补充（score < 0.9 的排除）
3. 按 PDF 文件划分 train/val/test（避免同页面近似副本泄露）
4. 数据增强：随机翻转、亮度扰动、缩放

## 预期指标（基于类似项目估计）

| 指标 | 预估值 |
|------|--------|
| question_stem mAP@0.5 | ~0.85（人工标注12页后） |
| diagram mAP@0.5 | ~0.70（图形多样性大） |
| header mAP@0.5 | ~0.95（固定位置，简单） |
| formula mAP@0.5 | ~0.60（样本少） |
| 单页推理耗时（CPU） | ~2-5s |
| 单页推理耗时（GPU） | ~0.1-0.3s |

## 评估方案

除 mAP 外，需关注业务指标：
- diagram 完整率（裁剪出的内容图像是否完整）
- header 污染率（推理结果是否包含页眉）
- stem OCR 污染率（visual_text 是否被误标为 stem）
- 人工审核率（置信度 < 阈值需要人工检查的比例）
