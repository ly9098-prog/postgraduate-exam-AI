# Production Architecture — 三层 CI Gate + 4-Layer Pipeline

> 最后更新: 2026-06-24

---

## 1. CI 三层 Gate 结构

```
┌─────────────────────────────────────────────────────────────┐
│                    CI Runner (run_pipeline_ci.py)            │
│                                                             │
│  python run_pipeline_ci.py                                  │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Tier 1: OPTIONS (options_pipeline)       36 tests  │   │
│  │  ► 必须 100% pass                                     │   │
│  │  ► failure = CI fail                                  │   │
│  │  ► pytest -m "options_pipeline"                       │   │
│  │  └─ test_options_never_dropped.py (15 defense tests)  │   │
│  │     test_question_normalizer.py (21 pipeline tests)   │   │
│  └──────────────────────────────────────────────────────┘   │
│                            │                                 │
│                            ▼                                 │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Tier 2: STRUCTURE (not ocr_deprecated)  1058 tests  │   │
│  │  ► 必须 100% pass                                     │   │
│  │  ► failure = CI fail                                  │   │
│  │  ► pytest -m "not ocr_deprecated"                     │   │
│  │  └─ 包括: splitter / normalizer / freeze / analyze    │   │
│  └──────────────────────────────────────────────────────┘   │
│                            │                                 │
│                            ▼                                 │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Tier 3: OCR (ocr_dependency)              11 tests   │   │
│  │  ► failure = allowed (ignored in gate)                 │   │
│  │  ► 仅标记 degraded                                     │   │
│  │  ► pytest -m "ocr_dependency" (xfail allowed)          │   │
│  │  └─ 已知失败: OCR service deprecation (非 pipeline bug)│
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### Gate 规则

| Tier | Marker | CI Gate | Failure 处理 |
|------|--------|---------|-------------|
| OPTIONS | `options_pipeline` | ✅ Hard gate | CI fail |
| STRUCTURE | `not ocr_deprecated` | ✅ Hard gate | CI fail |
| OCR | `ocr_dependency` | ⚠️ Degraded-OK | Logged, non-blocking |

### 运行方式

```bash
# CI 入口 (推荐)
python run_pipeline_ci.py

# 或直接 pytest
pytest -m "options_pipeline"                          # Tier 1
pytest -m "not ocr_deprecated"                        # Tier 2
pytest -m "ocr_dependency"                            # Tier 3

# 全部 (含已知 OCR 失败)
pytest
```

---

## 2. Pipeline Runtime Flow (4-Layer SSOT Architecture)

```
                                raw_blocks
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────┐
│  Layer 0: Structure Freeze Layer                         │
│  ┌────────────────────────────────────────────────────┐  │
│  │  frozen_option_registry (page→options)             │  │
│  │  当 frozen_options 存在时，跳过所有 regex 提取      │  │
│  │  保证:layout spatial data > regex extraction        │  │
│  └────────────────────────────────────────────────────┘  │
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────┐
│  Layer 1: Question Type Classifier (question_type_classifier.py)
│                                                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │  SSOT (Single Source of Truth)                     │  │
│  │                                                    │  │
│  │  detect_options_from_text(raw_text) → bool         │  │
│  │    ├─ Method 1: 标准行首 A./B./C./D.              │  │
│  │    ├─ Method 2: 行内选项 A.xxx B.xxx               │  │
│  │    ├─ Method 3: 编号选项 (1)(2)(3)(4)              │  │
│  │    ├─ Method 4: 圈号 ①②③④                       │  │
│  │    ├─ Method 5: 显式关键词                          │  │
│  │    ├─ Method 6: 断裂 OCR 容错                      │  │
│  │    └─ Method 7: 宽格式 A  xxx                      │  │
│  │                                                    │  │
│  │  extract_options_from_text(raw_text) → {key:text}  │  │
│  │    ├─ Method 1: 逐行 A. xxx                       │  │
│  │    ├─ Method 2: 圈号 ①. xxx → A                   │  │
│  │    ├─ Method 3: 宽格式 A  xxx                     │  │
│  │    └─ Method 4: 行内 A.xxx B.xxx                  │  │
│  │                                                    │  │
│  │  classify() → {has_options, reason, confidence}     │  │
│  │    ├─ Priority 1: is_frozen → has_options=True     │  │
│  │    ├─ Priority 2: detect_options → True            │  │
│  │    ├─ Priority 3: splitter content → True          │  │
│  │    └─ Priority 4: default → False                  │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  ★ ★ ★ ★  SSOT 位置  ★ ★ ★ ★                            │
│  detect_options_from_text 和 extract_options_from_text    │
│  是 pipeline 中唯一的选项检测/提取入口。                   │
│  所有 fallback (splitter / normalizer) 必须委托到此。      │
└──────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────┐
│  Layer 2: Question Splitter (question_splitter.py)       │
│                                                          │
│  职责: 切分题号 + 识别选项边界                             │
│  - 题号检测: 7种正则模式                                  │
│  - 选项提取: 委托 SSOT (extract_options_from_text)        │
│  - 行续接: 选项内容跨行拼接 (splitter 专属)                │
│  - OCR 容错: 8→B, 6→B, 0→D, Ｏ→D                       │
│  - 双栏合并检测 + 跨页恢复                                │
│  - 输出 option_lines + has_options                       │
│                                                          │
│  ❌ 不允许: 在 splitter 内复制 SSOT 检测逻辑              │
└──────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────┐
│  Layer 3: Question Normalizer (question_normalizer.py)   │
│                                                          │
│  职责: 标准化 + 类型推断 + 选项引擎                        │
│  - 调用 classify() → has_options gate                    │
│  - options 来源 (优先级):                                 │
│    ① blank_option_groups → 空 (多空选择题)                │
│    ② option_lines → 直接使用 splitter 结果                │
│    ③ SSOT fallback → extract_options_from_text()         │
│  - question_type 推断                                    │
│    ① 多空选择 → multi_blank_choice                       │
│    ② 有选项 → single_choice (classifier 可覆盖)           │
│    ③ 无选项 → subjective                                 │
│  - 标准化: stem / options / answer / explanation          │
│                                                          │
│  ❌ 不允许: 重新引入 fallback extraction 分支             │
└──────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────┐
│  Post-Stage: OPTIONS ENFORCEMENT (pipeline_orchestrator)  │
│                                                          │
│  detect_options_from_text(raw_text) == True 但 options    │
│  为空时 → 发出 [OPTIONS-ENFORCE] 警告 + risk_flags        │
│                                                          │
│  这是最后的防御线 (不修复/不注入, 仅告警)                  │
└──────────────────────────────────────────────────────────┘
                                    │
                                    ▼
                           normalized_questions
```

---

## 3. SSOT 位置与引用关系

```
question_type_classifier.py           ← SSOT (唯一真相源)
  ├── detect_options_from_text()       ← 检测, 7 种模式
  └── extract_options_from_text()      ← 提取, 4 种方法
         ▲                    ▲
         │                    │
         │                    └──────────┐
         │                               │
  question_splitter.py          question_normalizer.py
  └── _extract_options()        └── _extract_fallback_options()
       委托 SSOT 宽模式提取             直接委托 SSOT
  └── scan_entire_block()               
       委托 SSOT 全文扫描       
```

### 不变式 (Invariant)

```python
detect_options_from_text(raw_text) == True
⇒ extract_options_from_text(raw_text) != {}
```

违反 → pipeline bug → `[OPTIONS-ENFORCE]` 告警触发。

---

## 4. OCR Degraded Dependency

```
┌──────────────────────────────────────────────┐
│           OCR 服务 (PaddleOCR)                │
│                                              │
│  已废弃 (deprecated)                          │
│  - 11 个已知测试失败                          │
│  - 不影响 options/structure pipeline          │
│  - 不影响核心刷题流程                          │
│                                              │
│  标记: pytest.mark.ocr_deprecated             │
│        pytest.mark.ocr_dependency             │
│                                              │
│  CI 行为:                                    │
│  - ocr_dependency gateway: DEGRADED-OK       │
│  - 不阻塞 CI                                  │
│  - 仅记录 degraded 状态                       │
└──────────────────────────────────────────────┘
```

### 隔离机制

1. **pytest marker 隔离**: `ocr_deprecated` + `ocr_dependency`
2. **CI runner 三层 Gate**: OCR tier failure = allowed
3. **pytest.ini**: `addopts = -v --tb=short` (默认不跳过, 但 CI gate 不依赖)
4. **运行时隔离**: `OCR_ENABLED=false` 可完全禁用 OCR 服务 (不影响刷题)

---

## 5. 系统最终状态

| 维度 | 状态 | 说明 |
|------|------|------|
| Options Pipeline | 🟢 Production Ready | 36 项防御测试全部通过, 不变式验证通过 |
| Structure Pipeline | 🟢 Production Ready | 1058 项测试全部通过 |
| OCR Service | 🔴 Deprecated | 11 项失败, 被隔离, 不影响核心流程 |
| CI Gate | 🟢 Operational | 三层结构: OPTIONS(硬) / STRUCTURE(硬) / OCR(退化允许) |
| SSOT | 🟢 Clean | 所有 fallback 正确委托, 无重复检测分支 |

---

## 相关链接

- [[docs/architecture/SYSTEM_ARCHITECTURE.md|SYSTEM_ARCHITECTURE]] — 系统架构
- [[docs/architecture/API_ROUTER_STRUCTURE.md|API_ROUTER_STRUCTURE]] — 路由结构
- [[docs/project/PROJECT_RULES.md|PROJECT_RULES]] — 长期项目规则
- [[docs/project/DEPLOY_PLAN.md|DEPLOY_PLAN]] — 部署与运维
- [[docs/project/DEPLOY_CHANGELOG.md|DEPLOY_CHANGELOG]] — 生产发布与部署变更记录
- [[docs/project/DEPLOY_BUGS_HISTORY.md|DEPLOY_BUGS_HISTORY]] — 部署问题与修复记录
- [[docs/architecture/REDIS_USAGE.md|REDIS_USAGE]] — Redis 使用边界
