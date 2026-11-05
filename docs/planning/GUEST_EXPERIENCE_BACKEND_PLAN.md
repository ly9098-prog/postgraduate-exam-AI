# 游客体验与自主登录后端实施计划

> 状态：计划（2026-11-05）。本计划只覆盖后端和 API 合约；小程序实现由主任务另行执行。生产部署、迁移、提交和推送均不在本计划内。

> 实施对照（2026-11-05）：本文保留设计阶段原文，以下差异以代码与 [[docs/api/GUEST_EXPERIENCE_API.md|GUEST_EXPERIENCE_API]] 为准：匿名收藏筛选沿用空列表契约；题目使用最新不可变版本而非仅信任 `current_version_id`；作答只提交 `question_id/user_answer`，缺省题目视为跳过，不引入 `used_time/skipped_question_ids`。凭据字段为 `qs` 题目/版本二元组。新增 IP 请求预算，不新增数据库结构。

## Goal

解决微信审核拒绝的“未浏览体验功能即要求授权登录”问题：用户在未登录状态可浏览已发布公式，并按科目完成最多 5 道真实题目的一次完整试做；游客请求不写任何个人学习数据，登录仍由用户主动触发且可取消。

完成标准：

1. 匿名请求可获取公式公共读取内容和游客科目、出题、判分接口。
2. 个人收藏、正式练习提交和其他既有鉴权接口行为不变，无效凭据不能获得身份。
3. 游客批次最多 5 题、24 小时有效、绑定题目与不可变版本；篡改、越界和过期提交被拒绝。
4. 客观题判分复用现有规则，主观题仅返回参考答案自查；游客请求不写用户、练习、错题、复习、掌握度或成长数据。
5. 相关 pytest、Ruff 与 compileall 通过；本地自动验证不等价于模拟器、真机或平台审核验收。

## Architecture

- 新增独立的 `guest` API 域，路由只做参数校验，业务逻辑放在 service；不新增表、迁移、外部依赖或账号体系。
- 新增可选身份依赖 `get_optional_current_user`：无 Authorization 头返回 `None`；提供凭据则复用 `authenticate_user_token` 完整校验，失败抛 401/403，不降级为匿名身份。
- 公式目录、列表、随机读取改为可选身份；详情和标签原本无身份依赖，保持公开。收藏接口保持强制身份，且匿名请求传入 `favorite_only=true` 时返回 401/403 类鉴权错误，不能把个人筛选当公共筛选。
- 游客出题从 `questions.current_version_id` 读取不可变 `QuestionVersion`，并要求可变投影 `review_status == approved`、`is_active` 为真且科目有效。响应复用现有学生内容清洗、选项清理和知识点投影。
- 游客批次使用独立 HMAC 签名用途 `memograd:guest-practice-batch:v1`，与正式练习批次隔离；payload 固定 subject_id 与 revision ids，不绑定用户。判分只读 payload 内版本，不回读可变题目字段。
- 判分端点为纯读操作：复用 `is_answer_correct`、多空 slot 提取和现有答案清洗；主观题 `is_correct=None`，统计仅按客观题计算。

## Global Constraints

- 不引入 LangChain/LlamaIndex、微服务、Kubernetes、账号密码登录、多方式登录、社区或排行榜。
- 不创建游客用户，不使用 openid，不调用 AI，不写入练习记录、错题、复习调度、掌握度、成长统计或正式刷题预留。
- 不改变正式 `/api/v1/practice/*` 的签名、凭据或提交语义；游客凭据不能被正式提交接口接受。
- 公共内容只返回已发布、未删除、已审核且启用的学生可见字段；不返回 `raw_content`、导入来源文件、管理编辑信息或个人信息。
- 新增模块遵守 300 行 / 50 行预算；路由层不承载业务逻辑，测试不使用生产凭据或真实用户数据。

## Task List

### Stage 0 — 可选身份与公式匿名边界（Foundational）

**T0.1 可选身份依赖**

- 修改：`backend/app/core/security.py`
- 新增 `optional_security = HTTPBearer(auto_error=False)` 与 `get_optional_current_user`。
- 依赖：无。可与 T0.2 并行开发，但 T0.2 运行测试依赖 T0.1 完成。
- 验证：
  - `cd backend && .venv/bin/python -m pytest tests/test_api/test_formulas.py -q`
  - 新增测试断言：无凭据依赖返回 `None`；伪造/过期凭据返回 401；有效用户返回同一用户对象。

**T0.2 公式读取鉴权调整**

- 修改：`backend/app/api/v1/formulas.py`
- 修改：`backend/tests/test_api/test_formulas.py`
- `catalog`、`formulas list`、`random` 使用 `get_optional_current_user`。
- 匿名 `favorite_only=true` 显式拒绝；已登录时继续按用户收藏过滤。
- 收藏列表、收藏增删保持 `get_current_user`。
- 验证：
  - `cd backend && .venv/bin/python -m pytest tests/test_api/test_formulas.py -q`
  - 期望：匿名公共读取通过；匿名收藏操作失败；已有登录读取测试不回归。

### Stage 1 — 游客批次与出题（Foundational → User Story）

**T1.1 Guest schema**

- 修改：`backend/app/schemas/guest.py`（新增）
- 定义：
  - `GuestPracticeQuestion`：学生题干、选项、题型、科目、知识点、难度、图片；不含答案和解析。
  - `GuestPracticeQuestionsResponse`：`questions`、`total`、`subject_id`、`batch_token`、`expires_at`。
  - `GuestAnswerSubmit`：`question_id`、`user_answer`、`used_time`。
  - `GuestEvaluateRequest`：`answers`、`skipped_question_ids`、`batch_token`。
  - `GuestEvaluateResponse`：逐题 `is_correct`/`correct_answer`/`analysis`、客观题正确/错误数、总题数。
- 依赖：无；可与 T1.2、T1.3 并行。
- 验证：Pydantic schema 单元测试覆盖答案字段隔离、最大 5 题与空题列表。

**T1.2 Guest batch token**

- 修改：`backend/app/services/guest_practice.py`（新增）
- 实现：
  - `GUEST_PRACTICE_MAX_QUESTIONS = 5`
  - `GUEST_PRACTICE_TOKEN_TTL_SEC = 24 * 60 * 60`
  - 独立 HMAC payload：`v=1`、`sid`、`qids`、`vids`、`iat`、`exp`；签名前用 `APP_SECRET` 派生 `memograd:guest-practice-batch:v1`。
  - `create_guest_practice_batch_token`
  - `decode_guest_practice_batch_token`：验签、结构、题数、题目/版本一一对应、重复、过期。
- 依赖：无；可与 T1.1 并行。
- 验证：新增服务测试覆盖有效期、篡改、重复、题目版本数量不匹配。

**T1.3 科目与题目选择**

- 修改：`backend/app/services/guest_practice.py`
- 修改：`backend/app/api/v1/guest.py`（新增路由）
- 修改：`backend/app/api/v1/router.py`
- 行为：
  - 复用 `practice_service.get_practice_subject_tree` 获取现有科目树，再按“该科目存在合格题目”过滤；无题科目不展示，根科目包含可练习子科目时保留树形结构。
  - `GET /api/v1/guest/practice/subjects` 返回过滤后的树，不要求身份。
  - `GET /api/v1/guest/practice/questions?subject_id=...` 校验 subject 存在、启用且属于当前学习科目域；随机取最多 5 道不同题。
  - 合格题：`Question.review_status == approved`、`Question.is_active`、`current_version_id` 非空，版本 subject_id 与题目/请求科目一致。
  - 复用 `load_revision_views`、`load_revision_kp_names`、`sanitize_question_content`、`sanitize_question_options`、`ensure_true_false_options`。
  - 出题返回学生题干与选项，签发 24 小时游客批次，不返回答案/解析。
- 依赖：T1.1、T1.2；与 T1.4 顺序执行，避免同一 service 文件冲突。
- 验证：
  - `cd backend && .venv/bin/python -m pytest tests/test_api/test_guest_practice.py -q`
  - 覆盖：匿名成功、最多 5 题、少题返回实际数、无题 404、停用/未审核/缺版本排除、答案不出现在出题响应、批次内题目与版本绑定。

### Stage 2 — 游客判分与 API 完整闭环（User Story）

**T2.1 游客判分**

- 修改：`backend/app/services/guest_practice.py`
- 修改：`backend/app/api/v1/guest.py`
- 行为：
  - `POST /api/v1/guest/practice/evaluate` 只接受批次内题目；答案重复、跳过重复、答案与跳过重叠、空答案、越界或额外题目均 400/403。
  - 通过批次内 revision id 读取不可变答案、解析、题型和内容；不使用可变 `questions.answer`。
  - 客观题型复用 `is_answer_correct` 与 `extract_multi_blank_slot_ids`；`subjective` 的 `is_correct` 为 `None` 并返回参考答案。
  - 跳过题返回空用户答案与参考答案，不计入客观正确/错误数。
  - 响应包含客观正确数、客观错误数、主观/跳过说明和总题数；不产生任何数据库写操作。
- 依赖：Stage 1。
- 验证：
  - `cd backend && .venv/bin/python -m pytest tests/test_api/test_guest_practice.py -q`
  - 覆盖：单选/多选/判断/填空/多空/主观、跳过、签名篡改、过期、越界、重复和空答案；断言响应没有用户 ID，服务不调用 `db.add`/`commit`。

**T2.2 鉴权与数据不变性回归**

- 修改：`backend/tests/test_api/test_guest_practice.py`
- 修改：`backend/tests/test_api/test_formulas.py`
- 验证：
  - `cd backend && .venv/bin/python -m pytest tests/test_api/test_guest_practice.py tests/test_api/test_formulas.py -q`
  - 期望：游客接口匿名可用；游客批次不能提交到 `/api/v1/practice/batch-submit`；公式收藏仍要求身份。

### Stage 3 — 文档与质量门禁（Delivery）

**T3.1 API 文档**

- 修改：`docs/backend/API_SPEC.md`
- 增加 `guest/practice` 三个接口、请求/响应边界、24h 凭据和“不写个人数据”承诺。
- 标注本地测试状态；不把模拟器、真机、平台审核写成已通过。
- 依赖：Stage 2 行为冻结后执行。
- 验证：文档中接口路径、字段与代码/测试一致；无未来设计冒充已实现。

**T3.2 质量门禁**

- 命令：
  - `cd backend && .venv/bin/python -m compileall -q app`
  - `cd backend && /home/lmh/.local/bin/ruff check app/core/security.py app/api/v1/formulas.py app/api/v1/guest.py app/services/guest_practice.py app/schemas/guest.py tests/test_api/test_guest_practice.py tests/test_api/test_formulas.py`
  - `cd backend && .venv/bin/python -m pytest tests/test_api/test_guest_practice.py tests/test_api/test_formulas.py -q`
- 期望：compileall 0；Ruff 0；相关 pytest 0 failed。
- 如新增测试文件需要进入 CI 固定清单，同步修改 `.github/workflows/ci.yml`；不移动既有测试文件。

## Acceptance Scenarios

| Given | When | Then |
|---|---|---|
| 无 Authorization | GET 公式目录/列表/随机 | 200，仅公共内容；`favorite_only=true` 被拒绝 |
| 无 Authorization | GET 游客科目/出题 | 200/404，返回最多 5 题且不含答案 |
| 游客批次 | POST evaluate 有效作答 | 返回判分、答案、解析；不写业务表 |
| 游客批次过期/签名篡改/题目越界 | POST evaluate | 401/403/400，不返回答案 |
| 主观题 | 提交任意文本 | 返回参考答案，`is_correct=None` |
| 已登录用户 | 访问正式练习或收藏 | 原鉴权与行为不变 |
| 任意用户 | 用游客 token 调正式 batch-submit | 被正式批次校验拒绝 |

## Rollout / Compatibility

- API 仅新增 `/api/v1/guest/practice/*`，不迁移、不删除既有端点。
- `get_current_user` 不改签名，所有既有强鉴权依赖保持不变。
- 公式接口从强身份变为可选身份，仅影响原本应可匿名浏览的读取；收藏与个人写入无兼容放宽。
- 无数据库 schema 变更，无回滚迁移；后端回退为还原代码文件即可。
- 上线顺序：先部署后端并验证游客接口，再发布小程序；本轮不执行部署。

## Open Items / Notes

- 本计划不实现小程序页面、请求层或本地草稿；这些属于主任务后续阶段。
- 不为游客接口增加新的通用限流组件；沿用现有部署层与 HTTP 防护。若生产观察到异常流量，再基于观测数据专项设计。
- `QuestionVersion` 的 `subject_id` 历史上可为空，但游客体验要求必须存在且与题目/请求科目一致；缺 subject 的版本不入选。
- 不使用正式练习 `BatchSubmitRequest`，避免客户端误把游客凭据当作正式凭据。
