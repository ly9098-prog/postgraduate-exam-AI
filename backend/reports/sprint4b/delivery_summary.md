# Sprint 4B — 双环境 OCR 生产化交付总结

生成日期: 2026-07-18

---

## 交付状态总览

| 指标 | 结果 |
|------|------|
| Sprint 4B 测试 | **75 passed**, 6 skipped |
| Sprint 4A 回归 | **189 passed** |
| 全量测试 | **264 passed**, 6 skipped |
| Smoke Test | **13/13** |
| 架构审计 | all 18 target components exist |
| 新增同步实现 | **0** |

---

## 核心交付物

### 1. 双环境目标架构图

```
PipelineExecutionContext
  ├── deployment_profile: str
  ├── runtime_capabilities: dict
  └── feature_flags: dict

ControlPlane → CoordinatorPipeline
  ├── InputCoordinator       (Stage 1)
  ├── PageStream             (Stage 2, profile-aware)
  ├── OCRCoordinator         (Stage 3, via OCRGateway)
  ├── DocumentStructureCoordinator (Stage 4)
  ├── DomainParsingCoordinator     (Stage 5)
  ├── CorrectionCoordinator        (Stage 6)
  ├── ValidationCoordinator        (Stage 7)
  ├── ReviewCoordinator            (Stage 8)
  └── PersistenceCoordinator       (Stage 9, profile-aware)
```

### 2. local_import Profile 能力清单

- [x] 完整 PaddleOCR Pipeline（GPU + CPU fallback）
- [x] Batch 题库导入
- [x] 数据库同步（复用现有 sync 入口）
- [x] PageStream window=3, overlap=1
- [x] 本地题库写入（复用现有 question_import_writer）
- [x] 所有 8 个 Coordinator

### 3. cloud_api Profile 能力清单

- [x] 轻量外部 OCR API（无本地 PaddleOCR）
- [x] Input Safety
- [x] PageStream window=1, overlap=0
- [x] DocumentIR 转换
- [x] Review Artifact
- [x] 必要的任务状态和诊断
- [ ] 无本地模型
- [ ] 无 GPU 初始化
- [ ] 无 batch 导入
- [ ] 无数据库同步

### 4-5. 禁止能力清单

| 禁止项 | local_import | cloud_api |
|--------|-------------|-----------|
| 无 PaddleOCR 加载 | ❌ | ✅ 禁止 |
| 无 CUDA 初始化 | ❌ | ✅ 禁止 |
| 无 GPU 运行时 | ❌ | ✅ 禁止 |
| 无 batch 导入 | ❌ | ✅ 禁止 |
| 无数据库同步 | ❌ | ✅ 禁止 |
| 无本地 model fallback | ❌ | ✅ 禁止 |

### 6. DeploymentProfile 实现位置

`app/core/deployment_profile.py` — `DeploymentProfile` enum, `detect_deployment_profile()`, `validate_profile_flags()`

### 7. RuntimeCapabilities 结构

`app/features/runtime_capabilities.py` — Frozen dataclass with 17 fields:
- profile, cpu_count, memory_limit_bytes, gpu_available, gpu_memory_bytes
- local_ocr_allowed, remote_ocr_allowed, batch_import_allowed, database_sync_allowed
- max_concurrent_documents, max_concurrent_pages
- page_stream_window_size, page_stream_overlap
- gpu_ocr_batch_size, gpu_memory_budget_bytes
- max_rendered_page_cache, max_remote_ocr_calls_per_document

### 8. Profile 在 Resume 中的冻结结果

✅ `PipelineExecutionContext.deployment_profile` 和 `runtime_capabilities` 通过 `to_dict()` / `from_dict()` 完整序列化和恢复

### 9-10. 云端启动依赖审计结果

| 检查项 | 结果 |
|--------|------|
| 云端加载 PaddleOCR | **否** — 0 个顶层导入违规 |
| 云端初始化 CUDA | **否** — 0 个顶层导入违规 |
| PaddleOCR 导入位置 | 函数级 lazy import（`ocr_service.py:118`、`ocr_worker/executor.py:213`）|

### 11. 本地 OCR Adapter 注册方式

`OCRGateway._register_profile_backends()` — `local_import` 时注册 `PaddleOCRLocalAdapter`

### 12. 远程轻量 OCR Adapter 注册方式

`OCRGateway._register_remote_adapter()` — 注册 `PaddleOCRVLDocumentAdapter`（两个 Profile 共享）

### 13-14. AdapterSelector 的 Profile 路由规则

- **local_import** fallback chain: `paddleocr → paddleocr-vl → rule_fallback → review`
- **cloud_api** fallback chain: `paddleocr-vl → review`（禁止 paddleocr 和 rule_fallback）

### 15. 云端 OCR 失败策略

```
REMOTE_LIGHTWEIGHT → RETRY → FAIL（禁止 fallback 到本地 OCR）
```

### 16. 云端是否存在本地 OCR fallback

**❌ 不存在** — `OCRGateway._get_forbidden_fallback()` 返回 `["paddleocr", "rule_fallback"]` 被 `_enforce_fallback_policy()` 强制过滤

### 17. OCR Gateway Shadow 调用次数

Shadow 模式返回 route decision，不调用真实 OCR 后端（复用 Sprint 4A 实现）

### 18. 外部 OCR API 保障

- 统一 120s 超时
- 有限重试（fallback chain）
- CircuitBreaker（复用现有 AdapterSelector 实现）

### 19-21. 本地模型初始化与 GPU 显存

| 项目 | 状态 |
|------|------|
| 本地模型初始化次数 | **未测试** — 需要 RTX 3050 Ti 真实环境 |
| 本地 GPU 显存峰值 | **未测试** — 需要真实 GPU |
| CUDA OOM 故障注入 | **未测试** — 需要 GPU 环境 |

GPU 测试已创建但标记为 `skip(reason="environment_not_available: needs RTX 3050 Ti 4 GB GPU")`

### 22. PageStream 本地配置

- window_size=3, overlap=1（默认）
- GPU batch_size=1, memory_budget=3200 MB

### 23. PageStream 云端配置

- window_size=1, overlap=0
- max_rendered_page_cache=1
- 逐页渲染，原子落盘，立即释放

### 24-27. 2C/2G 生产环境测试

| 指标 | 状态 |
|------|------|
| 启动内存 | **未测试** — 需要真实 2C/2G 容器 |
| 单请求峰值内存 | **未测试** — 需要生产环境 |
| 连续请求内存回收 | **未测试** — 需要生产环境 |
| 云端并发限制验证 | ✅ `ResourceGuard` 限制 max_concurrent_documents=1, max_concurrent_pages=1 |

ResourceGuard 已实现，实际内存指标需在生产环境测量。

### 28. Orchestrator 双 Profile 调用路径

✅ `CoordinatorPipeline` 支持双 Profile，通过 `profile` 属性路由：
- `run_persistence_stage()` — cloud_api 跳过重型持久化
- `run_ocr_stage()` — 由 OCRGateway profile 路由决定

### 29-31. DocumentIR 双环境 schema

✅ 两个 Profile 共享同一 DocumentIR 和 ModuleResult schema
✅ `document_ir_to_blocks()` 兼容视图可用
✅ DocumentIR SSOT 审计结果：已有 13 个 legacy call sites（在 pipeline_orchestrator.py 中）

### 32-35. 数据库同步边界

| 项目 | 结果 |
|------|------|
| 本地题库写入复用 | ✅ Coordinators 继续调用现有写入入口 |
| 现有同步入口 | `POST /api/v1/sync/import` → `merge_sync_package()` |
| 同步兼容 | ✅ sync_uuid 主键匹配，字段兼容 |
| 新增同步实现 | **0** |

### 36-37. 同步路径验证

- `new_sync_implementations = 0` ✅
- 无重复同步路径 ✅
- 无 SyncCoordinator 类 ✅

### 38. Review Artifact 双 Profile 字段

`PipelineExecutionContext.to_dict()` 包含：
- `deployment_profile`
- `runtime_capabilities`（完整结构）
- `feature_flags`
- `pipeline_fingerprint`

### 39. Feature Flag 矩阵

| Flag | local_import | cloud_api |
|------|-------------|-----------|
| DEPLOYMENT_PROFILE | local_import | cloud_api |
| CONTROL_PLANE_MODE | facade | facade |
| NATIVE_TEXT_ROUTING_MODE | shadow | shadow |
| PAGE_STREAM_MODE | stream | stream |
| OCR_GATEWAY_MODE | shadow | shadow |
| DOCUMENT_IR_SSOT_MODE | dual | dual |
| UNIFIED_SAFETY_MODE | shadow | shadow |
| PERSISTENCE_MODE | legacy | legacy |

### 40. 测试命令结果

```bash
pytest: 264 passed, 6 skipped (GPU tests)
smoke: 13/13
bench: already validated
architecture audit: clean
deployment profile audit: clean
cloud dependency audit: 0 violations
database sync audit: 0 new implementations
```

### 41. 未执行的真实环境测试

| 测试 | 原因 |
|------|------|
| GPU 模型初始化测试 | 需要 RTX 3050 Ti 4 GB 环境 |
| CUDA OOM fallback 测试 | 需要 GPU + OOM 注入 |
| GPU 显存峰值测试 | 需要真实 GPU |
| 2C/2G 启动内存 | 需要受限容器或生产服务器 |
| 2C/2G 请求峰值内存 | 需要受限容器 |
| 外部 OCR API 沙箱测试 | 需要真实 API Key |

所有不可执行测试已明确标记 `environment_not_available`，不使用 Mock 伪造结果。

### 42. 云端 Profile 正式启用条件

❌ **尚不具备** — 需要完成：
- 2C/2G 内存基线实测
- 外部 OCR API 沙箱 E2E 测试
- 生产启动验证（无 PaddleOCR 加载确认）
- DEPLOYMENT_PROFILE=cloud_api CI 测试

### 43. 本地 OCR Gateway 切换条件

❌ 当前保持 `OCR_GATEWAY_MODE=shadow`。需要：
- PaddleOCRLocalAdapter 在 local_import profile 中正式注册
- Gateway 模式 E2E 测试通过
- 旧 legacy 路径验证等价后切换

### 44. 下一阶段建议

1. **2C/2G 生产基线测试** — 启动受限容器测量内存基线
2. **外部 OCR API 沙箱集成** — 真实认证和 timeout 测试
3. **Coordinator 深度集成** — 将 CoordinatorPipeline 完全接入实际 pipeline flow
4. **GPU 环境测试** — 在 3050 Ti 上运行模型 singleton 和 OOM 测试
5. **Sprint 4A→4B 过渡** — 将 CONTROL_PLANE_MODE 验证为正式，移除 legacy paths

---

## 新增文件清单

### 核心文件
| 文件 | 用途 |
|------|------|
| `app/core/deployment_profile.py` | DeploymentProfile enum + detect + validate |
| `app/features/runtime_capabilities.py` | RuntimeCapabilities frozen dataclass + factory |
| `app/features/resource_guard.py` | 2C/2G resource protection |
| `app/features/coordinator_orchestrator.py` | CoordinatorPipeline integration layer |

### 扩展文件
| 文件 | 变更 |
|------|------|
| `app/features/control_plane.py` | +deployment_profile, +runtime_capabilities 到 PipelineExecutionContext |
| `app/features/ocr_gateway.py` | +profile 参数, +profile-aware route, fallback policy enforcement |
| `app/features/page_stream.py` | +for_profile() classmethod |
| `app/core/config.py` | +DEPLOYMENT_PROFILE setting |

### 审计脚本
| 文件 | 用途 |
|------|------|
| `scripts/audit_deployment_profiles.py` | Profile 映射审计 |
| `scripts/audit_cloud_runtime_dependencies.py` | 云端依赖隔离审计 |
| `scripts/audit_local_import_path.py` | 本地/云端调用图生成 |
| `scripts/audit_database_sync_boundary.py` | 数据库同步边界审计 |
| `scripts/audit_production_readiness_baseline.py` | 生产就绪基线文档 |

### 审计报告
`reports/sprint4b/` — 6 个 JSON + 2 个 Markdown 审计输出

### 测试文件（26 个 Sprint 4B 文件, 75 个测试）
| 文件 | 测试数 |
|------|--------|
| `tests/test_deployment_profile.py` | 9 |
| `tests/test_runtime_capabilities.py` | 7 |
| `tests/test_profile_frozen_on_resume.py` | 4 |
| `tests/test_cloud_profile_no_paddle_import.py` | 2 |
| `tests/test_cloud_profile_no_cuda_initialization.py` | 2 |
| `tests/test_cloud_resource_guard.py` | 9 |
| `tests/test_cloud_profile_registry.py` | 1 |
| `tests/test_local_profile_registry.py` | 1 |
| `tests/test_profile_capability_enforcement.py` | 7 |
| `tests/test_ocr_adapter_lazy_loading.py` | 1 |
| `tests/test_ocr_gateway_profile_routes.py` | 5 |
| `tests/test_cloud_ocr_no_local_fallback.py` | 3 |
| `tests/test_page_stream_profile_config.py` | 5 |
| `tests/test_orchestrator_profile_integration.py` | 6 |
| `tests/test_no_duplicate_database_sync.py` | 2 |
| `tests/test_invalid_profile_flag_combinations.py` | 3 |
| `tests/test_database_sync_compatibility.py` | 3 |
| `tests/test_review_artifact_deployment_profile.py` | 3 |
| `tests/test_local_remote_document_ir_schema.py` | 3 |
| `tests/test_local_ocr_model_singleton.py` | 3 (skipped) |
| `tests/test_gpu_oom_fallback_policy.py` | 3 (skipped) |
