# OCR 导入故障排查手册

## Pipeline 卡住

**现象**: 导入长时间无进度更新，管理端状态停留在 processing。

**排查步骤**:
1. 查看后端日志: `grep pipeline_id logs/app.log`
2. 检查 disk space: `df -h`（磁盘满会导致 artifact 写入失败）
3. 检查系统资源: `top` / `free -h`（2C2G 服务器可能 OOM）
4. 检查 AI API 可达性（Admin 后台 → AI Settings 中配置的网关地址）

**解决方案**:
- 内存不足：减少 chunk_size（环境变量 `PDF_CHUNK_SIZE=20`）
- AI 超时：在 Admin 后台 AI Settings 中检查模型凭据（API Key / Base URL / model name，存于数据库 `admin_ai_model_configs`）
- 进程 OOM：重启后端进程

---

## OCR 质量差

**现象**: 识别文本乱码、大量字符错误、题号丢失。

**排查步骤**:
1. 检查源文件格式：扫描版 PDF？图片不清晰？分辨率 < 200 DPI？
2. 检查 OCR 缓存：`.backend_cache/ocr/` 是否过大？清理缓存后重试
3. 对比不同格式：同文件用 PNG vs PDF 分别导入
4. 查看 diagnostics 中的 OCR 失败页面列表

**常见原因**:
- PDF 为纯扫描版（需用图片模式处理）
- 页面含有复杂水印遮挡文字
- 源文件为照片翻拍（存在透视变形）
- OCR 引擎对特定字体识别率低

---

## 人工审核率过高

**现象**: estimated_manual_check_rate > 50%，大量题目需要人工审核。

**排查步骤**:
1. 检查 risk_flags 分布: diagnostics.risk_flag_counts
2. 高频 flag 排查：
   - `formula_uncertain`：公式截图是否正常？
   - `options_anomaly`：选项提取是否错位？
   - `answer_missing`：答案区域是否被截断？
   - `watermark_noise`：水印是否混入题目正文？
3. 检查 text_normalizer 水印规则是否需要更新
4. 检查 code_detector 是否误报（中文题干中出现编程关键词）

---

## AI Repair 失败

**现象**: pipeline repair 阶段报错，导入失败。

**排查步骤**:
1. 检查 token budget: `diagnostics.token_usage`
2. 检查模型配置: 管理端 → AI Settings（凭据存于数据库 `admin_ai_model_configs`，不用环境变量）
3. 查看 repair_stats: `diagnostics.stage_diffs.ai_repair_stats`

**临时解决方案**:
- 关闭 AI repair: 上传时设置 `enable_ai_repair=false`
- 检查 API monthly limit 是否用完

---

## Artifact Resume 失败

**现象**: resume 后 pipeline 从头开始，未跳过已完成 stage。

**排查步骤**:
1. 检查 artifact 目录: `ls .backend_cache/pipeline_artifacts/{pipeline_id}/`
2. 检查关键标记文件：`.completed` / `.failed`
3. 检查 source_sha256：源文件是否被修改？
4. 检查 created_by：resume 用户是否与原创建者一致？

**解决方案**:
- 源文件修改 → 重新上传新导入，勿 resume
- artifact 被误删 → 更换 pipeline_id 重新导入
- 权限问题 → 确认 resume 请求使用同一 admin 账号

---

## OCR 缓存问题

**现象**: 重复导入仍然慢，cache_hit_rate 低。

**排查步骤**:
1. 检查缓存目录: `ls -la .backend_cache/ocr/`
2. 检查 config_hash：OCR 配置是否变化？
3. 检查文件权限：缓存目录是否可写？

**解决方案**:
- TTL 14 天，过期自动惰性清理
- 配置变化（语言/检测阈值）自动导致缓存失效
- 如需手动清理：管理端 → 运维 → Dry-Run → 确认清理

---

## 相关链接

- [[docs/architecture/OCR_FLOW.md|OCR_FLOW]] — OCR 导入流程
- [[docs/architecture/OCR_USAGE.md|OCR_USAGE]] — OCR 使用说明
- [[docs/ocr/OPERATIONS.md|OPERATIONS]] — OCR 运维
