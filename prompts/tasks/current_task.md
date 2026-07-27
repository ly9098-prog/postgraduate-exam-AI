你是一名资深 Python/FastAPI 后端安全工程师。请直接检查并修改当前项目，解决 AI 模型 API Key 在数据库中可能以明文存储的问题。

## 一、已知问题

重点检查以下文件及其所有调用方：

- `app/models/admin_ai_config.py`
- `app/services/admin_ai_config_service.py`
- `app/services/model_config_resolver.py`
- `app/services/vector_config_service.py`
- `app/models/admin_vector_config.py`
- `app/api/v1/admin_ai_config.py`
- `app/api/v1/admin_vector_config.py`
- `app/schemas/admin_ai_config.py`
- `app/core/config.py`
- `app/services/production_config_validator.py`

当前 `encrypt_api_key()` 和 `decrypt_api_key()` 存在严重的 fail-open 行为：

```python
if f is None:
    return plain
```

当 `AI_CONFIG_ENCRYPT_KEY` 未配置或格式无效时，API Key 会直接以明文写入名为 `api_key_encrypted` 的字段。

当前数据库中需要关注的字段包括：

- `admin_ai_model_configs.api_key_encrypted`
- `admin_vector_configs.embedding_api_key_encrypted`

不要输出、打印、复制或记录数据库中的任何真实 API Key。

## 二、改造目标

实现可靠、可迁移、可测试的敏感凭据加密方案，必须满足：

1. API Key 绝不能因为加密配置缺失、格式错误或加密失败而以明文写入数据库。
2. 生产环境缺少有效加密主密钥时必须启动失败。
3. 已存在的明文 API Key 可以安全迁移为密文。
4. 迁移必须幂等，重复执行不能重复加密。
5. 加密密钥不能写入数据库、源代码、日志或 API 响应。
6. API 响应、审计日志、异常信息和应用日志中不得泄露 API Key。
7. 保持现有模型配置、向量配置和 AI 调用功能正常。
8. 同时兼容 SQLite 开发环境和 PostgreSQL 生产环境。

## 三、加密模块

将加解密逻辑从 ORM Model 中拆出，建立独立模块，例如：

```text
app/core/secret_crypto.py
```

使用 `cryptography.fernet.Fernet`，或者项目中已有的等价成熟加密库。

禁止自行实现加密算法。

建议提供以下接口，具体命名可根据项目规范调整：

```python
class SecretEncryptionError(RuntimeError):
    pass

class SecretDecryptionError(RuntimeError):
    pass

def encrypt_secret(plaintext: str) -> str:
    ...

def decrypt_secret(ciphertext: str) -> str:
    ...

def is_encrypted_secret(value: str) -> bool:
    ...
```

### 强制要求

- 加密配置缺失时，`encrypt_secret()` 必须抛出明确异常，绝不能返回明文。
- 加密配置无效时必须抛出明确异常。
- 解密失败时不得返回空字符串伪装成“未配置”。
- 解密失败不得自动使用原字符串作为明文。
- 不要通过是否以 `gAAAA` 开头作为唯一的长期数据格式判断。
- 数据库存储建议使用带版本的 envelope 格式，例如：

```text
enc:v1:<fernet-token>
```

如实现密钥轮换，也可以加入 key id：

```text
enc:v1:<key-id>:<fernet-token>
```

- `is_encrypted_secret()` 应根据明确的版本前缀判断。
- 普通业务运行期间不得自动把无前缀字符串当作明文凭据使用。
- 对旧明文的兼容只能放在专门的数据迁移流程中。

不要使用哈希代替加密，因为系统调用第三方模型 API 时需要恢复原始 API Key。

## 四、配置校验

继续支持现有环境变量：

```text
AI_CONFIG_ENCRYPT_KEY
```

要求：

1. 验证它是否是合法的 Fernet key。
2. 不要从 `APP_SECRET`、数据库密码或其他弱配置直接派生加密密钥。
3. 不要提供代码内默认密钥。
4. 在 production 或 cloud_api 等受限部署环境中：
   - 未配置时启动失败；
   - 格式错误时启动失败；
   - 错误信息可以说明变量名称，但不得包含变量值。
5. 开发环境未配置密钥时，可以允许应用启动，但任何保存 API Key 的操作必须失败并返回清晰、安全的错误，绝不能保存明文。

将检查加入现有的：

```text
app/services/production_config_validator.py
```

并复用项目已有的 restricted environment 判断方式。

如项目存在 `.env.example` 或部署文档，请增加配置示例，但不要填写真实密钥。

可在文档中给出生成方式：

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## 五、数据库明文迁移

检查项目的 Alembic 结构和迁移规范，增加安全的数据迁移方案。

迁移范围至少包括：

```text
admin_ai_model_configs.api_key_encrypted
admin_vector_configs.embedding_api_key_encrypted
```

迁移逻辑：

1. 空值跳过。
2. 已是 `enc:v1:` 格式的值跳过。
3. 旧值视为历史明文，仅在迁移程序中读取。
4. 使用当前有效的 `AI_CONFIG_ENCRYPT_KEY` 加密后写回。
5. 整个迁移尽可能在事务中执行。
6. 任意一条加密失败时回滚，不能留下部分迁移状态。
7. 重复执行迁移时不得二次加密。
8. 日志只能记录：
   - 处理记录数量；
   - 跳过数量；
   - 成功数量；
   - 失败记录的主键。
9. 日志不得记录：
   - 明文；
   - 密文；
   - API Key 前缀；
   - API Key 长度；
   - 请求体。
10. 迁移前检查现有字段长度是否足以保存带版本前缀的 Fernet 密文；如不足，通过 Alembic 扩容。
11. 不要在迁移文件或测试 fixture 中写入真实数据库凭据。

如果项目规范不适合在 Alembic upgrade 中依赖运行时密钥，则增加一个明确、幂等的 CLI 迁移命令，例如：

```bash
python -m app.cli.encrypt_ai_secrets
```

该命令应：

- 默认执行真实迁移前展示待处理记录数量；
- 支持 `--dry-run`；
- 缺少加密密钥时直接退出；
- 失败时返回非零退出码；
- 不输出任何凭据；
- 可安全重复执行。

优先采用最符合当前项目部署流程的方案，不要同时保留两套互相冲突的迁移入口。

## 六、业务层改造

替换所有对旧函数的调用：

```python
encrypt_api_key
decrypt_api_key
```

重点检查：

- 模型创建；
- 模型更新；
- 默认模型 seed；
- 环境变量同步；
- 模型连接测试；
- 模型配置解析；
- 向量配置创建与更新；
- Embedding 配置解析；
- OCR/视觉模型配置解析。

### 保存规则

- 请求未提交 `api_key`：保留原有凭据。
- 请求提交非空新 `api_key`：加密后保存。
- 如系统支持清除凭据，应使用明确语义，不要把 `"****"` 当成真正的 API Key。
- 保留现有前端兼容性时，必须确保 `"****"`、`"********"` 等掩码永远不会被写入数据库。
- 加密失败时：
  - 回滚数据库事务；
  - 返回安全、明确的服务端错误；
  - 不得退化为明文保存。

### 读取规则

- 普通业务只能接受带受支持版本前缀的密文。
- 无前缀历史值不得在普通运行路径中直接作为 API Key 使用。
- 遇到历史明文时返回明确的“需要执行凭据迁移”错误。
- 遇到无法解密的密文时返回明确的配置错误。
- 不要把解密失败简单解释为“没有配置 API Key”。
- 解密后的值只保存在调用第三方服务所需的局部变量中。
- 不得放入长期缓存、序列化对象、Pipeline context、任务元数据或响应对象。

## 七、API 安全

检查管理端相关 API。

### 响应

API 响应只允许包含：

```json
{
  "api_configured": true,
  "api_key_masked": "********"
}
```

要求：

- 绝不返回明文。
- 建议统一返回固定长度掩码，例如 `********`。
- 不要根据真实 API Key 长度生成掩码，避免泄露长度信息。
- 解密失败时不要返回看似正常的 `api_configured=true`。

### 连接测试接口

当前连接测试请求中的 `api_key` 不应强制前端重复提交已经保存的密钥。

将其改为可选：

```python
api_key: str | None = None
```

行为：

- 提供 `model_id` 且未提供新 API Key时，服务端从数据库安全解密。
- 新建模型尚未保存时，可以临时提交 API Key进行测试。
- 临时 API Key只能存在于请求生命周期内，不能写日志或写数据库。
- 同时传入 `model_id` 和新 API Key时，应明确使用临时新 Key，或者保持项目现有行为，但必须写测试固定该优先级。
- 不要记录连接测试请求体。

### 审计日志

审计记录只能写：

```json
{
  "api_key_updated": true
}
```

或：

```json
{
  "api_key_cleared": true
}
```

不得写入明文、密文、前缀或长度。

## 八、日志和异常检查

全局搜索以下关键词及其变体：

```text
api_key
apikey
authorization
bearer
secret
token
embedding_api_key
```

确认：

- ORM SQL 日志隐藏参数；
- HTTP 客户端调试日志不输出 Authorization；
- FastAPI 请求日志不输出敏感请求体；
- 异常对象中不拼接 API Key；
- 审计日志不包含密钥；
- `repr()`、Pydantic dump 和 dataclass dump 不会输出密钥；
- 测试失败信息不包含密钥。

不要在日志中输出掩码后的前几位或后几位。

## 九、密钥轮换

至少保证下面场景不会破坏数据：

- 修改 `AI_CONFIG_ENCRYPT_KEY` 后，旧密文不会被误认为明文并再次加密；
- 使用错误密钥解密时，不会覆盖原数据库数据；
- 不会将解密失败后的空字符串重新写入数据库。

如果在不显著增加复杂度的情况下可以支持轮换，请实现：

- 当前密钥用于加密；
- 一个或多个旧密钥仅用于解密；
- 成功使用旧密钥解密后，可在明确的轮换命令中重新加密；
- 普通读取路径不要隐式批量修改数据库。

如果项目暂时不适合实现多密钥支持，请提供独立的轮换步骤和文档，不要假装自动支持。

## 十、测试

为加密模块、服务层、API 层和迁移流程补充测试。

至少覆盖：

1. 正常加密、解密 round trip。
2. 同一明文多次加密产生不同密文。
3. 数据库密文不包含明文。
4. 未配置加密密钥时保存失败。
5. 加密密钥格式错误时保存失败。
6. 生产环境缺少密钥时启动校验失败。
7. 解密密钥错误时抛出明确异常。
8. 解密失败不会返回原始字符串。
9. 解密失败不会返回空字符串伪装成未配置。
10. 历史明文迁移成功。
11. 已加密记录不会二次加密。
12. 迁移重复执行保持幂等。
13. 迁移中途失败时事务回滚。
14. 模型配置 API 永远不返回明文。
15. API 使用固定长度掩码。
16. PATCH 未提交 API Key时保留旧值。
17. PATCH 提交新 API Key时数据库只保存密文。
18. 掩码字符串不会被当作新 Key 保存。
19. 模型连接测试可以通过 `model_id` 使用数据库凭据。
20. 日志、审计数据和错误信息中不出现测试 API Key。
21. `admin_vector_configs` 使用相同的安全规则。
22. 旧密文解密失败时不会被环境变量同步逻辑错误覆盖，除非有明确的新凭据需要更新。

测试中使用随机生成的 Fernet key和明显的假 API Key，例如：

```text
sk-test-do-not-use-123456
```

不要使用真实凭据。

## 十一、完成标准

修改完成后执行项目现有的：

- 单元测试；
- 集成测试；
- lint；
- type check；
- Alembic migration check；
- 生产配置检查。

如项目缺少某项命令，应说明，而不是伪造执行结果。

最后输出：

1. 根因总结；
2. 修改的文件列表；
3. 加密数据格式；
4. 明文迁移命令和执行顺序；
5. 新增环境变量；
6. 测试结果；
7. 部署注意事项；
8. 回滚方案；
9. 需要人工执行的安全操作。

## 十二、额外安全要求

- 不要修改或打印我提供的数据库中的真实 API Key。
- 不要把真实数据库加入测试、Git 或迁移 fixture。
- 不要在代码中硬编码任何加密密钥。
- 不要为了兼容旧数据继续保留“缺少密钥则明文保存”的逻辑。
- 不要静默吞掉加解密异常。
- 不要只修改字段名而不实现真正加密。
- 不要只依赖前端掩码保护。
- 不要在完成后展示数据库密文。
- 不要删除现有凭据记录。
- 修改前先搜索所有调用点，避免只修复模型管理页面而遗漏向量、OCR、Embedding 和后台任务路径。

完成代码修复后，请明确提醒运维人员：

数据库中已经出现过明文 API Key，应当把相关第三方平台凭据视为可能泄露。完成数据库加密迁移并验证服务正常后，需要在 DeepSeek、PaddleOCR、Embedding 服务等供应商后台轮换原 API Key，再通过管理端写入新 Key。数据库加密只能保护后续静态存储，不能使已经暴露过的旧 Key重新变得安全。
