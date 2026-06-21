# OCR 导题验收测试

用真实高数 / 408 资料验证 OCR 导题效果。

## 运行

```bash
# 检查环境
python -m pytest tests/ocr_regression

# 跑验收测试（需要手动放置样本）
python tests/ocr_acceptance/run_acceptance.py --case-dir tests/ocr_acceptance/cases
```

## 样本类型

验收 case 覆盖以下场景：

| # | 类型 | 样本名 | 来源 |
|---|------|--------|------|
| 1 | 高数公式 PDF | `math_formula_pdf/` | 需手动放置 |
| 2 | 高数扫描图片 | `math_scan_image/` | 需手动放置 |
| 3 | 线代矩阵题 | `matrix_questions.` | 需手动放置 |
| 4 | 概率统计表格题 | `stat_table/` | 需手动放置 |
| 5 | 408 C 代码题 | `408_code/` | 需手动放置 |
| 6 | 408 表格题 | `408_table/` | 需手动放置 |
| 7 | 多列选项题 | `multi_column/` | 需手动放置 |
| 8 | 水印干扰题 | `watermark/` | 需手动放置 |

## 预期指标

```json
{
  "question_count_recall": 0.95,
  "option_integrity": 0.98,
  "answer_match_rate": 0.96,
  "math_image_presence": 0.90,
  "code_symbol_preservation": 0.99,
  "table_structure_presence": 0.85,
  "manual_review_rate": 0.30
}
```

## 手动放置样本

由于版权原因，真实样本不提交仓库。请将样本文件放入 `cases/` 子目录。

```text
tests/ocr_acceptance/cases/
  math_formula_pdf/         # 高数 PDF（含复杂公式）
  math_scan_image/          # 高数扫描图片
  matrix_questions/         # 线代矩阵题
  stat_table/               # 概率统计表格
  408_code/                 # 408 C 代码题
  408_table/                # 408 表格题
  multi_column/             # 多列选项题
  watermark/                # 水印干扰题
```

每个目录下至少放一个文件。验收测试会扫描这些目录，对每个文件执行 OCR 并评估结果。

## 如何理解报告

输出 `acceptance_report.json`：

```json
{
  "date": "2026-06-21T...",
  "cases": {
    "math_formula_pdf": {
      "status": "passed", "question_count": ...,
      "metrics": { ... }
    }
  },
  "summary": {
    "total_cases": 8,
    "passed": 6,
    "failed": 2
  }
}
```

## 注意事项

1. 验收测试需要 OCR_ENABLED=true
2. 验收测试会调用 PaddleOCR，耗时较长
3. 预期指标是参考值，不通过不阻止 PR
4. 实际结果取决于样本质量
