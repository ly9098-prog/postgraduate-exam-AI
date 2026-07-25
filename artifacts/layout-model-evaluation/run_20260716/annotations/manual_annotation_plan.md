# 人工标注集计划

## 策略
从 ds_sc.pdf 的 28 个候选页中选取 12 页作为首批人工标注。
标注使用 COCO 格式（主）和 YOLO 格式（辅）。

## 选取原则
1. 覆盖所有 10 个标注类别
2. 覆盖所有特殊版面模式
3. 至少包含 1 页 CDLA 检出 figure 和 1 页 CDLA 漏检
4. 包含 auto-approved 和 manual_override 各至少 1 页

## 12 页推荐列表

| 页码 | 题号 | 版面特征 | 主要标注目标 | 难度 |
|------|------|---------|-------------|------|
| 229 | 229 | 普通文字+图 | question_stem, answer_block, diagram | 低 |
| 343 | 343 | 含 formula + footer | question_stem, answer_block, formula | 中 |
| 345 | 345 | 页眉清晰 | header, question_stem, diagram | 低 |
| 369 | 369 | 4个BST图+选项组 | question_stem, diagram(×4), option_image | 高 |
| 371 | 371 | 邻接表（CDLA漏检） | question_stem, diagram | 中 |
| 378 | 378 | 图（CDLA检出figure） | question_stem, diagram | 低 |
| 380 | 380 | B+树（CDLA漏检） | question_stem, diagram | 中 |
| 397 | 397 | 自动通过(auto_approved) | question_stem, diagram | 低 |
| 400 | 400 | 页眉清晰+answer_block | header, question_stem, answer_block | 低 |
| 405 | 405 | 含 reference 标签 | question_stem, instruction, diagram | 中 |
| 412 | 412 | 含 equation | question_stem, answer_block, formula | 中 |
| 480 | 480 | 宽图（manual calibration） | question_stem, diagram | 低 |

## 标注类别覆盖矩阵

| 类别 | p229 | p343 | p345 | p369 | p371 | p378 | p380 | p397 | p400 | p405 | p412 | p480 |
|------|------|------|------|------|------|------|------|------|------|------|------|------|
| question_stem | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| answer_block | ✅ | ✅ |   |   |   |   |   |   | ✅ |   | ✅ |   |
| diagram | ✅ |   | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |   | ✅ |   | ✅ |
| formula |   | ✅ |   |   |   |   |   |   |   |   | ✅ |   |
| option_image |   |   |   | ✅ |   |   |   |   |   |   |   |   |
| header |   |   | ✅ |   |   |   |   |   | ✅ |   |   |   |
| footer |   | ✅ |   |   |   |   |   |   |   |   |   |   |
| instruction |   |   |   |   |   |   |   |   |   | ✅ |   |   |

## 标注工具建议
- labelme (COCO JSON 格式)
- Label Studio (开源，支持多人协作)
- CVAT (功能全，但部署重)

## 质量门禁
1. question_stem 和 diagram 不应重叠
2. header 顶部从 y=0 开始，底部不超过 y=28pt
3. diagram 边界应紧贴视觉内容（≤3pt padding）
4. 同页多图时每个图独立标注
5. 选项区标注为 answer_block，不标注单个选项

## 后续步骤
1. 使用 labelme 或 Label Studio 完成 12 页标注
2. 导出 COCO JSON 格式
3. 与伪标签合并作为初始训练集
4. 按 PDF 文件切分 train/val/test (70/15/15)
