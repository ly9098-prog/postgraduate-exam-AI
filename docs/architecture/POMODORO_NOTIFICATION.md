# 番茄钟完成通知链路

> 更新时间：2026-06-14

## 设计目标

让用户即使**退出小程序、切到后台、锁屏**，也能在番茄钟到点时收到提醒。
**不**依赖前端 setTimeout，**不**依赖小程序运行状态。
通知核心由后端 + 微信订阅消息推送。

## 总链路

```
小程序: 点击「开始专注」
   │
   ├─ wx.requestSubscribeMessage(POMODORO_SUBSCRIBE_TMPL_ID)
   │     accept → notification_enabled=true
   │     reject → notification_enabled=false（番茄钟仍正常启动）
   │
   ▼
POST /api/v1/pomodoro/start { notification_enabled, ... }
   │
   ▼
backend: pomodoro_sessions 写入
   start_time, expected_end_time = start_time + work_duration*60s
   notification_enabled, notification_sent=false, openid_snapshot=user.openid
   │
   ▼
APScheduler.AsyncIOScheduler  每 60s tick
   │
   ├─ Redis 锁 pomodoro:scheduler:tick (TTL 70s) → 单实例独占
   │
   ├─ 认领：SELECT FOR UPDATE SKIP LOCKED
   │   WHERE status='running'
   │     AND notification_enabled=true
   │     AND notification_sent=false
   │     AND expected_end_time <= now()
   │     AND openid_snapshot IS NOT NULL
   │   并立即 UPDATE notification_sent=true（至多一次语义）
   │
   ▼
wechat_notify_service.send_subscribe_message
   access_token：Redis cache (wechat:access_token, ttl=expires_in-600s)
                + 进程内变量兜底
   POST https://api.weixin.qq.com/cgi-bin/message/subscribe/send
   page = pages/pomodoro/pomodoro
   │
   ▼
用户微信收到通知 → 点击 → 跳到番茄钟页面
```

## 关键约束

| 约束 | 实现 |
|------|------|
| **不重复推送** | 认领事务中先 `UPDATE notification_sent=true` 再发送；发送失败仅记录 `notification_error` |
| **重启容错** | scheduler 启动时 `next_run_time=utcnow()` 立即跑一次，吸收停机期间到期任务 |
| **多 worker 兼容** | Redis 锁 `pomodoro:scheduler:tick` 互斥；生产 `GUNICORN_WORKERS=1` 也安全 |
| **暂停延后通知** | `/pause` 写入 `paused_at`，scheduler 跳过；`/resume` 把暂停时长加到 `expected_end_time` 后清空 `paused_at` |
| **用户提前结束** | `complete/interrupt` 把 `notification_sent=true` 置位，scheduler 跳过 |
| **新启动覆盖旧任务** | `_cancel_running` 把旧 running 任务标 interrupted 并关闭通知通道 |
| **access_token 失效** | errcode 40001/40014/42001 → 强刷一次重发，仍失败写 `notification_error` |
| **模板未配置** | `notification_error="skipped: template_id not configured"`，不影响 status |

## 数据模型新增字段（pomodoro_sessions）

| 字段 | 类型 | 说明 |
|------|------|------|
| `expected_end_time` | DateTime, indexed | 预计完成时刻（UTC），调度器扫描依据 |
| `notification_enabled` | bool | 用户是否授权订阅 |
| `notification_sent` | bool | 是否已发送（认领前置位，幂等护栏） |
| `notification_sent_at` | DateTime | 发送/置位时间 |
| `notification_error` | Text | 失败原因/跳过原因 |
| `openid_snapshot` | String(64) | start 时的 openid 快照，发送不再 join users |
| `paused_at` | DateTime | 暂停时刻；非空时 scheduler 跳过；resume 时按其计算延后量 |

迁移：
- `p1f2g3h4i5j6_add_pomodoro_notification_fields.py`（首批字段）
- `q2g3h4i5j6k7_add_pomodoro_paused_at.py`（暂停延后通知）

## 配置项

| 名称 | 默认 | 说明 |
|------|------|------|
| `POMODORO_NOTIFY_ENABLED` | `true` | scheduler 总开关 |
| `WECHAT_SUBSCRIBE_POMODORO_TEMPLATE_ID` | `""` | 公众平台申请的订阅消息模板 ID |
| `POMODORO_NOTIFY_PAGE` | `pages/pomodoro/pomodoro` | 点击通知跳转路径 |
| `POMODORO_SCHEDULER_INTERVAL_SEC` | `60` | tick 间隔（最小 15s） |
| 小程序 `config.js` `POMODORO_SUBSCRIBE_TMPL_ID` | `""` | 同模板 ID，用于 `wx.requestSubscribeMessage` |

## 模板字段

公众平台已申请模板 ID：`Dc2tD7nbZn4FQi9nYOXZCtpmK3KUbcG_vrJ57UokMUQ`

| 字段 | 类型 | 当前传值 | 备注 |
|------|------|----------|------|
| `thing1.DATA` | thing（中文/数字，≤20 字符，禁止符号） | `{科目}番茄钟`（如 `数学番茄钟`） | 打卡活动 |
| `character_string2.DATA` | character_string（字母+数字，≤20 字符） | `{N}min`（如 `25min`） | 打卡进度 |

实现位置：`app/services/pomodoro_scheduler_service.py::_send_one`

## 日志锚点

- `2240ai.pomodoro_scheduler` — tick 启停、认领数量、发送结果
- `2240ai.wechat_notify` — access_token 刷新
- 单条任务：`番茄钟通知已发送 session_id=X openid=***xxxx`
- 失败：`番茄钟通知发送失败 session_id=X errcode=Y msg=Z`

## 已知限制

1. 失败不重试（避免 24 小时内重发骚扰）
2. 多副本部署必须同时具备可达 Redis；否则可能出现重复 tick（生产 1 worker 当前不受影响）
3. `paused_at` 仅在调用 `/pause` 时写入；前端若崩溃未上报暂停，scheduler 仍会按原 `expected_end_time` 推送（前端在 `_pauseSession` 中调用，本地暂停 UI 与后端推迟同步）

## 暂停/恢复 API

```
POST /api/v1/pomodoro/{session_id}/pause
POST /api/v1/pomodoro/{session_id}/resume
```

- `pause` 幂等：重复调用不刷新 `paused_at`
- `resume` 幂等：未暂停时不改 `expected_end_time`
- 暂停期间 `expected_end_time` 不变，scheduler 通过 `paused_at IS NOT NULL` 跳过
- 恢复时 `expected_end_time += (now - paused_at)`，并清空 `paused_at`
