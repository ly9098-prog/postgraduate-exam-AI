# 番茄钟完成通知功能开发需求

## 功能目标

为微信小程序番茄钟功能增加「计时结束通知提醒」。

要求：

- 用户开始番茄钟后，即使退出小程序、切换到其他应用、锁屏，也能在计时结束时收到微信通知。
- 不依赖前端 setTimeout 实现提醒。
- 使用微信官方订阅消息能力实现。

------

## 整体流程

用户开始番茄钟

↓

申请订阅消息授权

↓

用户同意

↓

调用后端创建番茄钟任务

↓

后端记录开始时间和结束时间

↓

时间到达

↓

后端自动发送微信订阅消息

↓

用户收到微信通知

↓

点击通知返回小程序番茄钟页面

------

## 小程序端改造

### 开始专注时

点击：

开始专注

执行：

wx.requestSubscribeMessage()

申请番茄钟提醒订阅权限。

如果用户拒绝：

允许继续开始番茄钟。

仅记录：

notificationEnabled=false

如果用户同意：

notificationEnabled=true

并将授权状态传递给后端。

------

### 创建番茄钟任务接口

新增：

POST /api/pomodoro/start

请求：

{
"duration": 25,
"notificationEnabled": true
}

返回：

{
"taskId": "xxx",
"endTime": "2026-06-14T15:30:00"
}

------

### 番茄钟结束页面

如果用户仍停留在小程序：

执行：

- 播放完成音效
- 手机振动
- 播放完成 Lottie 动画
- 弹出完成提示

------

## 后端改造

### 数据库新增表

pomodoro_tasks

字段：

id
user_id
duration
start_time
end_time
status
notification_enabled
notification_sent
created_at

状态：

RUNNING
COMPLETED
CANCELLED

------

### Redis缓存

创建任务时：

缓存：

pomodoro:task:{taskId}

记录：

结束时间
用户openid
通知状态

避免频繁查询数据库。

------

### 定时任务

使用 APScheduler。

每分钟扫描一次：

状态=RUNNING

且：

end_time <= 当前时间

的任务。

找到后：

执行完成逻辑。

------

### 完成逻辑

更新：

status=COMPLETED

然后：

调用微信订阅消息接口发送提醒。

发送成功后：

notification_sent=true

------

## 微信订阅消息

新增：

微信订阅消息模板配置。

消息内容示例：

标题：

番茄钟已完成

内容：

25分钟专注学习已结束

休息一下再继续努力吧

点击消息：

跳转：

/pages/pomodoro/index

------

## 容错要求

服务重启后：

能够继续扫描未完成任务。

不能因为服务重启导致提醒丢失。

------

## 日志要求

记录：

- 用户创建番茄钟
- 用户授权订阅消息
- 定时任务触发
- 消息发送成功
- 消息发送失败

方便后续排查。

------

## 注意事项

禁止使用前端 setTimeout 作为通知核心逻辑。

通知发送必须由后端负责。

请先分析当前项目结构后再实施，保证符合现有 FastAPI、Redis、PostgreSQL 架构，并输出详细改造方案后再开始编码。

------

## 实施状态（2026-06-14 已完成）

提交：`a49f6d5 feat(pomodoro): backend-driven WeChat subscribe notification on timer end`（17 文件，+1427 / -2）

### 已完成

- [x] 后端依赖：`apscheduler==3.10.4`
- [x] 配置项：`WECHAT_SUBSCRIBE_POMODORO_TEMPLATE_ID / POMODORO_NOTIFY_ENABLED / POMODORO_NOTIFY_PAGE / POMODORO_SCHEDULER_INTERVAL_SEC`
- [x] 模型扩展：`pomodoro_sessions` 增加 `expected_end_time`(索引) / `notification_enabled` / `notification_sent` / `notification_sent_at` / `notification_error` / `openid_snapshot`
- [x] Alembic 迁移：`p1f2g3h4i5j6_add_pomodoro_notification_fields.py`
- [x] 微信订阅消息服务：access_token Redis 缓存 + 进程兜底 + 双检锁；40001/40014/42001 强刷重试
- [x] 调度器：`AsyncIOScheduler` 60s tick；Redis 锁 `pomodoro:scheduler:tick`；`SELECT FOR UPDATE SKIP LOCKED` 认领后立即置位 `notification_sent`（至多一次）；启动后立即跑首次以吸收停机期间漏发
- [x] FastAPI lifespan 接入 scheduler 启停
- [x] `/api/v1/pomodoro/start` 透传 `notification_enabled`
- [x] `complete/interrupt/_cancel_running` 在状态切换时关闭通知通道，防止重复打扰
- [x] 小程序 `startSession` 接入 `wx.requestSubscribeMessage`；用户拒绝/未配置不阻断启动
- [x] `miniprogram/config.js` 增加 `POMODORO_SUBSCRIBE_TMPL_ID`
- [x] 文档：`docs/architecture/POMODORO_NOTIFICATION.md`、`docs/DEPLOY_PLAN.md` 同步
- [x] 单元测试：`tests/test_services/test_pomodoro_scheduler.py`（9/9 通过）
- [x] 端到端验证脚本：`tests/manual/verify_pomodoro_scheduler.py`
- [x] TestClient 冒烟脚本：`tests/manual/smoke_pomodoro_e2e.py`

### 设计简化（已与用户确认）

- ~~暂停不延后通知~~ → **已实现暂停延后通知**（2026-06-14 追加）：
  - 新增 `paused_at` 字段 + 迁移 `q2g3h4i5j6k7_add_pomodoro_paused_at.py`
  - 新增 `POST /api/v1/pomodoro/{id}/pause` `/resume` 接口（幂等）
  - scheduler 增加 `paused_at IS NULL` 过滤
  - 小程序 `_pauseSession`/`_resumeSession` 调用后端，失败不阻断本地 UI
  - 单元测试 +4：`test_paused_session_not_claimed` / `test_pause_then_resume_extends_expected_end_time` / `test_pause_is_idempotent` / `test_resume_without_pause_is_noop`
- 失败不重试：写 `notification_error`，避免 24 小时内重发骚扰
- 多副本部署需要可达 Redis；当前生产 `GUNICORN_WORKERS=1`，单 worker 不受影响

### 用户侧待办（部署前必须）

- [x] 微信公众平台申请「番茄钟完成」订阅消息模板（模板 ID `Dc2tD7nbZn4FQi9nYOXZCtpmK3KUbcG_vrJ57UokMUQ`，字段 `thing1` + `character_string2`）
- [x] 服务器 `backend/.env` 设置：
  ```
  WECHAT_SUBSCRIBE_POMODORO_TEMPLATE_ID=Dc2tD7nbZn4FQi9nYOXZCtpmK3KUbcG_vrJ57UokMUQ
  POMODORO_NOTIFY_ENABLED=true
  ```
- [x] 小程序 `miniprogram/config.js` 填同一个 `POMODORO_SUBSCRIBE_TMPL_ID`
- [x] 模板字段已按真实字段名（`thing1` 打卡活动 / `character_string2` 打卡进度）调整 `app/services/pomodoro_scheduler_service.py::_send_one`
- [ ] 部署：`bash deploy/scripts/deploy.sh migrate && bash deploy/scripts/deploy.sh update`（**迁移先于发版**）

### 验证清单（部署后冒烟）

- [ ] 真机：开启番茄钟 → 退出小程序 → 锁屏 → 计时结束时收到微信订阅消息通知
- [ ] 通知点击跳转到 `pages/pomodoro/pomodoro`
- [ ] 用户拒绝订阅授权时番茄钟仍可正常启动
- [ ] 用户提前 complete/interrupt 不会再收到通知
- [ ] 服务重启后 5 分钟内自动追发停机期间到期的通知
- [ ] DB 检查：`SELECT count(*) FROM pomodoro_sessions WHERE notification_error IS NOT NULL` 用于排障

### 后续可选优化（本期外）

- [x] ~~暂停延后通知~~（已实现，见上）
- [ ] `notification_error` 监控告警：发送失败率超阈值时触发
- [ ] 批量场景：单 tick 限制 50 条，需观察生产实际堆积情况