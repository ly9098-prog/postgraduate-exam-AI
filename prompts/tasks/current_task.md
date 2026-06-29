## 🧪 pgvector 真实验收执行任务

你是一个后端测试与数据库验证工程师，请在当前已部署的 pgvector 环境中执行**真实功能验收**，禁止使用 dry-run 或 mock。

------

## 🎯 一、核心目标

验证 pgvector 功能链路是否真实可用：

1. embedding 写入 PostgreSQL 成功
2. vector 类型 CAST 正确
3. similarity search 可执行
4. 事务 commit 正常
5. 查询结果可跨 session 读取
6. VECTOR_MODE=off 不影响基础功能

------

## 🧱 二、执行步骤（必须按顺序）

### Step 1：小批量真实回填（10条）

- 从题库随机或按 id 顺序取 10 条 question
- 调用 embedding API（真实请求）
- 写入 question_embeddings 表
- 使用：

```sql
CAST(:emb AS vector)
```

- 每条必须：
  - 成功写入
  - 不报 SQL 错误
  - 事务提交成功

------

### Step 2：数据库一致性检查

执行 SQL：

```sql
SELECT COUNT(*) FROM question_embeddings;

SELECT question_id, vector_dims(embedding)
FROM question_embeddings
LIMIT 20;
```

要求：

- 所有 vector_dims == 1024
- 无 NULL
- 无异常数据

------

### Step 3：真实向量检索测试

随机取一条 embedding：

```sql
SELECT embedding FROM question_embeddings LIMIT 1;
```

执行 similarity query：

```sql
SELECT question_id
FROM question_embeddings
ORDER BY embedding <=> CAST(:query_emb AS vector)
LIMIT 5;
```

要求：

- SQL 可执行
- 返回排序结果
- 无类型错误

------

### Step 4：事务验证

验证：

- commit 后重新连接 session 数据仍存在
- rollback 不污染数据
- 单条失败不会影响 batch

------

### Step 5：VECTOR_MODE=off 验证

确保：

- 关闭 vector mode 后系统正常运行
- fallback 路径正常
- 无 embedding 调用错误

------

## 🧪 三、验收标准（必须全部通过）

必须满足：

- ✔ 10条 embedding 全部写入成功
- ✔ vector 维度全部一致（1024）
- ✔ similarity query 正常执行
- ✔ 无 SQLAlchemy binding error
- ✔ 无事务回滚丢数据
- ✔ off 模式系统完全稳定

------

## 🚨 四、失败处理规则

如果出现以下任意情况：

- SQL binding error
- vector cast error
- 维度不一致
- 写入后查询不到数据
- session rollback 导致数据丢失

必须立即停止，并输出：

```text
BLOCKER: pgvector chain not stable
```

------

## 📦 五、输出报告格式

执行结束必须输出：

### 1. 写入结果

- 成功数量
- 失败数量
- 失败原因

### 2. 查询结果

- similarity top5 示例

### 3. 事务验证结果

- commit/rollback 是否正常

### 4. 风险结论

- PASS / FAIL
- 是否允许进入 shadow

------

## ⚠️ 六、重要约束

- 禁止 dry-run
- 禁止 mock embedding
- 必须使用真实 PostgreSQL
- 必须使用真实 pgvector operator `<=>`
- 必须使用 CAST(:emb AS vector)

------

