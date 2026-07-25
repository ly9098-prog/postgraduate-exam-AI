你负责 OCR 整改 P0：建立可信基线和发布门禁。本阶段不追求大规模重构，目标是让后续每个修复都可被自动验证，并消除“文档已完成但代码不可证”的状态。

### 必做任务

1. 扫描完整仓库而非仅 app/：
   - 记录 commit、dirty state、Python 版本、操作系统、依赖管理方式。
   - 统计源码、测试、CI、Docker、lock、benchmark、样本目录。
   - 计算当前源码包和关键输入集 hash。
2. 建立 `docs/audit/ocr_pipeline/ISSUE_MATRIX.md`：
   - 每个 fix_task 条目只能是 VERIFIED / PARTIAL / UNVERIFIED / REGRESSED / BLOCKED。
   - 每项必须附代码位置、测试名、测试结果和 commit。
3. 新增最小工程门禁：
   - import smoke test
   - compileall
   - ruff/format
   - pyright 或 mypy
   - pytest
   - pip-audit
   - Bandit/Semgrep（按仓库现状选一套可执行方案）
4. 新增静态架构测试，先让测试暴露当前违规：
   - 直接 import `app.services.ocr_service` 推理函数/私有锁的调用方。
   - 直接调用旧 safety acceptance 的调用方。
   - coordinator 中 `dummy_ir`、固定 success/no-op。
   - artifact/cache 中硬编码 fingerprint。
5. 给生产 feature flags 增加安全校验：
   - coordinator 尚有 dummy/no-op 时，`PIPELINE_COORDINATOR_MODE=coordinator` 必须启动失败或请求 fail closed。
   - OCR Gateway 尚未完整时不得静默启用。
6. 清理文档中的误导状态：
   - 仅把有自动测试证据的项保留为 ✅。
   - 其他项改为 PARTIAL/UNVERIFIED/REGRESSED。

### 不要做

- 不要在本阶段把架构测试标记 xfail 后宣称通过。
- 不要用 grep 脚本代替 AST 检查所有 Python import。
- 不要删除 legacy 路径，先建立可运行 baseline。
- 不要把 coordinator 的 dummy 结果包装得更像真实结果。

### 验收

- CI 能从干净环境安装并运行。
- 当前已知违规测试会稳定失败，或通过明确 allowlist 精确约束。
- coordinator 假成功路径已 fail closed。
- `CURRENT_STATE.md` 与代码一致。
- 输出 P0 commit、命令、日志摘要和剩余阻断项。