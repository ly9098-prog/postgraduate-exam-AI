# OCR 导入发布检查清单

## 发布前检查

### 1. 环境变量确认

```
必填:
  APP_SECRET=               # 已配置
  DATABASE_URL=             # 指向正确数据库
  AI_CONFIG_ENCRYPT_KEY=    # AI 模型凭据加密密钥
  WECHAT_APP_ID=            # 微信小程序 AppID
  WECHAT_APP_SECRET=        # 微信小程序 AppSecret

OCR 相关:
  OCR_ENABLED=true          # 开启 OCR 导入
  OCR_CACHE_DIR=            # 可选，默认 .backend_cache/ocr/
  PIPELINE_ARTIFACT_DIR=    # 可选，默认 .backend_cache/pipeline_artifacts/

可选:
  REDIS_URL=                # Redis（用于 pipeline 状态缓存）
  PDF_CHUNK_SIZE=40         # PDF 分块页数
  OCR_CACHE_ENABLED=true    # OCR 结果缓存
```

> AI 模型凭据（API Key / Base URL / model name）不使用环境变量，统一存于数据库 `admin_ai_model_configs`，经管理端 AI Settings 配置。

### 2. 运行预检查

```bash
cd /path/to/project

# 离线检查
python scripts/ocr_preflight_check.py --verbose

# 如果生产后端可访问
python scripts/ocr_preflight_check.py --api-base-url https://admin-api.example.com/api/admin/v1 --verbose
```

### 3. 运行回归测试

```bash
# 依赖 OCR 引擎的完整测试
OCR_ENABLED=true pytest tests/ocr_regression/ -v

# 仅元数据测试
pytest tests/ocr_regression/ -v -k "not ocr_and_pipeline"
```

### 4. 运行验收测试

```bash
# 需要真实样本（不在版本控制中）
python tests/ocr_acceptance/run_acceptance.py

# 严格模式
python tests/ocr_acceptance/run_acceptance.py --strict
```

### 5. 清理 Dry-Run

```bash
curl -X POST https://admin-api.example.com/api/admin/v1/imports/maintenance/cleanup \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"target": "all", "dry_run": true}'
```

确认结果合理后执行：
```bash
curl -X POST https://admin-api.example.com/api/admin/v1/imports/maintenance/cleanup \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"target": "all", "dry_run": false}'
```

### 6. 验证 unique image sources

确认 `ocr_test/images/` 中的图片有唯一来源，不存在重复或冲突文件名。

---

## 发布步骤

### 1. 代码部署

```bash
git pull origin main
# 确认代码版本
git log --oneline -3
```

### 2. 安装依赖

```bash
cd backend && pip install -r requirements.txt
```

### 3. 数据库迁移

```bash
# 如果存在数据库迁移
alembic upgrade head
```

### 4. 重启服务

```bash
# 根据部署方式
supervisorctl restart backend
# 或
systemctl restart backend.service
```

### 5. 验证部署

- 访问管理端 → 导入任务 → 上传测试文件 → 验证 pipeline 正常
- 检查 `.backend_cache/` 目录结构正确
- 检查 logs 无异常错误

---

## 发布后检查

### 功能验证
- [ ] 上传 PDF 导入 → pipeline completed
- [ ] 上传图片导入 → pipeline completed
- [ ] Excel 导入可用
- [ ] 文本导入可用
- [ ] 审核页打开正常
- [ ] 批量操作正常
- [ ] 发布题目正常

### 质量验证
- [ ] 管理端 → 运维 → 导入健康摘要有数据
- [ ] quality_report 字段完整
- [ ] performance_summary 有值
- [ ] 无异常告警

### 清理验证
- [ ] 管理端 → 运维 → Dry-Run 有结果
- [ ] 确认清理后 artifact 目录减少

---

## 回滚方案

如需回滚：

1. 代码回滚到上一版本
2. 重启服务
3. 确认清理操作（如有）不影响历史数据
4. 运行回归测试确认

---

## 日常检查频率

| 检查项 | 频率 | 方式 |
|--------|------|------|
| 导入成功率 | 每日 | 管理端运维页 |
| OCR 缓存大小 | 每周 | Cleanup Dry-Run |
| 失败样本导出 | 每次修复 | Export-Case |
| 回归测试 | 每次代码变更 | pytest |
| 发布前全量检查 | 每次发布 | preflight script |

---

## 相关链接

- [[docs/architecture/OCR_FLOW.md|OCR_FLOW]] — OCR 导入流程
- [[docs/architecture/OCR_USAGE.md|OCR_USAGE]] — OCR 使用说明
- [[docs/ocr/OPERATIONS.md|OPERATIONS]] — OCR 运维
- [[docs/ocr/TROUBLESHOOTING.md|TROUBLESHOOTING]] — OCR 排障
- [[docs/project/DEPLOY_PLAN.md|DEPLOY_PLAN]] — 部署与运维
- [[docs/project/DEPLOY_CHANGELOG.md|DEPLOY_CHANGELOG]] — 生产发布与部署变更记录
- [[docs/project/DEPLOY_BUGS_HISTORY.md|DEPLOY_BUGS_HISTORY]] — 部署问题与修复记录
