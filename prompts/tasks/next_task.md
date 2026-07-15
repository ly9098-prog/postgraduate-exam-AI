# 下一轮任务：数据结构题库审核 & 看图答题题目补图

## 背景

数据结构题库（`ds_sc.pdf`，513 页）已完成全量导入，`question_imports` 共 **513 条记录**，均为 `pending` 状态。`AUTO_PUBLISH=false`，questions 表未修改。

导入流程：逐页 OCR（PaddleOCR）→ `submit_to_review` 直接入库，跳过 pipeline 的多阶段流程（拆题器/结构分析/冻结/分类/去重等不适用于每页一题的格式）。

## 任务 A：逐题审核（人工）

`question_imports` 中 513 道题均为 `single_choice`，全部处于 `pending` 状态。需要逐题审核后通过管理端 API 发布到 `questions` 表。

审核重点：
- 题干是否完整、无 OCR 错字
- A/B/C/D 选项是否正确配对
- 答案是否确实为空（PDF 原页无答案栏，所有 `parsed_answer` 均为 null）
- 部分题目（约 27 题）引用原页图片/图/树/图结构，当前 OCR 文本无法还原图形信息

## 任务 B：看图答题题目补图（需开发）

### 问题描述

当前导入流程只用 PaddleOCR 提取了文本，**没有对题目涉及的图片/图/树/图结构进行截图保存**。27 道题在题干中明确引用"下图所示"或"如下图所示"，但 `parsed_content` 中只有文本描述，缺少原始图片。

需要开发的功能：
1. PDF 页面截取功能：对每道引用图片的题目，从原始 PDF 对应页面截取图片区域
2. 将截图存入可用于刷题展示的存储（如 `formula_graph_assets` 或新建关联模型）
3. 在发布到 `questions` 表时，图片随题目一起呈现

### 需要补图的题目清单（27 题）

| ID | 题干摘要 | 关键词 |
|----|---------|--------|
| 229 | 设有如下图所示的火车车轨 | 下图所示,如下图所示 |
| 337 | 无向图G有23条边 | 图G |
| 343 | 无向图G=(V,E) | 图G |
| 345 | 图的邻接矩阵A如下所示 | 如下所示 |
| 346 | 无向图G含有16条边 | 图G |
| 347 | 无向图G=(V,E) | 图G |
| 365 | 非连通无向图G | 图G |
| 369 | 如下图所示，符合深度优先遍历的序列 | 下图所示,如下图所示 |
| 371 | 有向图G的邻接表存储如下图所示 | 下图所示,如下图所示 |
| 379 | 设有向图G=(V,E) | 图G |
| 380 | 下列选项中，不是下图深度优先搜索序列的是 | 下图 |
| 388 | 下图所示有向图的所有拓扑序列共有 | 下图所示 |
| 395 | 对下图进行拓扑排序 | 下图 |
| 397 | 对下图所示的有向带权图 | 下图所示 |
| 400 | 对下图所示的有向图进行拓扑排序 | 下图所示 |
| 402 | 使用Dijkstra算法求下图中从顶点1 | 下图中,下图 |
| 405 | 下图所示的AOE网 | 下图所示 |
| 407 | 已知无向图G如下所示 | 如下所示 |
| 408 | 修改后的算法遍历有向无环图G | 图G |
| 411 | 使用Dijkstra算法求下图中从顶点1 | 下图中,下图 |
| 412 | 下图是一个有10个活动的AOE网 | 下图 |
| 451 | 在下图所示的平衡二叉树中插入关键字48 | 下图所示 |
| 457 | 已知二叉排序树如下图所示 | 下图所示,如下图所示 |
| 460 | 给定平衡二叉树如下图所示 | 下图所示,如下图所示 |
| 461 | 下图所示是一棵 (B树) | 下图所示 |
| 472 | 已知一棵3阶B树，如下图所示 | 下图所示,如下图所示 |
| 480 | 在下图所示的5阶B树T中 | 下图所示 |

> 注：当前 `source_page_start` 字段为 null，需要通过 OCR 文本内容匹配原 PDF 页码。建议开发页面映射功能时同步记录。

### 开发思路

```python
# 伪代码：从 PDF 截图题目对应区域
import fitz

doc = fitz.open("artifacts/data-structure-import/source/ds_sc.pdf")
for qi in image_dependent_questions:
    page = doc[qi.page_number - 1]
    
    # 方案 A：截取整页作为题目附图
    pix = page.get_pixmap(dpi=200)
    pix.save(f"static/question_images/q_{qi.id}.png")
    
    # 方案 B：通过 OCR bbox 定位题目区域进行裁剪
    # （适用于一页多题或需要精确区域）
    
    # 保存引用关系到 question_imports
    qi.parsed_content["images"] = qi.parsed_content.get("images", []) + [{
        "page": qi.page_number,
        "path": f"static/question_images/q_{qi.id}.png",
        "type": "full_page",
    }]
```

## 当前导入状态

| 指标 | 值 |
|------|-----|
| question_imports | 513 |
| questions | 0 |
| AUTO_PUBLISH | false |
| 自动修复（水印/截断） | 152 次 |
| 待人工审核 | 513 题 |
| 待补图 | 27 题 |

## 相关文件

- 审计报告：`artifacts/data-structure-import/reports/final-import-audit.md`
- 逐题明细：`artifacts/data-structure-import/audit/items.csv`
- 修复记录：`artifacts/data-structure-import/audit/auto-fixes.jsonl`
- 源 PDF：`artifacts/data-structure-import/source/ds_sc.pdf`
- 导入脚本：`scripts/direct_import.py`
- 状态标记：`artifacts/data-structure-import/SUCCESS`
