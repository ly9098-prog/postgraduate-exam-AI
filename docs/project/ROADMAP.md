# 项目路线图

> 当前处于 MVP 完成 + 导入管线增强阶段。

---

## 已完成

- 用户认证（微信 openid + JWT）
- 题库 CRUD + 随机刷题 + 自动判分
- 错题本（分类/筛选/统计）
- SM-2 间隔重复复习系统
- AI 错题分析 + 学习建议（DeepSeek + 降级缓存）
- 题库导入（Excel/PDF/Word）+ AI 辅助导题
- OCR 扫描版 PDF（代码就绪，待 E2E 验证）
- 学习统计 Dashboard + 答题行为记录
- 前端 10 个页面覆盖主要流程
- Docker Compose + Nginx 生产部署

---

## 当前阶段

- **导入管线增强**：文本标准化 → 结构分析 → 题目切分 → 答案匹配 → Schema 标准化 → AI 修复 → 审核 → Pipeline 集成（stage1-9）
- **生产环境切换**：小程序 BASE_URL 切换 + 提交审核

---

## 规划中

- 小程序提审上线
- 导入管线 E2E 验证
- 核心 service 单测补充
- OCR E2E 验证
