# 测试已知问题与修复记录

本文档记录项目中已修复的测试问题、已知的环境依赖，以及排查思路。

---

## 1. Admin 403 权限测试批量失败（21 个用例）

### 现象

`test_api/test_admin_rbac.py`、`test_admin_app_users.py`、`test_admin_questions.py`、`test_admin_subjects.py`、`test_admin_users.py` 中共 21 个测试报 403 Forbidden。

### 根因

`tests/test_services/test_health_check.py` 在模块级别设置了 `app.dependency_overrides` 并 monkey-patch 了 `_admin_security._get_permission_names`，但没有在测试结束后清理。后续测试文件导入时，权限检查函数已被永久替换为 fake 版本，导致所有 admin API 测试的权限校验失败。

### 修复

将 `test_health_check.py` 中的模块级 setup 改为 `autouse=True` 的 pytest fixture，使用 `yield` + 清理逻辑恢复原始状态：

```python
_original_get_permission_names = _admin_sec_mod._get_permission_names

@pytest.fixture(autouse=True)
def _isolate_api_overrides():
    _APP.dependency_overrides[_db_mod.get_db] = _fake_get_db
    _APP.dependency_overrides[_admin_sec_mod.get_current_admin] = _fake_get_current_admin
    _admin_sec_mod._get_permission_names = _fake_get_permission_names
    yield
    _APP.dependency_overrides.pop(_db_mod.get_db, None)
    _APP.dependency_overrides.pop(_admin_sec_mod.get_current_admin, None)
    _admin_sec_mod._get_permission_names = _original_get_permission_names
```

### 教训

- 模块级 monkey-patch 会污染整个进程生命周期
- `dependency_overrides` 必须在 fixture teardown 中清理
- 测试隔离问题通常在跨文件运行时才暴露

---

## 2. OCR 服务测试失败（2 个用例）

### 现象

- `test_ocr_pages_with_boxes_propagates_dependency_error`：期望空结果，但实际抛出 `RuntimeError`
- `test_ocr_pages_converts_page_exception_to_empty_text`：paddleocr 未安装时 `_get_ocr()` 直接失败

### 根因

- 第一个测试的断言与实际行为不匹配：`ocr_pages()` 在 OCR 不可用时抛出 `RuntimeError`，而非返回空结果
- 第二个测试没有绕过 `_get_ocr()` 的可用性检查，导致在 patch `_ocr_one_page` 之前就已经失败

### 修复

- 第一个测试：改为 `pytest.raises(RuntimeError, match="OCR 依赖未安装")`
- 第二个测试：增加 `patch.object(ocr_service, "ocr_is_available", return_value=True)` 绕过初始化检查

---

## 3. 批量导入幂等性测试失败（2 个用例）

### 现象

- `test_find_job_by_request_id_returns_existing`：查询 `request_id` 找不到记录
- 对应的幂等性提交测试：重复提交未返回已有 job

### 根因

`create_batch_job` 在创建 `ImportBatchJob` 时没有将 `request_id` 参数赋值到模型实例上，导致 `_find_job_by_request_id` 按 `request_id` 查询时找不到任何记录。

### 修复

在 `batch_image_import_service.py` 的 `create_batch_job` 中，创建 `ImportBatchJob` 时增加 `request_id=request_id`。

同时修复测试中 `_make_job()` 调用，增加 `request_id="req_abc"` 参数。

---

## 4. Phase 4.5 引入的 Phase 4 测试回归（4 个用例）

### 现象

Phase 4.5 新增代码导致 Phase 4 既有测试失败：

1. `test_create_new_config` — `ValueError: strategy_type 'practice_smart' not in allowed list`
2. `test_stable_assignment` — `TypeError: '>' not supported between 'float' and 'MagicMock'`
3. `test_returns_experiment_strategy` — 同上，流量上限检查失败
4. `test_aggregate_basic` — `ImportError: cannot import name 'timedeltatime'`

### 根因与修复

| # | 根因 | 修复 |
|---|------|------|
| 1 | `validate_strategy_config` 将 `scene` 回退为 `strategy_type` 进行校验 | 移除回退逻辑，仅校验显式提供的 `strategy_type` |
| 2-3 | `getattr(mock, "max_traffic_percent", 100.0)` 对 MagicMock 返回新 MagicMock 而非默认值 | 增加 `isinstance(raw, (int, float))` 检查 |
| 4 | 编辑操作将 `from datetime import datetime, timedelta` 误改为 `from datetime import date, timedeltatime, timedelta` | 修正为 `from datetime import datetime, timedelta` |

---

## 5. 测试隔离最佳实践

为避免类似的跨测试污染问题，建议遵循以下规范：

1. **禁止模块级 monkey-patch**：所有 `_module._function = fake` 必须在 fixture 的 `yield` 后恢复
2. **禁止模块级 `dependency_overrides`**：必须在 fixture teardown 中 `pop` 清理
3. **MagicMock 属性默认值**：使用 `isinstance` 检查而非 `getattr(obj, attr, default)`，因为 MagicMock 会自动创建属性
4. **可选依赖测试**：使用 `patch.object(module, "is_available", return_value=True/False)` 控制依赖可用性
5. **测试文件间独立性**：每个测试文件应可独立运行，不依赖其他文件的副作用

---

## 6. get_publish_history ImportError（Phase 4.7 记录 → Phase 5.0 已修复）

### 状态：已修复 ✅

Phase 5.0 中实现了 `get_publish_history` 函数，ImportError 已消除。
`test_question_publish_service.py` 可重新纳入常规测试范围，不再需要 `--ignore`。

### 实现摘要

- **函数位置**：`app/features/question_publish_service.py`
- **函数签名**：`async def get_publish_history(db, page=1, page_size=20) -> PublishHistoryResponse`
- **数据来源**：从 `question_imports` 表按 `batch_id` 聚合统计（published/duplicate/failed 计数）
- **Schema**：`PublishHistoryItem` + `PublishHistoryResponse`（`app/schemas/question_publish.py`）
- **Stage 10 后续增强**：可替换为专用 audit_log / publish_log 表，当前实现为最小兼容版本

### 原始问题记录（供参考）

`tests/test_services/test_question_publish_service.py` 在 import 阶段失败：

```
ImportError: cannot import name 'get_publish_history' from 'app.features.question_publish_service'
```

根因是 `get_publish_history` 为未完成的 Stage 10 功能，测试先行但实现被搁置。
