# AI Debug System

## 开启方式

- 前端：`miniprogram/config.js` 中 `DEBUG_MODE` 由 `DEV` 控制。
- 后端：`backend/app/core/config.py` 中 `DEBUG_MODE` 默认为 `None`，开发环境自动开启，生产环境默认关闭。

## TraceId

- 格式：`TRACE_YYYYMMDD_random`
- 示例：`TRACE_20260528_a1b2c3`
- 一次刷题流程建议复用同一个 TraceId，贯穿 API、normalize、render、submit。

## 单题调试

- 设置 `DEBUG_QUESTION_ID` 后，只输出对应题目的详细调试信息。
- 不匹配的题目只保留最小摘要，避免日志污染。

## renderCount

- 刷题页在每次题目展示时递增 `renderCount`。
- 如果发现同一题 renderCount 异常增长，优先检查 state 变化和重复 setData。

## Snapshot

- 前端 snapshot 保存在小程序 storage，键名包含 `traceId` 和 `stage`。
- 后端 snapshot 写入 `debug_snapshots/`。
- 常见阶段：`api`、`before_normalize`、`after_normalize`、`render`、`state`、`submit`。

## 分析链路

1. 先看 `API_RESPONSE` 是否已出现。
2. 再看 `BEFORE_NORMALIZE` / `AFTER_NORMALIZE` 是否一致。
3. 再看 `BEFORE_RENDER` 与 `renderCount` 是否异常。
4. 最后看 `STATE` 与 `SUBMIT` 是否沿同一 TraceId 传递。

---

## 相关链接

- [[docs/debug/DEBUG_HISTORY.md|DEBUG_HISTORY]] — 调试历史
- [[docs/project/BUGS_HISTORY.md|BUGS_HISTORY]] — 缺陷历史归档
- [[docs/backend/API_SPEC.md|API_SPEC]] — App API 合约
