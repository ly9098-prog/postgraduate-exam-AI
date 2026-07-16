# Claude Code 任务：补齐数据结构题库看图题图片链路

你正在修改一个 FastAPI + SQLAlchemy 后端。请先阅读现有代码，再直接实现、测试并提交修改，不要只给建议。

## 一、任务目标

为已经导入到 `question_imports` 的数据结构题库补齐原题图片，使图片能够：

1. 从原始 `ds_sc.pdf` 对应页截取并上传；
2. 在导入审核页中随题目展示；
3. 题目发布到 `questions` 后仍然保留；
4. 学生端 `/api/v1/questions`、`/random`、`/{id}` 返回的数据中可获得图片；
5. 全流程幂等，不改变题目审核状态，不自动发布题目。

## 二、已审计确认的事实

### 1. 页码其实没有丢失

`question_imports.source_page_start` 当前全为 `NULL`，但全部 513 条记录的真实页码都已保存在：

```python
qi.raw_data["source"]["source_page_start"]
```

513 条记录覆盖 PDF 第 1–513 页，页码唯一且完整。因此：

- 不要做 OCR 文本匹配；
- 优先从上述嵌套字段读取并回填 `source_page_start/source_page_end`；
- 同时兼容历史数据的顶层 `page_start/source_page/page` 字段。

请修复 `services/admin_import_service.py` 中历史数据兜底逻辑：它目前只检查 `raw_data` 顶层，没有检查 `raw_data["source"]`。

### 2. 当前代码已有可复用能力

可复用：

- `services/storage_backend.py`
- `services/visual_region_cropper.py`
- `services/formula_image_cropper.py`
- `QuestionImport.parsed_content`
- `Question.content`
- `Question.image_url`
- `features/question_publish_service.py` 对 `render_mode="segments"` 与 `segments` 的保留逻辑
- 学生端 `_sanitize_content()` 不会删除 `segments`

### 3. 当前方案中的错误点

不要把题图写入：

```python
parsed_content["images"]
```

现有 normalizer/publisher 不保留该字段，发布后会丢失。

不要使用 `formula_graph_assets` 存题图。该表：

- 强制关联 `formula_card_id`
- 属于公式卡片域
- 不适合关联 `question_imports` 或 `questions`

当前 `Question.image_url` 虽然存在，但发布服务没有赋值，`schemas/question.py::QuestionResponse` 也没有返回该字段。

### 4. 源 PDF 的持久化问题

当前上传的代码包中没有 `ds_sc.pdf`，数据库只保存了文件名 `ds_sc.pdf`，没有可读取的持久化绝对路径。

本次实现必须提供显式参数：

```bash
--pdf /absolute/path/to/artifacts/data-structure-import/source/ds_sc.pdf
```

不要假设仅凭 `source_file` 就能找到 PDF。

## 三、推荐的数据结构

以 `content.segments` 为学生端的规范渲染结构，同时同步 `Question.image_url` 兼容旧客户端。

补图后 `QuestionImport.parsed_content` 应类似：

```json
{
  "text": "原题干文本",
  "render_mode": "segments",
  "segments": [
    {
      "type": "text",
      "text": "原题干文本"
    },
    {
      "type": "image",
      "url": "https://.../question-assets/202607/ds_sc/q_229_p108_xxx.png",
      "alt": "题目原图",
      "display": true,
      "region_type": "illustration",
      "asset_kind": "question_figure",
      "source_page": 108,
      "bbox": [0, 0, 100, 100],
      "coordinate_space": "pdf_points",
      "crop_mode": "auto_region",
      "checksum": "..."
    }
  ]
}
```

要求：

- 已有文本 segment 时不要重复添加文本；
- 已存在相同 `asset_kind + source_page + checksum` 的图片时跳过；
- 同一题重复执行脚本不能生成重复 segment；
- 图片失败时不得破坏原 `parsed_content`；
- `source_snapshot_url` 仅用于审核快照，不得替代学生端图片 segment。

## 四、需要实现的代码

### A. 页码解析与回填

新增统一函数，例如：

```python
def resolve_source_page(qi: QuestionImport) -> int | None:
    ...
```

优先级：

1. `qi.source_page_start`
2. `raw_data["source"]["source_page_start"]`
3. `raw_data["source"]["page_start"]`
4. `raw_data["source"]["page"]`
5. `raw_data["page_start"]`
6. `raw_data["source_page"]`
7. `raw_data["page"]`

实现批量回填：

- 仅更新空字段；
- `source_page_end` 为空时设为同一页；
- 验证页码在 `1 <= page <= len(pdf)`；
- 输出异常记录；
- 支持 `--dry-run`；
- 不改 `status/question_id/reviewed_at`。

### B. 补图脚本

新增：

```text
scripts/backfill_question_images.py
```

建议 CLI：

```bash
python scripts/backfill_question_images.py \
  --db sqlite+aiosqlite:///path/to/postgraduate.db \
  --pdf artifacts/data-structure-import/source/ds_sc.pdf \
  --ids 229,369,371,380,388,395,397,400,402,405,407,411,412,451,457,460,461,472,480 \
  --mode auto \
  --dry-run
```

参数至少包括：

- `--db`
- `--pdf`
- `--ids`
- `--mode auto|full-page`
- `--dpi`，默认 200
- `--dry-run`
- `--force`
- `--output-report`

执行步骤：

1. 校验 PDF 存在、页数正确；
2. 解析/回填页码；
3. 渲染对应 PDF 页；
4. 尝试裁剪题图；
5. 上传图片；
6. 幂等写入 `parsed_content.segments`；
7. 输出 JSON/CSV 报告；
8. 每题独立事务或 savepoint，单题失败不影响其他题。

### C. 裁剪策略

实现两级策略：

#### 优先：自动图形区域

尽量复用现有 visual region/layout 能力。若能获得 bbox：

- 在 PDF point 坐标中保留 bbox；
- 加适量 padding；
- 200 DPI 输出；
- 自动去除大面积空白边缘；
- 最长边不超过合理尺寸；
- 保留图中文字、节点、权重和箭头。

#### 回退：整页截图

如果没有可靠 bbox：

- 使用整页图；
- `crop_mode="full_page_fallback"`；
- `requires_review=true`；
- 报告中标记人工复核；
- 不要把整页截图伪装成精确题图。

不要用 OCR 文本匹配来寻找页码。

### D. 存储

不要写入 `formula_graph_assets`。

可以复用或泛化 `StorageBackend`，但不要继续把题图语义上硬编码为公式图。推荐：

- 新增通用 namespace/prefix 支持；
- 本地目录：`static/question-assets/...`
- URL：`/static/question-assets/...`
- 在 `main.py` mount 对应静态目录；
- COS 使用独立前缀 `question-assets/`。

文件名必须包含：

- import id
- page
- 内容哈希

例如：

```text
question-assets/202607/ds_sc/q_229_p108_a1b2c3d4.png
```

### E. 发布链路

修改所有会创建 `Question` 的发布路径，至少检查：

- `features/question_publish_service.py`
- `features/question_import_writer.py`

要求：

1. `parsed_content.render_mode/segments` 完整保留；
2. 从 image segments 提取 URL，写入：

```python
Question.image_url = [...]
```

3. 不接受仅写 `parsed_content["images"]`；
4. 重复发布检测不能因图片 URL 改变而改变题干 hash；
5. 现有 pending 记录补图后仍保持 pending。

### F. API Schema

修改：

```text
schemas/question.py
```

为 `QuestionResponse` 增加：

```python
image_url: list | None = None
```

确保以下接口均返回图片：

- `GET /api/v1/questions`
- `GET /api/v1/questions/random`
- `GET /api/v1/questions/{question_id}`
- `GET /api/v1/questions/{question_id}/detail`

其中 `content.segments` 是主渲染数据，`image_url` 是兼容字段。

### G. 审核接口

确保管理员导入审核接口返回：

- 回填后的 `source_page_start/source_page_end`
- `parsed_content.segments`
- 图片 URL
- `crop_mode`
- `requires_review`

修复 `admin_import_service` 的嵌套页码兜底。

## 五、目标题目清单

### 明确依赖原图：19 题

```text
229,369,371,380,388,395,397,400,402,405,407,411,412,451,457,460,461,472,480
```

页码映射：

```text
229->108
369->286
371->288
380->297
388->307
395->314
397->316
400->319
402->321
405->324
407->326
411->330
412->331
451->370
457->376
460->379
461->380
472->391
480->399
```

### 可选补图：1 题

```text
345->262
```

该题的邻接矩阵已经 OCR 成文本，但原始矩阵排版图片可作为增强。默认可纳入，但报告中标记为 `optional_visual`。

### 误报/不应自动补图：7 题

```text
337,343,346,347,365,379,408
```

这些题中的“图G”是数学对象名称，不代表“下图”。其中 379 的集合/边集 OCR 文本可能需要人工修复，但不应通过整页题图掩盖文本问题。

脚本对上述 7 题默认跳过并写明原因；只有 `--force` 时才处理。

## 六、测试要求

新增自动化测试，至少覆盖：

1. 从 `raw_data.source.source_page_start` 解析页码；
2. 513 条数据可回填为 1–513；
3. 越界页码被拒绝；
4. `parsed_content["images"]` 不作为正式路径；
5. image segment 可被 normalizer/publisher保留；
6. `Question.image_url` 从 segments 同步生成；
7. 学生 API 返回 segments 和 image_url；
8. `_sanitize_content` 删除审核快照但保留 image segment；
9. 重复运行不重复上传、不重复插入 segment；
10. 单题裁剪失败时原数据不变；
11. `--dry-run` 不修改数据库和文件；
12. 执行补图后 `questions` 数量仍为 0，所有 513 条仍为 pending；
13. 发布测试夹具后，正式题目的图片仍可访问。

使用临时 SQLite、最小 PDF fixture 和 monkeypatch storage，测试不得依赖真实 513 页 PDF。

## 七、安全与数据保护

执行真实数据库前：

- 自动生成数据库备份；
- 默认 `--dry-run`；
- 仅处理 `status="pending"` 且 `question_id IS NULL` 的记录；
- 不调用 approve/publish；
- 不修改答案、解析、题型、学科和 hash；
- 日志禁止输出敏感配置；
- 图片上传成功但 DB 写入失败时，清理孤儿文件；
- DB 写入成功后再提交；
- 提供可逆回滚报告。

注意：当前代码中没有可见的 `AUTO_PUBLISH` 配置实现，且部分审核函数会直接发布。补图脚本不得调用这些审核函数。

## 八、验收标准

完成后必须满足：

1. `source_page_start/source_page_end` 正确回填；
2. 19 道明确看图题拥有可访问图片 segment；
3. 345 可配置处理；
4. 7 道误报默认跳过；
5. 运行脚本前后 `questions` 仍为 0；
6. 513 条记录仍为 pending；
7. 发布任一测试题后，`Question.content.segments` 和 `Question.image_url` 均保留图片；
8. 学生 API 能返回图片；
9. 脚本重复运行结果不变；
10. 生成审计报告，列出每题：
   - import_id
   - page
   - crop_mode
   - bbox
   - image_url
   - checksum
   - status
   - skip/failure reason

## 九、交付内容

请直接修改代码，并在最终回复中给出：

1. 修改文件列表；
2. 数据库迁移/兼容说明；
3. 执行命令；
4. 测试命令和结果；
5. dry-run 报告摘要；
6. 真实执行前仍缺少的外部文件或配置；
7. 未解决风险。

不要只返回设计方案。