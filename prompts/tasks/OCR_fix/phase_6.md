你负责 OCR 整改 P6：建立唯一声明式 stage 定义和可复现 artifact/cache 兼容语义。

### 当前问题

- stage order 虽已补充，但运行 stage_specs 和 canonical list 仍分开维护。
- artifact fingerprint 只含 stage order/schema/Python。
- `PipelineRunFingerprint` 存在但未成为 artifact/cache 的真实 SSOT。
- legacy artifact 默认接受。
- artifact 无 checksum/source hash/full config/model/code fingerprint。
- artifact dir 权限为 0755。
- marker/cleanup 主要依赖文件 mtime。
- cache janitor 仍在 OCR 写热路径。

### 必做任务

1. 新建单一 `PipelineDefinition`：
   每个 stage 声明：
   - name/version
   - dependencies
   - enabled_if
   - input/output schema
   - checkpointable
   - idempotent
   - retry policy
   - timeout
   - artifact schema/version
   - metrics namespace
2. orchestrator、coordinator、resume、UI stage status、artifact naming 全部从该定义生成。
3. 完整 `RunFingerprint`：
   - source SHA-256
   - selected page range
   - immutable options hash
   - code commit + dirty
   - dependency lock hash
   - OCR engine/model/weights digest
   - preprocess version/config
   - adapter config version和 secret version/HMAC（不含 secret）
   - DocumentIR schema
   - evaluator/rule versions
   - stage definition hash
   - deployment/runtime backend
4. artifact manifest：
   - run fingerprint
   - stage fingerprint
   - payload checksum
   - created time
   - upstream artifact checksums
   - schema version
   - completion/idempotency key
5. 原子持久化：
   - unique tempfile
   - flush + fsync file
   - os.replace
   - 必要时 fsync directory
   - 并发 writer 测试
6. typed serialization：
   - JSON/Pydantic schema。
   - 禁止 datetime/Decimal/UUID 通用 `str()` fallback；显式编码和解码。
7. 安全：
   - artifact root/dir 0700。
   - pipeline ID path containment。
   - cleanup 校验 DB ownership/tenant/status。
8. legacy：
   - 生产默认拒绝无 metadata artifact。
   - 提供显式离线迁移工具和 dry-run report。
9. janitor：
   - cache/artifact 清理由独立后台 job。
   - quota、TTL、LRU、corrupt quarantine。
10. resume：
   - 只从 checksum/fingerprint/schema 全兼容的边界恢复。
   - 写库用幂等 key/outbox，避免重复 review batch 或题目记录。

### 测试

- 任一关键维度变化，cache/artifact 必失效。
- 半写、断电模拟、并发写、checksum 损坏均安全回退。
- legacy 默认拒绝。
- path traversal/symlink/tenant 越权全部拒绝。
- clean run 与每个 checkpoint resume 最终结果等价。
- optional stage 组合不会造成 stage order 漂移。
- 同一任务重复执行只生成一个 review batch。

### 验收

- 仓库只存在一个 stage 定义事实源。
- artifact manifest 可机器验证。
- resume equivalence acceptance test 通过。
- 热路径不再全目录清理。