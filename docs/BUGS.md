# BUGFIX RECORD — 刷题页面题干/选项重复渲染问题

更新时间：2026-05-28
变更原因：P0「刷题页面题干/选项重复拼接」已按最小改动完成修复，需要将原待修复任务沉淀为已解决记录，并明确仍需重新导入后的手动验证项。

## 【P0】刷题页面题干/选项重复渲染

状态：已解决，待重新导入后手动验证

## 问题现象

刷题页中普通题干和选项在前端页面重复显示。

已确认正常的链路：

- 后端数据库正常
- 审核页面显示正常
- `/practice/questions` API 返回结构正常
- API 未出现重复字段
- `question.content.text` 正常
- `options` 正常
- 后端无需修改 schema
- 后端无需重构导题链路

刷题接口返回的数据结构为：

```json
{
  "content": {
    "text": "题干"
  },
  "options": {
    "A": "...",
    "B": "..."
  }
}
```

接口中未发现：

- 重复题干
- 重复选项
- `rawText`
- `mergedText`
- duplicated options

## 根因结论

根因定位在前端刷题页渲染层，不是后端数据或导题链路问题。

具体表现：

- 普通文本题干/选项也进入 `mp-html` 富文本渲染路径。
- 日志确认 `sourceLen` / `cleanedLen` 正常，`hasEmbeddedOptions` / `hasCleanedOptions` 为 `false`，但页面仍重复显示。
- 因此重复并非来自数据库、审核页、API 或题干清理结果，而是来自刷题页渲染组件路径。

## 修改范围

仅涉及微信小程序刷题页前端渲染相关文件：

- `miniprogram/pages/practice/practice.js`
- `miniprogram/pages/practice/practice.wxml`
- `miniprogram/pages/practice/practice.wxss`

未修改：

- 后端 API
- 数据库 schema
- 导题链路
- 审核入库流程

## 修复策略

采用最小改动修复：

- 普通文本题干使用 `<text>` 渲染。
- 普通文本选项使用 `<text>` 渲染。
- 只有包含 LaTeX 或 HTML 的题干/选项才走 `mp-html`。
- `segments` 模式继续保留 `math-question` 渲染。
- 保留并增强题干清理逻辑，避免题干尾部嵌入选项时重复显示。
- 保留 `BEFORE_RENDER` 诊断字段，用于确认渲染前文本长度和选项嵌入状态。

## 验证要点

已完成的定位/代码级确认：

- 后端数据库、审核页面、`/practice/questions` API 数据结构正常。
- `BEFORE_RENDER` 日志字段可用于确认：
  - `sourceLen`
  - `cleanedLen`
  - `hasEmbeddedOptions`
  - `hasCleanedOptions`
  - `sourceTail`
  - `cleanedTail`
- 普通文本和富文本渲染路径已拆分。

仍需重新导入后手动验证：

1. 刷题页面普通题干不再重复。
2. 刷题页面普通选项不再重复。
3. 单选题正常渲染和作答。
4. 多选题正常渲染和作答。
5. 判断题正常渲染和作答。
6. 新导入题目正常显示。
7. 旧题库兼容性正常。
8. 数学公式 / LaTeX 内容不重复。
9. HTML / 富文本内容不重复。
10. `segments` 模式仍正常使用 `math-question`。
11. 不影响题目解析、提交和错题记录链路。

## 测试数据状态

更新时间：2026-05-28
变更原因：为重新导入并手动验证该 P0 修复，已清理本地 SQLite 题库数据。

- `backend/postgraduate.db` 已备份到 `backend/postgraduate.db.backup-before-clear-20260528192427`
- 已清零：`questions`、`question_imports`、`practice`、`review`、`wrong`、`tags` 等题库/刷题相关数据
- 已保留：`users`、`alembic_version`、`ai_chats`

## 后续处理

- 重新导入题库后，在微信开发者工具或真机中完成手动验证。
- 若仍出现重复，应优先检查刷题页 `mp-html` / `<text>` 条件分支和 `BEFORE_RENDER` 日志，而不是回退到后端 schema 或导题链路排查。
