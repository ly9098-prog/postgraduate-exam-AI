请对刚完成的 PDF 指定页码范围导入修复进行第二轮验收审计。不要假设上一轮实现正确，必须直接检查代码、运行测试，并修复发现的问题。

# 目标

确认上一轮实现真正满足端到端验收条件，而不只是底层纯函数测试通过。

# 一、先核查实现完整性

逐项检查并明确回答：

1. `PipelineUploadResponse` 和前端 `ImportPipelineUploadResponse` 是否都包含：

```text
page_range
```

1. 以下两个接口是否具有完全一致的页码语义、校验和状态响应：

```text
POST /api/admin/v1/imports/upload
POST /api/v1/import/pipeline/upload
```

1. 非 PDF 文件携带 `page_start` 或 `page_end` 时，是否明确返回 4xx，而不是静默忽略。
2. 页码越界异常是否不会被类似下面的逻辑吞掉：

```python
except Exception:
    pass
```

1. `page_range` 是否在以下全部状态中保持存在：

```text
queued
processing
failed
completed
cancelled（如果支持）
```

1. `_set_pipeline_store()` 或其他覆盖式状态更新是否可能删除 `page_range`。
2. `page_range` 是否在上传响应中立即返回，而不是必须等第一次轮询。
3. 整份 PDF 导入时是否也返回：

```text
effective_start = 1
effective_end = total_pages
selected_page_count = total_pages
```

1. 题目最终保存的 `source_page_start/source_page_end` 是否仍然是原 PDF 物理页码。
2. 分块统计中的总页数是否等于：

```text
effective_end - effective_start + 1
```

而不是 `effective_end`。

# 二、检查前端请求

检查：

```text
admin-frontend/src/app/(admin)/imports/tasks/page.tsx
```

确认最终请求满足：

- `FormData` 中只有 `file`；
- 配置通过 `toQuery()` 进入 URL；
- 没有发送空字符串、`null`、`undefined` 字符串；
- 非 PDF 不发送 `page_start/page_end`；
- 不再发送 `ocr_mode`；
- `ImportPipelineUploadResponse` 正确声明 `page_range`；
- 上传成功后的首次界面就能显示生效范围；
- 页码输入在任务运行期间被禁用；
- 切换到非 PDF 时会清空旧页码；
- `parseProgressPercent()` 不依赖 React 组件内部状态，能够独立测试。

# 三、补充缺失测试

## 1. 后端 API 集成测试

使用 FastAPI 测试客户端或项目现有异步客户端，至少覆盖：

### 管理端上传

上传一个多页 PDF，请求：

```text
/imports/upload?page_start=2&page_end=4&import_mode=book&enable_ai_repair=false&confidence_threshold=0.7
```

验证：

- service 收到正确类型的参数；
- multipart 中只需要文件；
- 响应 `page_range` 为第 2–4 页；
- `selected_page_count == 3`。

### 公共端上传

对公共端接口执行等价测试，确保行为一致。

### 错误场景

覆盖：

- 非 PDF 携带页码；
- `page_start=0`；
- `page_start > page_end`；
- 起始页超过总页数；
- 结束页超过总页数。

验证返回明确的 4xx 和可理解错误信息。

## 2. 文本 PDF 端到端测试

创建 5 页 PDF，每页带唯一文本：

```text
PAGE_ONE
PAGE_TWO
PAGE_THREE
PAGE_FOUR
PAGE_FIVE
```

指定第 2–4 页，验证：

- 只提取第二、三、四页；
- 不包含第一、五页文字；
- block 页码为 2、3、4；
- 后续题目来源页码没有被重编号。

## 3. OCR 范围测试

通过 mock 或小型扫描 PDF 验证：

- 只 OCR 选中页面；
- 范围外页面不渲染、不调用 OCR；
- 页码保持原物理页码；
- PDF 共 100 页但只选择 10 页、OCR 上限为 20 时，不产生截断警告；
- 选择 51 页、OCR 上限为 20 时，警告为 `20/51 selected pages`。

## 4. 状态持久化测试

构造状态流转：

```text
queued → processing → completed
queued → processing → failed
```

验证每个状态响应中的 `page_range` 不丢失。

如果存在恢复接口，增加指定范围 chunked 任务的恢复测试。

## 5. 前端测试

使用仓库现有前端测试框架。若没有，则只引入项目可接受的最小测试配置。

至少覆盖：

```typescript
parseProgressPercent("3/10 pages") === 30
parseProgressPercent("3/10") === 30
parseProgressPercent("30%") === 30
parseProgressPercent("") === 0
parseProgressPercent("invalid") === 0
parseProgressPercent("300%") === 100
```

页码验证覆盖：

- 空值；
- 正整数；
- 0；
- 负数；
- 小数；
- 非数字；
- start > end。

请求构造覆盖：

- PDF 请求的参数位于 Query；
- FormData 只包含文件；
- 非 PDF 不包含页码参数；
- 不包含 `ocr_mode`。

# 四、运行完整验证

不要只运行新增测试。根据仓库实际脚本，运行所有可用检查：

```text
完整后端测试套件
相关导入流水线测试
前端单元测试
TypeScript 类型检查
ESLint
Next.js production build
```

如果完整后端测试耗时过长，仍必须至少运行：

- 全部 import/pipeline 相关测试；
- API 测试；
- service 测试；
- orchestrator 测试。

# 五、发现问题时直接修复

发现以下任何问题时不要只报告，直接修改：

- API 两端行为不一致；
- 上传响应类型缺字段；
- page_range 在状态更新中丢失；
- 非 PDF 页码被忽略；
- OCR 截断误报；
- chunk 统计错误；
- 前端类型不完整；
- Query 参数构造错误；
- 生产构建失败；
- 测试未覆盖关键验收场景。

# 六、最终输出格式

最终必须提供：

## 实际检查结论

逐项说明完整支持、部分支持或已修复。

## 追加修改

列出本轮实际修改的文件和原因。

## 测试结果

必须列出执行过的具体命令及结果，例如：

```text
pytest backend/tests/... — 54 passed
npm run test — 18 passed
npm run typecheck — passed
npm run lint — passed
npm run build — passed
```

不要只写“All tests pass”。

## 最终端到端请求示例

提供一个实际有效的请求示例，说明：

- 参数位于 URL Query；
- 文件位于 multipart；
- 响应中的 `page_range` 示例。

## 剩余风险

没有剩余风险时明确写“未发现已知剩余风险”；存在限制时逐项说明。