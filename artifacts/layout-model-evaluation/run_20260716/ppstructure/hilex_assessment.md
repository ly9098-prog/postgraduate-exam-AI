# HiLEx 数据集评估报告

## 概述
HiLEx (Hierarchical Layout Examination) 是一个面向试卷文档的版面分析基准数据集，提供层次化标注。

## 标注体系

HiLEx 定义 6 类版面结构，映射到本项目如下：

| HiLEx 类别 | 本项目映射 |
|-----------|-----------|
| Question_Answer_Block | question_bbox → source_snapshot |
| Question_Block | question_stem（题干文字区域） |
| Answer_Block | answer_block（选项文字区域） |
| Instruction | instruction（答题说明，不进入正文） |
| Figure/Table | diagram/table（视觉资源） |
| Header/Footer | header/footer（不进入题目） |

## 标注格式
- 主格式：COCO JSON
- 可选：YOLO 格式
- 图像为试卷页面扫描件

## 可复用性评估

### 优势
1. **专为试卷设计** — 类别与本项目需求高度对齐
2. **COCO 格式** — 可直接用于 Detectron2 训练
3. **层次化结构** — QA Block → Question/Answer 的父子关系对本项目 multi-blank-choice 的多层结构有参考价值

### 限制
1. **中文试卷** — HiLEx 本身就是中文数据集，不存在语言不兼容问题
2. **页面风格差异** — HiLEx 可能包含多种考试类型，不一定涵盖本项目的"数据结构"特定图表（树、图、邻接表）
3. **训练代码耦合** — HiLEx benchmark 代码多绑定 Detectron2，复用时需适配本项目的数据加载

## 是否可以直接处理本项目页面
✅ 可以处理中文页面，但：
- 零样本推理效果依赖模型训练数据覆盖的题型范围
- 对于树/图类图表（BST、B+树、邻接表），需验证检测效果

## 推荐使用方式
1. 使用 HiLEx 的标注体系作为本项目标注模板
2. 复用其 COCO 格式和 Detectron2 训练管线
3. 使用 HiLEx 预训练权重作为本项目的 fine-tune 起点（如果可用）
4. 补充本项目特有的标注类别（如 option_image, formula）

## 不可用场景
- 无法直接用 HiLEx 权重推理本项目页面（除非已 fine-tune）
- 不包含公式/图表专用的区域细分（本项目需要 diagram/table/formula 细分类别）

> 注意：网络访问受限，无法下载实际数据集和验证标注文件。以上评估基于文档描述和已知信息。
