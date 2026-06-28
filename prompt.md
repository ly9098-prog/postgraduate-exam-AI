# 22408 AI 考研学习助手 — prompt.md

> 当前阶段任务入口。已完成开发阶段归档于 `/docs/ARCHIVE/`。
> 详细设计文档见 `/docs/`。
>
> **别先改代码，先看这里明确当前要做什么。**

---

## 项目状态

| 阶段 | 状态 |
|------|------|
| 1-6：核心刷题 → 生产部署 | ✅ 完成 |
| 7：AI 辅助导题 | ✅ 完成 |
| 8：OCR 扫描版 PDF | ✅ 完成（待容器环境 E2E 验证） |
| **微信小程序正式环境切换** | **⏳ 唯一阻塞项** |

当前后端全部功能已完成，唯一未完成的是小程序端切换到生产环境并提交微信审核。

---

## 当前 Sprint

- [ ] 修改 `miniprogram/config.js` 的 `BASE_URL` 为生产域名
- [ ] 微信小程序管理后台配置合法域名
- [ ] 关闭开发模式（`DEV = false`）
- [ ] 全链路回归测试（登录 → 刷题 → 错题 → AI → 复习）
- [ ] 提交微信审核

---

## 执行流程

1. **读 CLAUDE.md** — 项目规则、架构约束、开发规范
2. **读本文件** — 当前阶段任务
3. **查阅 `/docs/`** — 需要细节时
4. **查阅 `/docs/ARCHIVE/`** — 需要回顾历史阶段设计时
5. **实施变更**
6. **回归验证**（不破坏已有功能）

---

## 关键参考导航

| 文档 | 内容 |
|------|------|
| `docs/backend/API_SPEC.md` | 全部 API 接口定义 |
| `docs/backend/DB_SCHEMA.md` | 数据库设计 + ER 图 |
| `docs/project/PROJECT_RULES.md` | 开发规范补充 |
| `docs/ai/AI_PIPELINE.md` | AI 模块架构 |
| `docs/architecture/OCR_FLOW.md` | OCR 处理流程 |
| `docs/architecture/REVIEW_ALGORITHM.md` | SM-2 复习算法 |
| `docs/frontend/UI_RULES.md` | 小程序 UI 规范 |
| `docs/architecture/MEMORY_SYSTEM.md` | 记忆系统设计 |
| `docs/achieve/README.md` | 历史阶段归档索引 |

---

## 重要约束（与 CLAUDE.md 一致）

- 不引入 langchain / llamaindex / 新中间件
- 不提前优化，不抽不必要的抽象
- AI 挂了不能阻塞刷题
- 不要创建 `__init__.py` 重导出
- 不改已有 API 兼容性（只新增，不破坏）
- 不改数据库 migration 回滚脚本
