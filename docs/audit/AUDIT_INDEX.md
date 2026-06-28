# 审计索引（auditor-agent 使用）

> 本文件是 auditor-agent 的审计入口，用于快速确定审计范围、风险重点和应查文档。
> 审计原则：先定位风险与最小修复点，不做大规模重构，不替代实现 agent 写业务代码。

---

## 1. 使用规则

### 什么时候查本索引

- 修复前：用户要求排查 bug、真机异常、OCR/PDF 解析异常、AI 标准化异常、API 数据链路错误
- 修复后：需要评估回归风险、数据库兼容、历史数据影响、异步状态风险
- 阶段前：需要审计方案是否违背项目长期规则
- 阶段后：需要验证实现是否与文档、API、DB、前端行为一致

### 审计边界

- 只做工程审计、风险定位、最小修复建议
- 不做大规模架构重写、不升级依赖、不引入新技术栈
- 不直接修改业务代码，除非用户明确要求并且范围很小
- 审计结论必须包含证据位置、影响范围、修复优先级

---

## 2. 审计优先级

| 优先级 | 类型 | 判断标准 |
|--------|------|----------|
| P0 | 数据污染 / 入库错误 / 权限绕过 | 会破坏题库、错题、用户数据或后台权限边界 |
| P1 | 核心流程不可用 | 刷题、导入、确认入库、登录、审核等主链路失败 |
| P2 | 兼容性 / 真机 / 性能风险 | 模拟器正常但真机异常、setData 过大、异步状态错乱 |
| P3 | 文档或体验问题 | 不影响主流程，但会误导后续开发或降低可维护性 |

---

## 3. 风险域 → 必查文档

| 风险域 | 必查文档 |
|--------|----------|
| 项目边界 / 是否违背长期约束 | `CLAUDE.md`、`docs/project/PROJECT_RULES.md` |
| App API | `docs/backend/API_SPEC.md`、`docs/backend/DB_SCHEMA.md` |
| Admin API / 后台权限 | `docs/admin/ADMIN_API_SPEC.md`、`docs/admin/RBAC_RULES.md`、`docs/admin/AUDIT_LOG.md` |
| 数据库兼容 / 字段污染 | `docs/backend/DB_SCHEMA.md`、`docs/admin/DB_SCHEMA_ADMIN.md` |
| OCR / PDF 导入 | `docs/architecture/OCR_FLOW.md`、`docs/ai/OCR_STRATEGY.md`、`docs/ai/STANDARDIZATION_FLOW.md` |
| AI 标准化 / JSON 结构 | `docs/ai/AI_PIPELINE.md`、`docs/ai/STANDARDIZATION_FLOW.md`、相关 `/prompts/` |
| 小程序页面 / 真机渲染 | `docs/frontend/UI_RULES.md`、`docs/frontend/COMPONENT_RULES.md` |
| SM-2 / 复习算法 | `docs/architecture/REVIEW_ALGORITHM.md` |
| 文件 / 图片 / 公式存储 | `docs/backend/STORAGE_DESIGN.md`、`docs/architecture/MATH_IMAGE_ARCHITECTURE.md` |
| 调试规则 / 历史问题 | `docs/debug/DEBUG_SYSTEM.md`、根目录 `docs/BUGS.md` / `docs/DEBUG_HISTORY.md` 如仍被引用 |

---

## 4. 常见审计场景

### OCR / PDF / AI 导入异常

重点检查：

- OCR 是否只负责文本提取，AI 是否只做修复 / 补全 / 结构化增强
- 是否绕过 `question_imports` + 人工确认直接入库
- 题干、选项、答案、解析是否发生重复拼接或错位
- AI 输出 JSON 是否污染字段结构或引入非 schema 字段
- Markdown / LaTeX / 图片引用是否能被小程序安全渲染

必查：

- `docs/architecture/OCR_FLOW.md`
- `docs/ai/OCR_STRATEGY.md`
- `docs/ai/STANDARDIZATION_FLOW.md`
- `docs/backend/DB_SCHEMA.md`

### 小程序真机异常

重点检查：

- 页面生命周期是否重复触发请求或 setData
- 是否存在大对象 / 长列表 / Markdown HTML 一次性 setData
- 异步请求返回顺序是否覆盖新状态
- LaTeX、Markdown、图片渲染是否依赖开发者工具特性
- 分包、资源路径、真机网络边界是否一致

必查：

- `docs/frontend/UI_RULES.md`
- `docs/frontend/COMPONENT_RULES.md`
- 相关页面 `.js/.wxml/.wxss`

### API / 数据链路异常

重点检查：

- 路由是否只做参数校验，业务是否在 services 层
- 响应结构是否保持 `{code, message, data}` 或 Admin 约定结构
- 外部输入是否在边界校验
- 数据库字段是否允许空值、默认值是否与历史数据兼容
- 批量操作是否存在部分失败污染

必查：

- `docs/backend/API_SPEC.md` 或 `docs/admin/ADMIN_API_SPEC.md`
- `docs/backend/DB_SCHEMA.md` 或 `docs/admin/DB_SCHEMA_ADMIN.md`

### Admin / RBAC / 审计日志

重点检查：

- AppUser 与 AdminUser 是否隔离
- Admin 是否保持 `/api/admin/v1` 命名空间
- RBAC 是否通过 FastAPI dependencies 实现，不引入 NestJS/Prisma/BullMQ
- critical 审计日志是否在事务内同步写入
- role-version、用户级 nbf、登录限流是否与文档一致

必查：

- `docs/admin/ADMIN_ARCHITECTURE.md`
- `docs/admin/RBAC_RULES.md`
- `docs/admin/AUDIT_LOG.md`
- `docs/admin/ADMIN_API_SPEC.md`

---

## 5. 审计输出模板

```markdown
## 审计结论

- 结论：通过 / 有风险 / 阻塞
- 最高风险级别：P0 / P1 / P2 / P3
- 影响范围：<模块、接口、页面、数据表>

## 证据

- `<file_path>:<line>` — <观察到的问题或符合点>

## 风险点

1. <风险描述>
   - 影响：<会造成什么后果>
   - 触发条件：<什么情况下发生>
   - 优先级：P0/P1/P2/P3

## 最小修复建议

1. <建议一，限定修改范围>
2. <建议二，避免大改>

## 回归检查点

- [ ] <API / 页面 / 导入 / 数据库检查点>
- [ ] <历史数据兼容检查点>
- [ ] <真机或边界场景检查点>
```

---

## 6. auditor-agent 执行清单

1. 先明确用户要的是修复前排查、修复后复查，还是阶段审计。
2. 根据风险域读取对应文档和代码，不做无关全仓扫描。
3. 优先找数据污染、权限绕过、直接入库、异步状态错乱、真机兼容风险。
4. 给出证据位置与最小修复建议。
5. 若发现文档与代码冲突，标注“以当前代码为准”或“以长期规则为准”，并建议 docs-maintainer 同步。
6. 不输出泛泛建议；每条建议必须能落到文件、接口、页面或数据表。
