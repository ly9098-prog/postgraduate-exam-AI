# 阶段 3：完善 + 打磨 ✅

**目标**：体验优化、数据统计、稳定性

| 项目 | 内容 |
|------|------|
| 前端 | 加载态、空态、错误态覆盖、数据看板 |
| AI | 降级方案完善、token 统计看板 |
| 部署 | Nginx 配置、HTTPS、日志收集 |

**验收**：所有页面有加载/空/错误状态 → 复习计划按时推送 → AI 降级正常（API 挂了不影响刷题）→ 可部署上线

### AI 降级策略

1. 静默降级：返回预置通用分析模板
2. 本地缓存：检查 `wrong_questions.ai_analysis` 是否有缓存
3. 排队重试：写入 `ai_retry_queue`，下次请求时重试
4. 前端提示：小程序提示"AI 分析暂时不可用，请稍后重试"

不允许阻塞刷题流程，AI 挂了对用户无感知。

---

## 相关链接

- [[docs/INDEX.md|INDEX]] — 文档总索引
- [[docs/project/ROADMAP.md|ROADMAP]] — 现行范围
- [[docs/project/CHANGELOG.md|CHANGELOG]] — 项目变更记录
- [[docs/planning/TASK_PLAN.md|TASK_PLAN]] — 任务计划
