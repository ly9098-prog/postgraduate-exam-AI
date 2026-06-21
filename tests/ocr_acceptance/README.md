# OCR 导题验收测试

用真实高数 / 408 资料验证 OCR 导题效果。

## 运行

```bash
# 轻量级回归（不依赖真实样本，CI 默认模式）
python -m pytest tests/ocr_regression

# 标准验收（需要手动放置样本）
python tests/ocr_acceptance/run_acceptance.py --case-dir tests/ocr_acceptance/cases

# 严格模式（发布前检查，通过标准更高）
python tests/ocr_acceptance/run_acceptance.py --case-dir tests/ocr_acceptance/cases --strict
```

## 三种测试模式

| 模式 | 命令 | 用途 | 需要真实样本 | CI 执行 |
|------|------|------|-------------|---------|
| 轻量级 | `pytest tests/ocr_regression` | PR/CI 默认检查 | 否 | 是 |
| 标准验收 | `run_acceptance.py` | 本地开发验收 | 是 | 否 |
| 严格模式 | `run_acceptance.py --strict` | 发布前全面检查 | 是 | 否 |

## 样本类型

验收 case 覆盖以下场景：

| # | 类型 | 样本名 | 来源 |
|---|------|--------|------|
| 1 | 高数公式 PDF | `math_formula_pdf/` | 需手动放置 |
| 2 | 高数扫描图片 | `math_scan_image/` | 需手动放置 |
| 3 | 线代矩阵题 | `matrix_questions/` | 需手动放置 |
| 4 | 概率统计表格题 | `stat_table/` | 需手动放置 |
| 5 | 408 C 代码题 | `408_code/` | 需手动放置 |
| 6 | 408 表格题（计组） | `408_table/` | 需手动放置 |
| 7 | 多列选项题 | `multi_column/` | 需手动放置 |
| 8 | 水印干扰题 | `watermark/` | 需手动放置 |
| 9 | 408 计网题 | `408_network/` | 需手动放置 |
| 10 | 408 操作系统题 | `408_os/` | 需手动放置 |

## 样本元数据

每个 case 目录包含 `case.json`，标注以下指标：

```json
{
  "case_id": "math_formula_pdf_001",
  "subject_type": "math / code / table / mixed",
  "expected_question_count": 20,
  "expected_answer_count": 20,
  "expected_math_image_count": 15,
  "expected_table_count": 0,
  "expected_code_blocks": 0,
  "known_risks": ["复杂积分上下标可能识别不全"]
}
```

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
  408_network/              # 408 计网题
  408_os/                   # 408 操作系统题
```

每个目录下至少放一个文件。验收测试会扫描这些目录，对每个文件执行 OCR 并评估结果。

## 如何理解报告

输出 `acceptance_report.json`：

```json
{
  "date": "2026-06-21T...",
  "cases": {
    "math_formula_pdf": {
      "status": "passed",
      "question_count": 18,
      "metrics": {
        "question_count_recall": { "actual": 0.90, "reference": 0.95, "passed": true }
      }
    }
  },
  "summary": {
    "total_cases": 10,
    "passed": 8,
    "failed": 2
  }
}
```

## 注意事项

1. 验收测试需要 OCR_ENABLED=true
2. 验收测试会调用 PaddleOCR，耗时较长
3. 预期指标是参考值，不通过不阻止 PR
4. 实际结果取决于样本质量
5. 缺少本地真实文件时不影响 CI（只输出 skipped）
