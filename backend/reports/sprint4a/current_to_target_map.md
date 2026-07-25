# 当前架构到目标架构映射

生成时间: 2026-07-18

分析覆盖: 184 个源文件

## 映射概要

| 目标组件 | 状态 | 当前实现文件 | 改造风险 |
|---------|------|------------|---------|
| AdapterRegistry | ✅ 已存在 | `app/features/ocr_adapter.py` | 低 |
| AdapterSelector | ✅ 已存在 | `app/features/ocr_adapter.py` | 低 |
| AssetOutbox | ✅ 已存在 | `app/services/asset_reference_service.py`, `app/services/storage_backend.py` | 低 |
| ControlPlaneFacade | ✅ 已存在 | `app/features/ocr_canary.py`, `app/features/pipeline_fingerprint.py`, `app/features/pipeline_orchestrator.py` | 低 |
| CorrectionCoordinator | ✅ 已存在 | `app/features/ai_repair.py`, `app/features/code_detector.py`, `app/features/code_integrity.py`, `app/features/code_structure_reconstructor.py`, `app/features/layout_reconstruction.py` 等 7 个文件 | 低 |
| DocumentIR | ✅ 已存在 | `app/core/document_ir.py` | 低 |
| DocumentValidator | ✅ 已存在 | `app/features/ai_validation.py`, `app/features/batch_validation.py` | 低 |
| DomainParsingCoordinator | ✅ 已存在 | `app/features/answer_matcher.py`, `app/features/cross_page_linking.py`, `app/features/exercise_region_detector.py`, `app/features/question_normalizer.py`, `app/features/question_numbering.py` 等 7 个文件 | 低 |
| InputGateway | ✅ 已存在 | `app/features/ocr_service.py`, `app/core/ocr_request.py`, `app/services/import_pipeline_service.py`, `app/services/ocr_service.py` | 低 |
| InputSafetyValidator | ✅ 已存在 | `app/features/resource_guard.py`, `app/core/admin_security.py`, `app/core/resource_guard.py`, `app/core/security.py`, `app/services/upload_validator.py` | 低 |
| NativeTextProbe | ✅ 已存在 | `app/features/page_classifier.py`, `app/services/pdf_text_normalizer.py` | 低 |
| OCRGateway | ✅ 已存在 | `app/features/ocr_adapter.py`, `app/features/ocr_mode.py`, `app/features/ocr_service.py`, `app/services/ocr_service.py` | 低 |
| PageRenderer | ✅ 已存在 | `app/services/pdf_renderer_service.py`, `app/services/visual_region_cropper.py` | 低 |
| PageStream | ✅ 已存在 | `app/features/pipeline_artifacts.py`, `app/features/pipeline_checkpoint.py`, `app/ocr_worker/workspace.py` | 低 |
| PipelineExecutionContext | ✅ 已存在 | `app/features/pipeline_fingerprint.py`, `app/core/config.py`, `app/core/logging_config.py`, `app/core/ocr_runtime_config.py`, `app/ocr_worker/config.py` | 低 |
| ReadingOrderCoordinator | ✅ 已存在 | `app/features/reading_order.py` | 低 |
| ReviewArtifactBuilder | ✅ 已存在 | `app/features/pipeline_artifacts.py`, `app/features/review_service.py`, `app/services/question_review_service.py` | 低 |
| TransactionalPersistenceCoordinator | ✅ 已存在 | `app/features/batch_image_import_service.py`, `app/features/question_import_writer.py`, `app/services/admin_import_service.py`, `app/services/import_pipeline_service.py`, `app/services/import_service.py` | 低 |
| UnifiedSafetyEvaluator | ✅ 已存在 | `app/features/ai_safety.py`, `app/features/candidate_evaluator.py`, `app/features/ocr_quality_gate.py`, `app/features/quality_gate.py` | 低 |

## 架构差距分析

| 组件 | 严重程度 | 类型 | 详情 |
|------|---------|------|------|
| NativeTextProbe | LOW | mode_switch_needed | Needs NATIVE_TEXT_ROUTING_MODE env var with modes ['off', 'shadow'] |
| OCRGateway | LOW | mode_switch_needed | Needs OCR_GATEWAY_MODE env var with modes ['legacy', 'shadow', 'gateway'] |
| DomainParsingCoordinator | MEDIUM | scattered_implementation | Capability spread across 7 files, needs Coordinator facade |
| CorrectionCoordinator | MEDIUM | scattered_implementation | Capability spread across 7 files, needs Coordinator facade |
| UnifiedSafetyEvaluator | LOW | mode_switch_needed | Needs UNIFIED_SAFETY_MODE env var with modes ['off', 'shadow'] |