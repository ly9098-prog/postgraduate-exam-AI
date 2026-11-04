# 冷启动会话还原实施计划（2026-11-05）

仅实现 `current_task.md` 已确认的小程序范围，不提交、部署或改后端。保留工作区既有改动。

1. 基础存储与解析：新增 `miniprogram/utils/launch-session-store.js`、`launch-resume.js`，更新 `utils/storage-core.js`。使用用户动态键、固定 24 小时刷题生命周期、当日复习标记和有界番茄钟查询；登录入口集成并防止异步迟响应覆盖显式入口。
2. 刷题持久化：新增 `subpackages/study/practice/utils/cold-resume-controller.js`；在现有生命周期、加载、作答、切题、提交控制器接入，保留批次凭据与启动上下文，重建前台计时。`practice.js`、`app.js`、`home.js` 不变。
3. 复习标记：在现有复习控制器的阶段切换及确认退出接入单槽标记，不改变草稿恢复/清理行为。页面字面量与番茄钟页面不变。
4. 验证：先写 `node:test` 失败用例，再实施；运行新增行为测试、受影响既有测试、全量独立脚本、架构守卫和包体检查。守卫仅登记必要的新依赖，不抬高页面预算。按当前结果记录故障，不把旧报告当通过证据。
5. 交付：同步 `docs/frontend/` 与任务/交接状态，列出微信开发者工具和真机待验边界，完成代码审查。

验证重点：冷/热启动与显式路径、登录后用户隔离、pending/blocked/submitted 优先级、超时与离线降级、快照完整性和 TTL 不续期、确认退出与提交接管、同日/跨天复习以及后台时间不计入。

顺序模式服务端预留 TTL 为 24 小时（`backend/app/services/practice/sequential_service.py`），与 batch token 一致；还原应复用原 token/requestId，不换发批次。真实设备平台导航栏与真实多设备并发行为交给任务中的手工清单验收。
