# OCR识别异常

## ✅ 已修复汇总（2026-07-08）

本轮修复已全面处理以下 5 个案例 + 5 个系统性架构问题（P0-P1），
详见下方各案例标记和文末修复总结。

| 案例 | 状态 | 回归测试 | 涉及文件 |
|------|------|----------|----------|
| Case 1 (false_3): 栈题横排选项 | ✅ 已修复 | `test_bugs_stack_and_code_cases::TestCase1_*` | `question_splitter.py`, `question_normalizer.py` |
| Case 2 (false_4): 题干选项粘连 | ✅ 已修复 | `TestCase2_*` | `question_normalizer.py` (inline stripping) |
| Case 3 (false_5): 下标误改写 | ✅ 已修复 | `TestSubscriptSafetyGate::test_detect_subscript_change_*` | `ai_repair.py` (safety gate) |
| Case 4 (false_1): 代码误切选项 | ✅ 已修复 | `TestCase4_*` | `question_splitter.py` (code quarantine) |
| Case 5 (ocr_code_test_2): 结构体+遍历序列 | ✅ 已修复 | `TestLogReplayOcrCodeTest2::*`, `TestCase5_*` | `code_integrity.py`, `answer_matcher.py`, `question_splitter.py` |

### 系统性修复

| 问题 | 状态 | 回归测试 |
|------|------|----------|
| P0.1 显式答案提取 | ✅ 已修复 | `TestExplicitAnswerExtraction::*` |
| P0.2 Frozen option stem 剥离 | ✅ 已修复 | `TestFrozenOptionsStripping::*` |
| P0.3 质量状态单调性 | ✅ 已修复 | `TestQualityStatus::*` |
| P0.4 乱码代码检测增强 | ✅ 已修复 | `TestGarbledCodeDetection::*` |
| P0.5 Review 保留 risk_flags | ✅ 已修复 | — |
| P1.1 代码隔离 | ✅ 已修复 | `TestCase4_*::test_code_quarantine_*` |
| P1.2 横排选项 + inline stripping | ✅ 已修复 | `TestCase1_*`, `TestCase2_*` |
| P1.3 数学下标安全门禁 | ✅ 已修复 | `TestSubscriptSafetyGate::*` |

---

## 本轮根据原图补充的修复目标

- 补全各案例的“原题”空块，记录图片可见的正确题干、选项与答案。
- 明确四类 OCR/AI 修复异常：数学下标丢失、横排选项截断、题干与选项粘连、代码片段被误切成选项。
- 新增二叉树遍历题作为“结构体代码块 + 遍历字符串 + 答案区”混合场景回归样例。
- 后续验收时，客观题应同时校验 `stem/options/answer/analysis`，不能只判定 `is_valid=true`。

## 案例语料索引（2026-11-08 拆分）

六个案例的完整语料（原题、期望解析、异常点、OCR 原文、导入后审核态、修复中间结果与验收用例）
已于 2026-11-08 移至 [[docs/ocr/OCR_FIX_CASES.md|OCR_FIX_CASES]]（`docs/ocr/`），本文件保留状态汇总。
案例编号与下方表格一致；运行时行为以 `backend/tests/` 回归测试与当前代码为准。

| 案例 | 场景 | 核心修复 | 语料 |
|------|------|----------|------|
| 案例一 (false_3) | 栈题横排选项截断 | 横排选项切分增强 + inline stripping | `docs/ocr/OCR_FIX_CASES.md` 案例一 |
| 案例二 (false_4) | 题干选项粘连 | inline option stem stripping | `docs/ocr/OCR_FIX_CASES.md` 案例二 |
| 案例三 (false_5) | 数学下标误改写 | AI repair 安全门禁 | `docs/ocr/OCR_FIX_CASES.md` 案例三 |
| 案例四 (false_1) | 代码片段误切为选项 | splitter 代码隔离 | `docs/ocr/OCR_FIX_CASES.md` 案例四 |
| 案例五 (ocr_code_test_2 前身批次) | 结构体+遍历序列混合 | code_integrity / answer_matcher | `docs/ocr/OCR_FIX_CASES.md` 案例五 |
| 案例六 (ocr_code_test_2) | 结构体代码块+二叉树遍历 | 代码块保护 + 连续字母串保护 + 答案区提取 | `docs/ocr/OCR_FIX_CASES.md` 案例六 |

> 与 [[docs/project/BUGS_HISTORY.md|BUGS_HISTORY]] 的分工：本文件记录 OCR 修复案例的状态汇总与
> 语料索引；BUGS_HISTORY 收录跨模块的结构化缺陷条目（现象/根因/处理/验证）。新缺陷按 BUGS_HISTORY
> 的条目格式登记，OCR 回归语料按本文件 → `docs/ocr/OCR_FIX_CASES.md` 的归属沉淀。

## 相关链接

- [[docs/project/PROJECT_RULES.md|PROJECT_RULES]] — 长期项目规则
- [[docs/project/ROADMAP.md|ROADMAP]] — 现行范围
- [[docs/project/CHANGELOG.md|CHANGELOG]] — 项目变更记录
- [[docs/project/DEPLOY_PLAN.md|DEPLOY_PLAN]] — 部署与运维
- [[docs/project/DEPLOY_CHANGELOG.md|DEPLOY_CHANGELOG]] — 生产发布与部署变更记录
- [[docs/project/DEPLOY_BUGS_HISTORY.md|DEPLOY_BUGS_HISTORY]] — 部署问题与修复记录
- [[docs/project/BUGS_HISTORY.md|BUGS_HISTORY]] — 缺陷历史归档
