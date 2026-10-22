# 审核队列语义与兼容基线

核对日期：2026-10-22。对应重构计划阶段 0；范围仅限 Admin 导入审核队列及审核动作，不表示导入流水线、OCR 或题库治理全域已完成审查。

## 1. 入口与消费者

| 用例 | 入口与实现 | 消费者 | 处理决定 |
| --- | --- | --- | --- |
| 审核队列读取 | `GET /api/admin/v1/imports/review-queue` → `admin_import_service.list_review_queue` | `admin-frontend/src/app/(admin)/imports/review/page.tsx` | 保留现有 query key、debounce、分页、`placeholderData` 和筛选参数拼装。 |
| 单题通过/驳回 | `POST /imports/questions/{id}/approve|reject` | 审核页确认弹层与 feature mutation | 保留请求、幂等边界、缓存失效和单题成功关闭抽屉。 |
| 整批通过/驳回 | `POST /imports/{batch_id}/approve|reject` | 审核页批次操作 | 保留服务端批量事务与客户端 Idempotency-Key；前端只在无已选 ID 时走整批接口。 |
| 已选题目批量通过/驳回 | 逐题 approve/reject，6 并发分块 | `review-action-requests.ts` | 保留输入 ID 顺序、部分失败汇总和选择集原样发送。 |
| 低风险批量通过 | `POST /imports/{batch_id}/approve-low-risk` | 审核页确认弹层 | 保留服务端 `risk_level=low` 判定、跳过计数和原因上限。 |
| 详情读取 | `GET /imports/questions/{id}` | 审核抽屉 | 详情数据优先于 completed item 和队列摘要；本批未改。 |

注册以 `backend/app/api/router.py` → `backend/app/api/admin/router.py` → `backend/app/api/v1/admin_imports.py` 和当前页面为准；未用旧文档或静态图存在性推断调用方。

## 2. 服务端排序、过滤与分页

- 默认排序为 `created_at DESC, id DESC`；指定批次且未显式传 `sort` 时改为来源图片顺序、页码、来源序号和 ID。
- `risk_level` 在摘要行完成动态派生后、分页之后于内存过滤；`total` 在过滤前计算，`paginated_response` 的 `total_pages` 也只由该 `total` 推导。因此风险筛选下的 `items` 数量可以少于页大小，`total_pages` 也可能大于实际可展示页数。这是现有行为，不能在等价重构中顺手修正。
- `answer_status`、`question_type`、科目、来源、关键词和状态在 SQL 侧过滤；`batch_id` 缺省时使用 URL 参数。前端仍使用 300ms debounce 的关键词和 page_size 50。
- `placeholderData` 保留上一查询结果；筛选或分页切换期间，页面可以短暂展示旧列表而与新 query key 不一致。该过渡态属于既有 UI 行为，尚未用浏览器测试验证。

## 3. 客户端选择集

审核页的 `selectedIds` 是独立本地集合：

- 点击单题只切换该 ID；全选按当前 `items` 全量替换，若当前页已全选则清空。
- 下拉筛选会通过 `updateFilter` 清空选择；关键词输入与全量重置均经由 `review-filter-selection.ts` 的策略入口更新，只触发页码回到 1，不清选择集。全量重置还会关闭抽屉和编辑状态。上述差异由当前页面源码与 `review-filter-selection.test.ts` 确认，需保留到后续明确行为决策。
- 翻页本身不清空选择；队列刷新也不过滤失效 ID。`allChecked` 只判断当前页 ID 是否都在集合中，但批量操作发送整个集合。
- 这与公式页的 `safeSelectedIds`（按当前列表 ID 过滤）不同。审核页当前行为意味着跨页/跨刷新保留的 ID 仍可能被批量提交，不能把它当作可随手改掉的实现细节。
- 单题和批量审核成功后，mutation 的 `onReset` 清空选择、确认动作和驳回原因。逐题批量即使全部失败也会汇总为成功结果并清空；只有请求 Promise 被拒绝进入 `onError` 时才不清空。

后续若决定过滤失效 ID，必须先明确这是行为修复还是兼容重构，并补跨页、队列刷新、空页和批量请求载荷测试；本基线不做该变更。

## 4. 审核返回与提示

| 动作 | 返回形态 | 当前提示 |
| --- | --- | --- |
| 单题通过 | `AdminImportActionResponse` | `导入题目 #<动作 ID> 已通过审核。`，随后关闭抽屉 |
| 单题驳回 | 同上 | `导入题目 #<动作 ID> 已驳回。`，随后关闭抽屉 |
| 已选/整批通过 | 成功响应或无 `errors` 的结果 | `批量审核通过完成，影响 N 条导入题目。` |
| 已选/整批驳回 | 同上 | `批量驳回完成，影响 N 条导入题目。` |
| 已选批量部分失败 | 客户端 `Promise.allSettled` 汇总 `{affected_count, errors[]}` | `批量<动作>部分完成：成功 N，失败 M（#id…）。`，按输入 ID 顺序汇总客户端逐题失败 |
| 低风险批量通过 | `{affected_count, skipped_count, skipped_reasons[]}` | 固定计数；仅 skipped_count>0 追加“部分高风险/需检查题已跳过” |

当前页面在批量结果缺 `affected_count` 时显示 0；这是防御性回退，不是服务端正常响应。低风险提示不展示 `skipped_reasons` 明细。

审核 mutation 成功后的顺序为：页面提示/按需关闭抽屉 → 清空选择/确认/驳回原因 → 失效 `import-review-queue`、`import-batches`，非驳回动作再失效 `questions`。逐题批量中被 `Promise.allSettled` 汇总的部分或全部失败仍会 resolve 为结果并进入成功清理；只有 mutation Promise 本身被拒绝进入 `onError` 时，才只显示错误且不清选择或失效缓存。未识别的运行时动作返回防御性提示且不关闭抽屉，但仍按既有成功清理路径清空选择/确认/驳回原因，提示用户刷新确认结果。

## 5. 已确认的边界与缺口

- `re_pending`、编辑后自动待重审、已入库题目重审/版本回滚仍是设计预留；审核页没有可用写入路径。
- 真实权限拒绝、真实 Admin 登录、弹层取消/确认、`window.confirm` 未保存保护、跨页选择和队列刷新后的批量载荷尚无浏览器验收。
- 风险筛选的 `total` 与分页口径是服务端现状；若后续修复，必须单独评估 API 兼容和分页 UI。
- 当前选择集跨刷新保留失效 ID 是已确认现状，不是本批引入的回归，也不能由现有纯规则/reducer 测试证明浏览器行为。

## 6. 可执行基线

- `admin-frontend/src/app/(admin)/imports/review/review-query-state.test.ts`：筛选默认/重置、URL 批次回退和参数拼装。
- `admin-frontend/src/app/(admin)/imports/review/review-action-requests.test.ts`：单题/批次路径、6 并发分块、部分失败与 Idempotency-Key。
- `admin-frontend/src/app/(admin)/imports/review/hooks/use-review-action-mutation.test.ts`：成功回调/reset/缓存失效顺序与失败不清缓存。
- `admin-frontend/src/app/(admin)/imports/review/review-action-feedback.test.ts`：四类动作提示、部分失败顺序、缺字段回退和低风险跳过后缀。
- `admin-frontend/src/app/(admin)/imports/review/review-action-dialog-state.test.ts`：打开/取消、选择替换与函数式连续更新、成功 reset 和消息保留。
- `admin-frontend/src/app/(admin)/imports/review/review-confirm-dialog-state.test.ts`：确认弹层文案、危险态、选择数说明和驳回输入条件。

本基线来自源码、Vitest/类型/构建及静态对照；未运行真实 Admin 浏览器、真实服务端、真实权限拒绝或真机，不能据此宣称审核流程生产验收完成。
