# 版面模型推理流程设计

## 最终推理流程

```
输入: PDF 页面（或页面截图）
  │
  ├─ 1. 版面检测（模型推理）
  │    Detectron2 Faster R-CNN / PP-StructureV3
  │    输出: 所有版面区域（bbox + 类别 + 置信度）
  │
  ├─ 2. 区域分类后处理
  │    ├─ question_answer_block → 生成 source_snapshot（整题截图）
  │    ├─ question_stem → 送入 OCR，结果进入题干
  │    ├─ answer_block → 送入 OCR，按空间排序映射为选项
  │    ├─ diagram/table/formula/option_image → 生成 content_image
  │    ├─ header/footer/instruction → 丢弃，不进入任何 OCR 输入
  │    └─ 低置信度区域 → 人工审核队列
  │
  ├─ 3. OCR 与 visual_text 标记
  │    ├─ 对 question_stem + answer_block 运行 OCR
  │    ├─ 与 diagram/table/formula 区域重叠的 OCR 行 → 标记为 visual_text
  │    └─ visual_text 不进入题干文本
  │
  ├─ 4. 空间关系校验
  │    ├─ OCR 题号只作为模型结果的校验（不直接决定 visual_bbox）
  │    ├─ 若 layout bbox 包含多个 sub-region，拆分
  │    └─ 校验 question_stem 和 diagram 不重叠
  │
  └─ 5. 输出
       ├─ segments（用于前端渲染）
       ├─ content_image（学生端看图）
       ├─ source_snapshot（管理端审核）
       ├─ cleaned_stem（纯文本题干）
       └─ confidence + requires_review 标记
```

## 与当前 visual-v2 规则的关键区别

| 方面 | 当前 visual-v2 | 模型方案 |
|------|---------------|---------|
| visual_bbox 来源 | OCR 文本行 union → 前景像素分析 | 模型直接检测 |
| header 排除 | 固定 y0 < 28pt 硬编码 | 模型检测 header 类别 |
| stem/answer 分离 | 依赖 OCR 行分类（zone 规则） | 模型检测 question_stem / answer_block |
| diagram 检测 | 人工配置或 manifest bbox | 模型检测 diagram 类别 |
| visual_text | OCR 行在视觉区重叠判断 | 模型边界直接判断 |
| 人工审核率 | 27/28 = 96%（仅 1 页自动通过） | 预计 20-40% |
| 新 PDF 适配 | 需手工调参（header_bottom、空白比等） | 模型直接推理（零样本或 fine-tune） |

## 回退策略

当模型方案置信度不足时，回退到当前 visual-v2 规则：

```
if model_confidence >= 0.7:
    使用模型结果
elif 0.4 <= model_confidence < 0.7:
    模型结果 + 人工审核
else:
    回退到 visual-v2 规则（前景分析 + OCR zone 分类）
```

## 部署考虑

- **推理设备**: 需 GPU（RTX 3050 4GB 或更高），CPU 推理太慢（2-5s/页）
- **模型大小**: ~150MB（Faster R-CNN R50-FPN）
- **批量处理**: 离线批量生成，不要求实时
- **训练环境**: 本地 i7+3060（与当前 OCR 导入流程一致）
