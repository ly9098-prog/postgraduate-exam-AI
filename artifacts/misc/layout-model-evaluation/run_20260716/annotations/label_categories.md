# 统一版面标注类别定义

## 类别总表

| ID | 名称 | 颜色 | 语义 | COCO 超类 | 推理用途 |
|----|------|------|------|-----------|---------|
| 0 | background | — | 背景（非标注区域） | — | — |
| 1 | question_answer_block | 🟦 #1f77b4 | 一道完整题目（题干+图+选项） | question | source_snapshot 裁剪区域 |
| 2 | question_stem | 🟩 #2ca02c | 需要 OCR 进入题干的文字 | question | stem OCR 输入区域 |
| 3 | answer_block | 🟧 #ff7f0e | 普通文字选项（A/B/C/D） | question | 选项 OCR 输入区域 |
| 4 | diagram | 🟥 #d62728 | 树/图/邻接表等图形 | visual | content_image 裁剪区域 |
| 5 | table | 🟪 #9467bd | 表格 | visual | content_image 裁剪区域 |
| 6 | formula | 🟫 #8c564b | 公式 | visual | content_image 裁剪区域（OCR 标记为 visual_text） |
| 7 | option_image | 🟨 #bcbd22 | 图片型选项 | visual | content_image 裁剪区域 |
| 8 | header | ⬜ #7f7f7f | 页眉（不进入题目） | ignore | 排除区域 |
| 9 | footer | ⬜ #7f7f7f | 页脚（不进入题目） | ignore | 排除区域 |
| 10 | instruction | ⬜ #e377c2 | 答题说明/提示（不进入正文） | ignore | 排除区域 |

## 推理后处理规则

### 1. source_snapshot 生成
- 取 `question_answer_block` 的最小外接矩形，padding 5pt
- 若同一页有多个 `question_answer_block`，分别裁剪
- 若无 `question_answer_block`，fallback 到 `question_stem + answer_block + diagram` 的 union

### 2. content_image 生成
- 对每个 `diagram/table/formula/option_image` 独立裁剪
- 与这些区域重叠的 OCR 结果标记为 `visual_text`，不进入题干
- 同一 `question_answer_block` 内多个 visual 区域合并到一张 content_image

### 3. stem OCR
- 对 `question_stem` 区域运行 OCR
- 排除 `visual_text` 标记的文本
- 排除 `header/footer/instruction` 区域

### 4. answer OCR
- 对 `answer_block` 区域运行 OCR
- 按空间位置（上→下，左→右）排序后映射为 A/B/C/D 选项

## 导出格式

### COCO JSON
```json
{
  "images": [{"id": 1, "file_name": "p369.png", "width": 1134, "height": 851}],
  "annotations": [
    {"id": 1, "image_id": 1, "category_id": 4, 
     "bbox": [205, 134, 665, 206], "area": 136990, 
     "iscrowd": 0}
  ],
  "categories": [
    {"id": 1, "name": "question_answer_block", "supercategory": "question"},
    ...
  ]
}
```

### YOLO 格式
每张图片对应一个 `.txt` 文件，每行：`<class_id> <x_center> <y_center> <width> <height>`（归一化到 [0,1]）。

## 标注质量要求
- `question_answer_block` 必须完全包含其子区域
- `diagram/table/formula` 边界应紧贴视觉内容（可接受 ≤3pt padding）
- `header/footer` 应完整覆盖页眉/页脚区域
- 同一 `question_answer_block` 的 `question_stem` 和 `answer_block` 不应重叠
- `option_image` 应精确框住图片（不包含文字标签 A/B/C/D）
