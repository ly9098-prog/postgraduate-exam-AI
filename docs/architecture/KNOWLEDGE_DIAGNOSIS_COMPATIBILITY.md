# 小程序章节知识诊断请求链路兼容边界

## 范围与职责

2026-10-30 按“小程序接口 > 后台管理系统接口 > OCR 接口”顺序，治理统计页和学习中心消费的章节知识诊断请求链路。

- 小程序统计页 `pages/dashboard/dashboard.js::_fetchKnowledgeDiagnosis` 请求 `GET /api/v1/study-hub/knowledge-diagnosis`；学习中心 `study_hub_service._chapter_task_for_subject` 消费同一 service 的首条推荐并生成章节任务。
- `api/v1/study_hub.py` 保留原鉴权依赖、参数约束、404 与响应 schema。路由无需另行拆分。
- `knowledge_diagnosis_service.py` 保留原三个函数的声明、数据库读取与 map/history/aggregate/rank 的调用顺序。
- `knowledge_diagnosis_projection.py` 集中历史 scope 清洗、根章节报告、最近会话、汇总报告和响应投影；只通过使用时读取的 service 端口取得原 helper，不导入数据库、模型、配置或 service。
- `knowledge_diagnosis_logic.py` 是本批保留的既有聚合/排名依赖，文件与长函数未修改。本批不代表整个知识诊断领域均已达到预算或完成全部治理。

## 保留行为

### 历史读取与清洗

查询仍只读取同一 user/subject 的 completed knowledge_chapter 会话，以 `finished_at >= since` 为下界，无新增上界；按 finished_at、id 均倒序。列、参数转换和执行顺序保持。

先归一化历史 scope，再读取行根 ID；scope 缺失、根 ID 非正或两处根不一致时丢弃。served/resolved ID 集合、计数非负处理、字符串转换和历史时间对象保持原口径，不从当前知识树重写快照。

### 请求与投影

map 不存在时在读取时钟和会话前返回 None。days 在查询窗口和汇总 period 两处按原规则转换并截断至 1–365；默认、异常转换时机均保持。

聚合与排名使用原依赖；根章节按原 nodes 顺序产出。当前 coverage 与 scope coverage 保留各自截断规则；accuracy 不增加 0–1 截断。mastery、空值、round 和时间序列化规则保持。

先取 `subject_map["subject"]`，再生成最近会话和汇总。最近会话仍先取前五条，再跳过非 datetime，因此返回可以少于五条；不从第六条补齐。汇总仍统计全部有效 scope 会话，最近七天统计与最近展示列表是不同口径。

scope 的 exam408 回退、字段插入顺序、recommendations 列表与 primary_recommendation 首项对象身份保持。历史 service helper 和常量在每次使用时读取，运行期间替换 helper 的行为仍可见。

### 异常与副作用

本链路保持只读，不增加 commit/flush/add/rollback、缓存写入或错误吞并。查询、scope/helper 和字段访问异常按原顺序传播；CancelledError 原样传播。本批没有业务修复、schema/迁移或客户端界面变动。

## 回归入口

- `backend/tests/test_services/test_knowledge_diagnosis_contract.py`：历史 scope/SQL、空 map、days、最近截取、异常与取消、动态 helper、Public API 查询校验/404/响应，以及学习中心使用真实诊断 service。
- 既有 `test_knowledge_diagnosis_logic_compatibility.py`、`test_rank_chapter_recommendations_compatibility.py`、`knowledge/test_knowledge_diagnosis_ranking.py` 和 study-hub recommendation/overview 契约继续覆盖依赖规则。
- `backend/tests/architecture/test_knowledge_diagnosis_boundaries.py`：原声明/SQL、投影委托、导入与数据库边界、模块/函数预算及负例；两份新增测试进入固定 CI 静态清单。

命令、数量、文件长度、哈希和最终审查结论集中于 `refactor-results/miniprogram-knowledge-diagnosis-2026-10-30.json`。临时回放工具及日志保存在 `/tmp/miniprogram-knowledge-diagnosis-batch/`；extract.py/build_gate.py 会改写源码，禁止作为验证命令重跑。

## 验收限制

Public API 测试使用独立 FastAPI router、替换的数据库与用户依赖，验证参数和响应边界，不代表真实微信登录/JWT 验收。差分中的数据库响应为替身；SQL/参数对照不等于真实 PostgreSQL 执行、索引计划或生产数据验收。

未执行真实微信编译、模拟器/真机、跨设备、生产鉴权、外部 AI/OCR、PostgreSQL/Redis 与完整学习闭环验收。未部署、push 或操作生产/用户数据。全栈重构目标保持 ACTIVE。
