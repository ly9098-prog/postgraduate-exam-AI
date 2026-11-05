---
tags: [api, guest, practice, review-remediation]
title: 游客体验与自主登录 API
type: reference
---

# 游客体验与自主登录 API

> 更新：2026-11-05。对应微信审核整改“先浏览体验，再自主登录”。本页只记录已实现的后端契约；小程序、模拟器、真机与平台审核结果分开记录，本地自动测试不代表审核通过。

## 背景与边界

审核要求用户可以先浏览、体验功能，再自行选择是否授权登录；登录页必须提供取消/返回。为此开放两类匿名读取：

1. **公式公共内容**：目录、标签、列表、详情、随机阅读。
2. **游客试做**：按科目取最多 5 道真实题目，作答后查看判分与解析。

游客不创建账号，不调用 AI，不写练习记录、错题、复习调度、掌握度、成长统计或正式刷题预留；游客凭据不能用于正式提交接口。

## 认证方式

| 模式 | 使用范围 | 行为 |
| --- | --- | --- |
| 必需身份 | 收藏、个人数据、正式练习、管理接口 | 沿用 `get_current_user`；缺失或失效返回 401/403 |
| 可选身份 | `GET /formulas/catalog`、`GET /formulas`、`GET /formulas/random/next` | 无 `Authorization` 时按匿名返回公共内容；提供凭据时完整校验，无效凭据不会被降级为匿名 |
| 匿名 | 标签、公式详情、游客试做 | 不读取身份 |

匿名请求携带 `favorite_only=true` 时，公式列表返回空分页（`items=[]`、`total=0`、`total_pages=0`，保留请求的 `page` / `page_size`），公式目录返回 `items=[]`；普通匿名读取不受影响，已有参数校验继续生效。携带有效身份时按当前用户筛选收藏，收藏列表与收藏增删始终要求身份。

## 游客试做接口

前缀 `/api/v1/guest/practice`，三个端点共用按客户端 IP 的 120 次/分钟预算；超限返回 429，缓存不可用返回 503，均不进入业务查询。

### GET `/subjects`

返回按现有科目树裁剪后的节点，只保留存在可体验题目的科目及其祖先；每个节点附带 `trial_question_count`。

### GET `/questions?subject_id=<id>`

从人工审核通过、启用且具有有效不可变版本的真实题目中随机取**最多 5 道不同题**；少题按实际数量返回，无题返回 404。

```json
{
  "questions": [
    {
      "id": 101,
      "question_version_id": 1001,
      "question_version": 3,
      "subject_id": 12,
      "subject_code": "ds",
      "subject_name": "数据结构",
      "question_type": "single_choice",
      "content": {"text": "题干"},
      "options": {"A": "选项 A", "B": "选项 B"},
      "knowledge_points": ["线性表"],
      "difficulty": 3,
      "image_url": null
    }
  ],
  "total": 5,
  "subject_id": 12,
  "subject_name": "数据结构",
  "batch_token": "signed-token",
  "expires_at": 1792040000
}
```

响应只包含学生可见题干、选项、知识点、难度与图片地址；不返回答案、解析、导入原文、来源文件或管理字段。

### POST `/evaluate`

```json
{
  "batch_token": "signed-token",
  "answers": [{"question_id": 101, "user_answer": "A"}]
}
```

响应逐题返回 `is_correct`、`user_answer`、`correct_answer`、`analysis`、`reference_only`，并汇总客观题正确/错误、主观题与未作答数量。

- 客观题（单选、多选、判断、填空、多空单选/多选）复用 `is_answer_correct` 与多空 slot 提取，按现有规则判分。
- 主观题 `is_correct=null`、`reference_only=true`，仅供对照参考答案自查，不计入客观正确率。
- 未作答题目返回 `skipped_total`，不视为错误。
- 批次外题目、重复题目、篡改签名、过期或结构异常返回 400。

## 游客批次凭据

- HMAC-SHA256 签名，派生用途固定为 `memograd:guest-practice-batch:v1`，与正式刷题批次凭据隔离。
- 载荷只含版本号、科目、题目与不可变版本 id、签发时间和过期时间；出题后固定 24 小时，不随作答续期。
- 判分只读取凭据内的题目与版本；题目改版后，旧批次仍按原版本判分。
- 正式练习提交接口不接受该凭据。

## 验证状态

| 项目 | 状态 |
| --- | --- |
| 后端游客接口与公式可选鉴权 pytest | 本地通过（见任务记录 `prompts/tasks/current_task.md`） |
| Ruff / compileall | 本地通过 |
| 开发者工具内置 WCC 模板/样式编译 | 本地通过：改造后 practice / practice-result 模板与样式 `success: true`；此前的全量 45 WXML / 59 WXSS 含已删除的 trial 页，当前仓库为 44 / 58。不等于整包构建 |
| 微信开发者工具模拟器 | 已验证共享刷题页 → 共享结果页的游客主流程，仅发起 `/guest/practice/*` 请求；结果页复用 `practice-result/index?guest=1` |
| 真机 | 未验证；需按验收清单复验首次安装、会话失效、登录取消与冷启动恢复 |
| 微信平台重新提审 | 未执行，需单独授权 |

## 相关链接

- [[docs/backend/API_SPEC.md|API_SPEC]] — App API 总规范
- [[docs/frontend/LAUNCH_RESUME.md|LAUNCH_RESUME]] — 启动与登录返回
- [[docs/frontend/UI_RULES.md|UI_RULES]] — 页面与交互规则
- [[docs/planning/GUEST_EXPERIENCE_BACKEND_PLAN.md|GUEST_EXPERIENCE_BACKEND_PLAN]] — 后端实施计划
