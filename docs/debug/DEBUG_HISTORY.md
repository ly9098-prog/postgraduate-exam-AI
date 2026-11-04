# 调试历史

> 记录已经定位并修复过的调试案例，给后续 AI 和开发者提供根因参考。

## 用途

当一个 BUG 已经完成“定位 → 修复 → 验证”后，把完整排查过程沉淀到这里，而不是继续留在 `BUGS.md`。

## 维护规则

- 只记录已经闭环的案例
- 只保留根因、证据、修复范围和验证结论
- 不写冗长回顾，不写情绪化判断
- 每条记录必须包含 `traceId` 或 `questionId`
- 只记录第一次异常出现的层，不记录猜测链路

## 推荐格式

```markdown
## 2026-05-27 Q123 题干重复拼接

状态：已修复

traceId：
- TRACE_20260527_143012_OCR_a8f3c2

questionId：
- 123

排查链路：
- OCR：正常
- AI_PARSE：正常
- NORMALIZE：首次异常
- DB_SAVE：沿用污染数据
- API：未二次污染
- FRONTEND_STATE：未二次污染
- RENDER：正常

第一异常层：
- NORMALIZE

证据：
- `normalize_output` 中出现重复拼接
- `db_read_output` 已继承污染结果

修复：
- 仅修正标准化输出字段合并逻辑

验证：
- Q123 正常
- 同批次题目无回归
```

## 2026-05-28 刷题页普通题干/选项重复渲染

状态：已解决，待重新导入后手动验证

traceId：
- 未固定；通过刷题页运行时 `traceId` 与 `BEFORE_RENDER` 日志定位

questionId：
- 未固定；问题出现在刷题页普通文本渲染路径

排查链路：
- DB：正常
- REVIEW：正常
- API：正常
- FRONTEND_STATE：正常
- RENDER：首次异常

第一异常层：
- RENDER

证据：
- 后端数据库、审核页、`/practice/questions` 返回结构均正常。
- `question.content.text` 与 `options` 未发现重复字段或重复拼接。
- `BEFORE_RENDER` 中 `sourceLen` / `cleanedLen` 正常，`hasEmbeddedOptions` / `hasCleanedOptions` 为 `false`，但页面仍出现重复显示，指向渲染组件路径。

修复：
- 普通文本题干/选项改用 `<text>` 渲染。
- 仅包含 LaTeX 或 HTML 的题干/选项走 `mp-html`。
- `segments` 模式继续保留 `math-question`。
- 保留并增强题干清理和 `BEFORE_RENDER` 诊断字段。

验证：
- 代码级确认普通文本与富文本渲染路径已拆分。
- 待重新导入题库后，在微信开发者工具或真机验证刷题页题干/选项不重复。

## 记录原则

- 根因优先于现象
- 证据优先于结论
- 单层修复优先于联动修改
- 验证结果必须可复现

---

## 相关链接

- [[docs/debug/DEBUG_SYSTEM.md|DEBUG_SYSTEM]] — 调试体系
- [[docs/project/BUGS_HISTORY.md|BUGS_HISTORY]] — 缺陷历史归档
- [[docs/backend/API_SPEC.md|API_SPEC]] — App API 合约
