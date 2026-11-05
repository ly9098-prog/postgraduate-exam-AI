# 当前任务与历史验收交接

## 2026-11-05 当前任务：冷启动会话还原

- 以 `prompts/tasks/current_task.md` 的新任务为准；旧 Obsidian 链接任务已结束，本轮不再继续复核旧任务。
- 已实现默认冷启动在登录后依次解析待确认刷题提交、单槽刷题/复习标记、番茄钟，直接 reLaunch；热启动和显式目标保持原入口。
- 新模块：`miniprogram/utils/launch-session-store.js`、`launch-resume.js`、practice `utils/cold-resume-controller.js`、review-today `utils/review-active-state.js`；页面冻结字面量、app.js/home.js 未改。
- 完成作答/切题/onHide 快照、交卷接管/退出清除、复习阶段标记与用户归属检查。自动鉴权失效保留恢复状态，显式登出清除。番茄钟快照写入附加 ownerId。
- 本轮复审修复：自动鉴权失效重新登录可恢复一次；复习 overview/error 瞬态保留标记；普通刷题与待确认交卷均容忍设备时钟回拨；掌握和退出控制器通过独立业务端口清理活跃状态，计时端口不再夹带清理副作用。均有回归覆盖。
- 本地验证：渲染 fixture 5/31、架构守卫、包体/媒体预算和包体质量检查通过。全量测试结果记录于 `current_task.md`。历史 `scripts/test-*.js` 25/28，3 个失败已在未修改 HEAD 基线复现，本轮未重跑该历史脚本集合。
- 文档：`docs/frontend/LAUNCH_RESUME.md`，包含本地边界和完整手工清单。初版已提交 `e3759765`，本轮按用户授权提交复审修复；尚未做微信编译、模拟器、真机、原生返回按钮及编译包扫描，未推送、部署或同步 Windows 镜像。
- 保留本轮开始前的所有无关修改、删除与未跟踪文件。实施计划 `prompts/tasks/launch-resume-plan.md`；本地验证输出 `/tmp/postgraduate-launch-resume-20261105/`（临时证据，不提交）。

## 历史重构与最终环境验收摘要

更新：2026-11-02（Asia/Shanghai）。最新验收证据基线为 `307a8df9`（该证据提交时本地 `origin/main` 引用 ahead 7，未推送）；整体ENV-BLOCKED（最终验收未完成），代码已达到继续隔离验收标准；当前轮专用合成身份/角色续验及清理完成，并复核ENV-02/03/05既有证据与当前源码一致。最终门禁未全关。旧交接快照保留；修复快照在 `~/.cache/postgraduate-ai/acceptance/2026-11-01-env02-fixes/before/`。
