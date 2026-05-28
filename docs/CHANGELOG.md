# 调试变更日志

> 记录调试体系、日志规范、trace 方案、snapshot 方案等工程级变更。

> 说明：项目级发布变更仍以 `docs/project/CHANGELOG.md` 为准；这里专门记录调试基础设施相关变化。

## 2026-05-28

### Fixed
- 刷题页普通题干/选项重复渲染问题已修复：普通文本改走 `<text>`，仅 LaTeX/HTML 内容走 `mp-html`，`segments` 模式继续使用 `math-question`。

### Changed
- 更新 `docs/BUGS.md` 和 `docs/DEBUG_HISTORY.md`，将 P0 重复渲染问题从待修复任务改为已解决记录；变更原因是前端渲染路径已完成最小修复，但仍需重新导入后在微信开发者工具或真机手动验证。


只记录下面这些内容：

- traceId 体系调整
- DEBUG_MODE / 单题调试开关
- snapshot 目录或格式变化
- 日志字段与层级规范变化
- 调试文档体系调整
- 调试流程的结构性变更

不记录：

- 单个 BUG 的排查细节
- 临时修复过程
- 与调试体系无关的产品发布说明

## 推荐格式

```markdown
## 2026-05-27

### Added
- 新增 `DEBUG_MODE` / `DEBUG_QUESTION_ID` 规范。
- 新增 `traceId` 统一传递规则。

### Changed
- 统一 `OCR` / `AI_PARSE` / `NORMALIZE` / `DB_SAVE` / `API` / `RENDER` 日志层级。

### Fixed
- 统一题目链路的 snapshot 保存顺序。
```

## 维护原则

- 一条变更只写一次
- 先写结果，再补影响范围
- 不写推测，只写已确认事实
- 变更描述保持短句，便于检索
