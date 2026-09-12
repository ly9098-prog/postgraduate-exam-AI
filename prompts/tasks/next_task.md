你正在我的本地代码仓库和本地 PostgreSQL 数据库中工作。

请完成一次 `question_embeddings` 模型字段规范化改造：

当前：

```text
question_embeddings.embedding_model varchar(128)
```

保存的是类似：

```text
qwen3.7-text-embedding
```

这样的模型名称字符串。

现在我要将其改造成真正的模型配置外键：

```text
question_embeddings.model_id int4 NOT NULL
    REFERENCES admin_ai_model_configs(id)
```

也就是说：

```text
question_embeddings
        │
        │ model_id
        ▼
admin_ai_model_configs.id
```

最终 `question_embeddings` 不应再把模型名称字符串作为模型身份来源。

------

# 一、最高优先级

按以下优先级执行：

```text
数据库可恢复性
>
现有 embedding 数据不丢失
>
正确回填 model_id
>
后端代码完整迁移
>
数据库约束完整
>
删除旧 embedding_model 字符串字段
```

不要直接执行破坏性 ALTER。

必须先审计、备份、验证映射关系，然后迁移。

------

# 二、先检查代码和数据库

不要根据本 Prompt 猜字段。

首先检查仓库中：

- ORM model / entity
- migration
- repository / DAO
- service
- embedding service
- AI model config service
- admin AI model config API
- embedding generation job
- embedding backfill script
- vector search / similarity search
- question recommendation
- tests

搜索所有：

```text
embedding_model
question_embeddings
admin_ai_model_configs
qwen3.7-text-embedding
embedding_dim
content_hash
content_text
```

同时查询真实 PostgreSQL schema。

至少检查：

```sql
\d question_embeddings
\d admin_ai_model_configs
```

或者通过 `information_schema` / `pg_catalog` 获取真实定义。

确认：

1. `question_embeddings.embedding_model` 当前类型
2. 是否允许 NULL
3. 是否存在索引
4. 是否存在 unique constraint
5. `admin_ai_model_configs.id` 是否确实为 `int4`
6. `admin_ai_model_configs` 中哪个字段保存类似：

```text
qwen3.7-text-embedding
```

的模型标识

这个字段可能叫：

```text
model
model_name
model_id
model_key
name
api_model
provider_model
```

必须根据真实数据库确定。

**不要假设字段名。**

------

# 三、数据库修改前必须备份

在任何：

```text
ALTER
UPDATE
DROP
DELETE
```

之前，先创建 PostgreSQL 完整备份。

优先使用仓库已有 backup script。

否则使用：

```bash
pg_dump
```

备份保存到例如：

```text
artifacts/db_backup/
```

文件名：

```text
pre_question_embeddings_model_fk_YYYYMMDD_HHMMSS.dump
```

要求：

- 文件存在
- 文件大小 > 0
- pg_dump exit code = 0
- 不覆盖旧备份
- backup 文件加入 `.gitignore`
- 不提交数据库备份到 Git

备份失败则禁止继续。

------

# 四、先审计现有 embedding_model

正式迁移前查询：

```sql
SELECT
    embedding_model,
    COUNT(*)
FROM question_embeddings
GROUP BY embedding_model
ORDER BY COUNT(*) DESC;
```

然后查询：

```text
admin_ai_model_configs
```

确认每一个现有：

```text
question_embeddings.embedding_model
```

都能映射到**唯一一个**：

```text
admin_ai_model_configs.id
```

例如当前可能存在：

```text
question_embeddings.embedding_model
= 'qwen3.7-text-embedding'
```

如果：

```text
admin_ai_model_configs
```

中对应配置 ID 是：

```text
12
```

最终应该变成：

```text
question_embeddings.model_id = 12
```

------

# 五、映射必须严格唯一

请建立迁移前审计。

对于每一个不同的旧模型名称，输出：

```text
old_embedding_model
matched_admin_ai_model_config_id
matched_model_name
embedding_row_count
match_status
```

`match_status` 至少区分：

```text
exact_unique
unmatched
ambiguous
```

只有：

```text
exact_unique
```

允许自动迁移。

如果出现：

```text
unmatched
```

或：

```text
ambiguous
```

禁止继续执行 DROP / NOT NULL。

停止迁移并报告具体模型名称。

**不要 fuzzy match。**

**不要猜测。**

**不要自动创建新的 admin_ai_model_configs。**

------

# 六、推荐数据库迁移方案

不要直接：

```sql
ALTER COLUMN embedding_model TYPE int4
```

因为旧数据是字符串。

使用安全的 staged migration。

## Phase 1

新增：

```sql
ALTER TABLE question_embeddings
ADD COLUMN model_id int4;
```

此时先允许 NULL。

------

## Phase 2

使用 `admin_ai_model_configs` 的真实模型标识字段进行回填。

类似：

```sql
UPDATE question_embeddings qe
SET model_id = c.id
FROM admin_ai_model_configs c
WHERE qe.embedding_model = c.<REAL_MODEL_IDENTIFIER_COLUMN>;
```

这里：

```text
<REAL_MODEL_IDENTIFIER_COLUMN>
```

必须替换成数据库中的真实字段。

不要照抄占位符。

------

# 七、回填后必须立即验证

执行：

```sql
SELECT COUNT(*)
FROM question_embeddings
WHERE model_id IS NULL;
```

必须为：

```text
0
```

再检查：

```sql
SELECT
    qe.embedding_model,
    qe.model_id,
    c.id,
    c.<model identifier>
FROM question_embeddings qe
LEFT JOIN admin_ai_model_configs c
    ON c.id = qe.model_id
WHERE c.id IS NULL;
```

必须：

```text
0 rows
```

并验证迁移前后总行数完全一致。

例如：

```text
before_count == after_count
```

------

# 八、增加 FK

确认数据完全有效后增加：

```sql
ALTER TABLE question_embeddings
ADD CONSTRAINT fk_question_embeddings_model
FOREIGN KEY (model_id)
REFERENCES admin_ai_model_configs(id);
```

默认：

**不要使用 `ON DELETE CASCADE`。**

模型配置被删除时，不应该顺带删除所有 question embedding。

请检查项目业务语义。

优先考虑：

```text
ON DELETE RESTRICT
```

或 PostgreSQL 默认 `NO ACTION`。

如果项目采用模型配置软删除，则更不需要 CASCADE。

------

# 九、model_id 设置 NOT NULL

只有确认：

```text
model_id IS NULL = 0
```

之后执行：

```sql
ALTER TABLE question_embeddings
ALTER COLUMN model_id SET NOT NULL;
```

------

# 十、索引

检查实际查询模式。

如果 embedding 查询经常按：

```text
question_id + model
```

查询，应考虑建立：

```sql
CREATE INDEX ...
ON question_embeddings(model_id);
```

如果业务逻辑要求同一：

```text
question_id
+
question_type
+
model_id
```

只能存在一个 embedding，则检查当前数据库是否已经通过 unique constraint 实现。

不要盲目建立重复索引。

根据仓库真实查询调整。

------

# 十一、修改后端 ORM / Model

将原来类似：

```text
embedding_model: string
```

改成：

```text
model_id: int
```

并建立 ORM relation：

```text
QuestionEmbedding
    belongs_to
AdminAiModelConfig
```

具体写法遵循项目现有 ORM。

最终模型语义应类似：

```text
QuestionEmbedding {
    id
    question_id
    question_type
    model_id
    model / ai_model_config relation
    embedding_dim
    content_hash
    content_text
    embedding
    ...
}
```

不要在 DB model 中继续把：

```text
embedding_model
```

作为权威模型身份。

------

# 十二、修改所有写入 embedding 的代码

搜索所有创建：

```text
question_embeddings
```

的地方。

旧代码可能类似：

```python
QuestionEmbedding(
    question_id=...,
    embedding_model=model_name,
    embedding_dim=...
)
```

应改成类似：

```python
QuestionEmbedding(
    question_id=...,
    model_id=model_config.id,
    embedding_dim=...
)
```

注意：

embedding service 已经选择了：

```text
admin_ai_model_configs
```

中的某个配置时，应直接沿用该配置的：

```text
id
```

不要再次通过模型名称查询 ID。

即优先：

```text
resolved model config
    ↓
config.id
    ↓
question_embeddings.model_id
```

不要：

```text
config.model_name
    ↓
重新查数据库
    ↓
model_id
```

避免重复解析和名称歧义。

------

# 十三、修改读取代码

所有原来使用：

```text
embedding.embedding_model
```

的地方都要审计。

如果业务只需要模型 ID：

改为：

```text
embedding.model_id
```

如果 API / 日志 / Admin UI 需要显示：

```text
qwen3.7-text-embedding
```

则通过关联：

```text
embedding.model.<REAL_MODEL_IDENTIFIER_COLUMN>
```

获取。

例如 ORM eager load / JOIN：

```text
question_embeddings
JOIN admin_ai_model_configs
ON question_embeddings.model_id = admin_ai_model_configs.id
```

------

# 十四、不要产生 N+1

如果列表接口展示 embedding model 名称：

不要每一行 embedding 单独查询一次 model config。

使用：

- ORM eager loading
- joinedload
- preload
- include
- SQL JOIN

根据项目框架实现。

------

# 十五、修改 embedding 去重 / cache / content hash 逻辑

重点检查是否有代码使用：

```text
embedding_model
```

参与：

- embedding 是否已经存在判断
- UPSERT
- unique key
- cache key
- dedup key
- vector search filter
- model compatibility check
- stale embedding detection

例如旧逻辑：

```text
(question_id, embedding_model)
```

需要改为：

```text
(question_id, model_id)
```

不要遗漏这一步。

否则数据库虽然迁移成功，后端仍可能不断重复生成 embedding。

------

# 十六、embedding_dim 一致性验证

`question_embeddings` 还保存：

```text
embedding_dim
```

请检查：

```text
admin_ai_model_configs
```

是否也配置了 embedding dimension。

如果有：

迁移后验证：

```text
question_embeddings.embedding_dim
```

与对应：

```text
admin_ai_model_configs
```

配置一致。

如果存在不一致：

先报告。

不要自动修改 vector 数据。

------

# 十七、现有 embedding vector 不需要重新生成

这次任务只是：

```text
模型字符串
→
模型配置 FK
```

如果：

```text
old embedding_model
```

能够精确唯一映射到相同模型配置，那么：

**不要删除或重新生成现有 embedding vector。**

例如：

```text
qwen3.7-text-embedding
```

仍然对应同一个 Qwen embedding 模型，只是身份从字符串变成：

```text
admin_ai_model_configs.id
```

那么：

```text
embedding vector
content_hash
content_text
```

本次都无需修改。

注意：

这与之前“知识点体系变化后重新生成 question_embeddings”是两个不同问题。

如果当前 question_embeddings 已经是使用新知识点内容重新生成后的数据，本次只做 model FK migration。

如果仓库实际发现当前 embeddings 仍是旧知识点体系生成的数据，则明确报告，不要把两个任务混在 migration 中偷偷重新生成。

------

# 十八、修改 API Schema

检查是否有 API 返回：

```json
{
  "embedding_model": "qwen3.7-text-embedding"
}
```

如果这个 API 是内部接口，可以考虑调整为：

```json
{
  "model_id": 12,
  "model_name": "qwen3.7-text-embedding"
}
```

如果已有前端依赖 `embedding_model`：

不要直接破坏 API。

可以临时通过 relation 兼容：

```json
{
  "model_id": 12,
  "embedding_model": "qwen3.7-text-embedding"
}
```

其中：

```text
embedding_model
```

是 response compatibility field，不再对应数据库列。

是否保留兼容字段，要根据仓库真实调用者决定。

------

# 十九、Admin 页面

检查：

```text
admin_ai_model_configs
```

相关管理页面。

如果 question embedding 页面会展示模型：

应通过：

```text
model_id -> admin_ai_model_configs
```

展示模型名称。

数据库中不再存冗余模型字符串。

------

# 二十、最终删除旧列

只有在以下全部完成后：

- model_id 全部回填
- FK 生效
- NOT NULL 生效
- 后端已经全面使用 model_id
- tests 通过
- 搜索确认业务代码不再依赖 DB column `embedding_model`

才允许：

```sql
ALTER TABLE question_embeddings
DROP COLUMN embedding_model;
```

删除之前再执行一次全仓库：

```text
embedding_model
```

搜索。

注意：

API DTO 中为了兼容而存在的 `embedding_model` 可以继续存在。

但数据库 ORM 不应再把它映射为真实列。

------

# 二十一、Migration 最好拆成明确步骤

请使用项目现有 migration 框架。

不要只在数据库客户端手工执行 SQL。

至少产生可追踪 migration。

建议逻辑：

```text
Migration A

1. add question_embeddings.model_id nullable
2. audit old model values
3. backfill model_id
4. validate no NULL
5. add FK
6. add needed indexes
7. model_id NOT NULL
8. drop embedding_model
```

如果项目 deployment 流程要求兼容滚动升级，可以拆成两个 migrations：

```text
Migration 1:
add + backfill + FK

代码部署:
改用 model_id

Migration 2:
drop embedding_model
```

优先遵循项目现有部署方式。

------

# 二十二、回滚能力

Migration 必须尽可能支持 rollback。

如果需要恢复旧字段：

可以通过：

```text
model_id
JOIN
admin_ai_model_configs
```

重新构造字符串模型字段。

down migration 的逻辑应类似：

```text
add embedding_model varchar(128)
↓
JOIN model_id -> admin_ai_model_configs
↓
回填模型名称
↓
验证
↓
drop FK/model_id
```

不要写一个无法恢复数据的 down migration。

------

# 二十三、测试

运行项目已有：

```text
unit tests
integration tests
backend tests
lint
typecheck
```

另外增加针对本次改动的测试。

至少覆盖：

### 创建 embedding

给定：

```text
admin_ai_model_configs.id = X
```

新 embedding 保存：

```text
model_id = X
```

### 读取 embedding

能够通过 relation 获取模型配置。

### 不允许无效 ID

插入：

```text
model_id = 不存在的ID
```

数据库应 FK failure。

### model_id NOT NULL

不允许创建：

```text
model_id = NULL
```

### 删除 model config

确认实际 ON DELETE 行为符合预期。

### embedding lookup

原来依赖：

```text
embedding_model
```

的 lookup / upsert / search 仍然正常。

------

# 二十四、数据库最终验证

迁移完成后输出：

```sql
SELECT COUNT(*)
FROM question_embeddings;
```

与迁移前必须一致。

再验证：

```sql
SELECT COUNT(*)
FROM question_embeddings
WHERE model_id IS NULL;
```

必须：

```text
0
```

验证孤儿 FK：

```sql
SELECT COUNT(*)
FROM question_embeddings qe
LEFT JOIN admin_ai_model_configs c
  ON qe.model_id = c.id
WHERE c.id IS NULL;
```

必须：

```text
0
```

再输出类似：

```sql
SELECT
    qe.model_id,
    c.<real_model_identifier>,
    COUNT(*) AS embedding_count,
    MIN(qe.embedding_dim),
    MAX(qe.embedding_dim)
FROM question_embeddings qe
JOIN admin_ai_model_configs c
  ON c.id = qe.model_id
GROUP BY qe.model_id, c.<real_model_identifier>
ORDER BY qe.model_id;
```

让我看到最终模型分布。

------

# 二十五、最终目标 Schema

最终 `question_embeddings` 应类似：

```text
id
question_id
question_type
model_id                int4 NOT NULL FK
embedding_dim
content_hash
content_text
embedding
...
```

其中：

```text
model_id
```

引用：

```text
admin_ai_model_configs.id
```

不再存在数据库字段：

```text
embedding_model varchar(128)
```

模型名称只存储于：

```text
admin_ai_model_configs
```

中。

------

# 二十六、最后输出报告

完成后给我：

## 数据库

- backup 路径
- migration 文件
- migration 前 embedding row count
- migration 后 embedding row count
- old embedding_model → model_id 映射表
- NULL model_id 数
- orphan model_id 数
- FK 名称
- index 名称

## 后端

列出所有修改文件，并说明：

```text
ORM
repository
service
embedding generation
vector search
API DTO
admin API
tests
```

哪些发生了变化。

## 验证

列出实际执行的：

```text
migration
SQL verification
tests
lint
typecheck
```

以及结果。

## Git

运行：

```bash
git diff
git status
```

确认：

- backup 未进入 Git
- 没有密码
- 没有连接字符串
- 没有无关修改

不要只告诉我“应该怎么改”。

请实际：

**审计 → 备份 → 建 migration → 回填 → 改后端 → 执行 migration → 验证 → 测试 → 报告。**
