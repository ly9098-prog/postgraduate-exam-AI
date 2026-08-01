# P8：VL 代码列表题选项抽取不足（ocr_regression 023/025）

> 状态：**保持红色，留作 TODO**（2026-08-01，用户决定不标记 xfail，作为待修 OCR 质量项）
> 归属：`tests/ocr_regression/cases/023_bugs_case3_linkedlist`、`025_bugs_case5_listinsert`

## Bug 描述

`pytest tests/ocr_regression` 中两个 case 持续失败，断言为 `Option count below threshold`（expected >= 4）：

- **023_bugs_case3_linkedlist**：实际只抽出 2 个选项 `{A: 找到头结点, B: 找到尾结点}`，C/D 选项缺失。
- **025_bugs_case5_listinsert**：实际抽出 3 个选项 `{B, C, D}`，且 D 为乱码 `= xau<-s :xau<-s = jxau<-d`（是 `s->next = ...` 的镜像误读）。

## 复现步骤

前置：`postgraduate.db` 中 `admin_ai_model_configs` 存在 `PaddleOCR-VL-1.6` 且 token 有效（aistudio）。

```bash
cd backend
.venv/bin/python -m pytest "tests/ocr_regression/runner.py::test_ocr_regression[023_bugs_case3_linkedlist]" "tests/ocr_regression/runner.py::test_ocr_regression[025_bugs_case5_listinsert]" -q -rs
```

## 根因分析

- 这是**真实 VL 模型对代码列表题的识别质量限制**，不是 harness bug。
- `runner.py::run_ocr_case()` 只执行 `VL_REBUILD`（`pipeline._run_vl_rebuild_blocks`）+ `detect_options_from_text` / `extract_options_from_text`，**不含 AI repair**。
- 生产完整管线（`ImportPipeline` 含 `enable_ai_repair`）会对 <4 选项的题触发 `incomplete_options` AI repair，从 PP-OCR raw text 恢复乱码选项——因此这两个 case 的 `compare_output`（文本比对）是 **PASS** 的，只有轻量 `run_ocr_case` 门禁失败。
- 历史：commit `c34cf41e`（case 5，original_raw_text merge + AI repair incomplete_options）曾修过同类问题；`0d08dc99` 加入 021-025 全管线回归测试。

## 修复方向（候选）

1. **对齐门禁与生产行为**：让 `run_ocr_case` 走完整图片管线（VL_REBUILD + AI repair incomplete_options + 选项合并），使回归门禁反映真实生产效果——两个 case 应能真实通过。
2. **提升 VL 代码选项抽取**：从 PP-OCR raw text / VL 文本做选项补全与去镜像（`xau<-s` → `s->next`），提高选项召回。
3. 若短期不修：保持红色，不要标记 xfail（用户明确决定），作为 OCR 质量 TODO 跟踪。

## 回归检查

- [ ] `pytest tests/ocr_regression -q` 全绿（021/022/024 已通过，须保持）
- [ ] 修复后 023/025 选项数 >= 4
- [ ] 生产完整管线文本比对不受影响（compare_output 持续 PASS）
- [ ] 相关功能（选项抽取、AI repair、VL_REBUILD）未受影响
