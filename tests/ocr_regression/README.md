# OCR 回归测试

## 目录结构

```
tests/ocr_regression/
  test_ocr_regression.py   — 回归测试 runner
  cases/                    — 测试 case 定义（JSON）
    math_case_001_*.json    — 高数极限-无穷小等价
    math_case_002_*.json    — 高数积分-极值拐点
    math_case_003_*.json    — 高数二重积分-交换次序
    math_case_004_*.json    — 高数无穷小-o运算
    math_case_005_*.json    — 高数隐函数-偏导数
  expected/                 — (预留) 人工标注 expected 输出
```

## 运行

```bash
# 只跑元数据校验（不依赖 PaddleOCR）
pytest tests/ocr_regression/ -v -k "metadata"

# 完整测试（需要 OCR_ENABLED=true）
OCR_ENABLED=true pytest tests/ocr_regression/ -v

# 单 case
pytest tests/ocr_regression/ -v -k "math_case_001"
```

## 新增 case

1. 将图片放入 `ocr_test/images/example/` 或 `ocr_test/images/cases/`
2. 在 `cases/` 中创建 `{case_id}.json`，参考现有 case
3. 在 `expected/` 中创建 `{case_id}_expected.json` 包含人工标注的完整结构化输出
4. 运行 `pytest tests/ocr_regression/ -v` 验证

## Case 字段说明

| 字段 | 说明 |
|------|------|
| case_id | 唯一标识 |
| source | 图片文件名 |
| source_path | 图片相对项目根目录的路径 |
| description | 题目描述 |
| subject | 科目（math2 / 408 / english 等） |
| question_type | 题型 |
| expected.stem_patterns | 题干中必须出现的关键词 |
| expected.has_math_image_segment | 是否期望 math_image segment |
| expected.has_table_markdown_segment | 是否期望 table_markdown segment |
| expected.expected_risk_flags | 期望的风险标记 |
| expected.requires_review | 是否需要人工审核 |
| expected.min_confidence | 最小期望 OCR 置信度 |
| ocr_hints | OCR 已知问题和注意事项 |
