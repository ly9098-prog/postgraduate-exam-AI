# OCR 评测框架

评估 OCR 识别质量和下游管线处理效果的开发工具。

## 快速开始

```bash
# structure-only 模式（无需 PaddleOCR）
cd backend && PYTHONPATH=. python -m tests.ocr_eval.eval_ocr

# 作为 pytest 运行
PYTHONPATH=backend python3 -m pytest backend/tests/ocr_eval/eval_ocr.py -v

# 真实 OCR 模式（需要 PaddleOCR + 图片文件）
cd backend && PYTHONPATH=. python -m tests.ocr_eval.eval_ocr --live-ocr

# 单个样本
cd backend && PYTHONPATH=. python -m tests.ocr_eval.eval_ocr --sample 001

# JSON 输出
cd backend && PYTHONPATH=. python -m tests.ocr_eval.eval_ocr --json
```

## 目录结构

```
tests/ocr_eval/
  metrics.py          # 评测指标纯函数
  eval_ocr.py         # 评测入口脚本
  samples/
    NNN_description/
      ground_truth.txt    # 人工标注正确文本
      ocr_output.txt      # OCR 实际识别结果
      meta.json           # 样本元信息
      image.png           # (可选) 原始截图
```

## 添加新样本

1. 创建目录 `samples/NNN_short_description/`（NNN 递增编号）
2. 写入 `ground_truth.txt`：人工核对的正确文本，纯 UTF-8，每行一个逻辑行
3. 写入 `ocr_output.txt`：OCR 实际输出（从日志/BUGS.md 粘贴，或 live-ocr 模式生成）
4. 写入 `meta.json`：

```json
{
  "id": "NNN",
  "description": "简述失败现象",
  "subject": "exam408",
  "failure_type": "text_drop",
  "expected_questions": 1,
  "date_added": "YYYY-MM-DD"
}
```

`failure_type` 可选值：
- `text_drop` — 整行或多行文本丢失
- `char_substitution` — 单字替换/错字
- `option_confusion` — 选项识别混乱
- `line_merge` — 多行被错误合并
- `line_split` — 单行被错误拆分
- `ordering_error` — 阅读顺序错乱
- `clean` — 基线正确样本

5. (可选) 放入 `image.png` 用于 live-ocr 模式

## 评测指标

| 指标 | 含义 |
|------|------|
| CER | 字符错误率（越低越好） |
| Line Recall | GT 行在 OCR 输出中的召回率 |
| Line Precision | OCR 输出行在 GT 中的精确率 |
| Text Drop Rate | GT 字符完全丢失的比例 |

## 状态判定

- CER < 0.05 → PASS
- 0.05 <= CER < 0.2 → DEGRADED
- CER >= 0.2 → FAIL
