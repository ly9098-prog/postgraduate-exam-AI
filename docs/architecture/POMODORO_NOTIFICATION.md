# 番茄钟完成通知（字段保留、推送链路未实现）

> 更新时间：2026-10-23
> 状态：本文只描述当前代码事实。微信订阅消息推送链路已于 2026-07-29（commit `0063f278`，fix(notify): remove deprecated WeChat subscribe message push feature）整体移除；`pomodoro_sessions` 的通知相关字段保留，但没有任何发送方读取它们。

## 当前事实（已确认实现）

- 后端**不存在**通知调度器：`wechat_notify_service.py` 与 `pomodoro_scheduler_service.py` 已随 `0063f278` 删除；当前工作区无任何订阅消息发送代码。
- 后端**不存在**番茄钟通知 tick：`app/services/runtime_periodic_tasks.py` 的周期任务只有 token_cleanup / staging_cleanup / export_processor / export_cleanup。
- 配置项 `POMODORO_NOTIFY_ENABLED` / `WECHAT_SUBSCRIBE_POMODORO_TEMPLATE_ID` / `POMODORO_NOTIFY_PAGE` / `POMODORO_SCHEDULER_INTERVAL_SEC` 已随功能移除，代码中无引用。
- 小程序端无 `wx.requestSubscribeMessage` 调用。

字段层面（保留，无发送方）：

- `POST /api/v1/pomodoro/start` 仍接收 `notification_enabled` 并写入会话；free 计时模式强制 `notification_enabled=false`、`work_duration=break_duration=0`（`pomodoro_service.py:283-285,344-345`）。
- start 时仍写 `openid_snapshot`（`pomodoro_service.py:340-346,404-406`）。
- `complete` / `interrupt` 仍会置 `notification_sent=true`、`notification_sent_at`，并写入 `notification_error`：完成写 `skipped: user completed before scheduler`，中断写 `skipped: user interrupted`（`pomodoro_service.py:514-518`）。该文案为历史遗留语义（scheduler 已不存在），当前仅作字段留痕。
- 暂停/恢复 API `POST /api/v1/pomodoro/{session_id}/pause` 与 `/resume` 仍在位（`pomodoro_service.py:651,742`），暂停统计以 `pomodoro_pause_intervals` 为唯一事实源，与通知链路无关。

## 已移除内容（历史设计，勿再当作现行设计）

以下为 2026-06-14 引入、2026-07-29 删除的设计，仅存历史记录：

- 微信订阅消息推送（access_token 缓存 + `message/subscribe/send`）
- APScheduler 60s tick + Redis 锁 `pomodoro:scheduler:tick`（TTL 70s）+ `SELECT FOR UPDATE SKIP LOCKED` 认领
- 「不重复推送 / 重启容错 / 多 worker 兼容 / 暂停延后 / 提前结束置位 / 失败重刷 token」等约束表
- 日志锚点 `2240ai.pomodoro_scheduler`、`2240ai.wechat_notify`
- 公众平台模板 ID `Dc2tD7nbZn4FQi9nYOXZCtpmK3KUbcG_vrJ57UokMUQ` 及模板字段传值

## 数据模型保留字段（pomodoro_sessions）

迁移仍在（schema 未回滚）：

- `p1f2g3h4i5j6_add_pomodoro_notification_fields.py`（通知字段）
- `q2g3h4i5j6k7_add_pomodoro_paused_at.py`（paused_at）

| 字段 | 类型 | 当前状态 |
|------|------|---------|
| `notification_enabled` | bool | start 时写入，无消费者 |
| `notification_sent` | bool | complete/interrupt 时置位 |
| `notification_sent_at` | DateTime | 随 `notification_sent` 置位 |
| `notification_error` | Text | 仅写 skipped 原因 |
| `openid_snapshot` | String(64) | start 时快照，无消费者 |
| `expected_end_time` | DateTime, indexed | 保留（无调度器扫描） |
| `paused_at` | DateTime | 暂停时刻；暂停时长以 `pomodoro_pause_intervals` 为准 |

## 恢复条件（计划，未实现）

如未来恢复服务端推送，需重新引入调度器与订阅消息发送链路、恢复配置项，并经 pm 确认后另行设计；当前仓库无相关代码，本文不描述具体方案。

---

## 相关链接

- [[docs/architecture/SYSTEM_ARCHITECTURE.md|SYSTEM_ARCHITECTURE]] — 系统架构
- [[docs/architecture/PRODUCTION_ARCH.md|PRODUCTION_ARCH]] — 生产架构
- [[docs/architecture/API_ROUTER_STRUCTURE.md|API_ROUTER_STRUCTURE]] — 路由结构
- [[docs/project/PROJECT_RULES.md|PROJECT_RULES]] — 长期项目规则
- [[docs/project/POMODORO_V2_MIGRATION.md|POMODORO_V2_MIGRATION]] — 番茄钟迁移
