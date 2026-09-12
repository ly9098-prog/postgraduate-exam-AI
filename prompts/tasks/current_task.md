你正在一个本地代码仓库中工作。请直接检查仓库代码、数据库配置、迁移脚本、ORM/SQL 模型、后端接口以及相关导入逻辑，并完成一次 **408 知识点与考纲数据的破坏式全量重构**。

## 一、目标

当前数据库中的知识点、知识图谱和考纲数据大部分由旧 AI 自动生成，质量不可靠。

现在需要完全放弃旧知识点/旧考纲数据，以仓库目录：

```
/artifacts/data_reshape/
```

中的新数据作为权威数据源，对数据库进行重构。

允许破坏旧的题目知识点历史快照、旧考纲版本映射和用户知识状态，因为后续可以基于新知识点重新回填。

但是：

**任何数据库修改之前，必须先创建完整可恢复备份。**

不要为了兼容旧 AI 数据而保留错误结构。

------

# 二、第一原则：先检查仓库，不要直接执行 SQL

开始修改之前，先完整检查：

1. 数据库类型和版本
2. ORM / 数据访问层
3. migration 系统
4. 数据库连接配置
5. Knowledge Point 相关 Model / Entity / Table
6. Syllabus / 考纲相关表
7. Knowledge Graph Edge 相关表
8. Question 与 Knowledge Point 的关联表
9. Question Version 与 Syllabus Knowledge Point 的关联表
10. 用户知识掌握状态、推荐、自适应学习等引用 knowledge_point_id 的表
11. subject / exam / root subject 的结构
12. 小程序和后端实际如何读取知识点树和知识图谱
13. 是否存在触发器、约束、枚举、缓存、搜索索引、物化视图等依赖

不要假设我下面写出的表名一定和代码完全一致。

应以仓库真实 schema 为准。

如果实际表名、字段名与数据文件不完全一致，请根据真实代码做适配。

------

# 三、必须首先执行数据库备份

在任何 DELETE / TRUNCATE / DROP / UPDATE / INSERT 之前，必须完成数据库备份。

备份必须满足：

- 是数据库级完整备份，不只是导出知识点几张表
- 能用于完整恢复
- 文件名带时间戳
- 不覆盖已有备份
- 放在仓库中合适的备份目录，例如：

```
artifacts/db_backup/
```

或仓库已有 backup 目录

建议命名：

```
pre_408_knowledge_graph_rebuild_YYYYMMDD_HHMMSS.*
```

根据数据库类型选择正确方式，例如：

PostgreSQL：
`pg_dump`

MySQL：
`mysqldump`

SQLite：
复制数据库文件，并确保 WAL 一并正确处理

如果仓库已有正式 backup script，优先复用。

完成备份后必须验证：

- 文件确实存在
- 文件大小非 0
- backup command exit code 成功

如果条件允许，再通过 restore dry-run 或 schema inspection 验证备份可恢复。

**备份失败则禁止继续修改数据库。**

------

# 四、新数据目录

新的重构数据全部位于：

```
artifacts/data_reshape/
```

请先列出该目录中的实际文件，并检查 CSV header。

预期至少会存在类似以下数据：

- `knowledge_points_replace.csv`
- `knowledge_edges_replace.csv`
- `syllabus_versions_replace.csv`
- `syllabus_knowledge_points_replace.csv`
- `syllabus_knowledge_point_mappings_replace.csv`
- `syllabus_outline_audit.csv`
- `question_backfill_leaf_catalog.csv`
- `old_knowledge_point_exact_crosswalk.csv`
- `verification_summary.csv`
- `00_destructive_rebuild_manifest.csv`

不要仅根据文件名猜 schema。

必须读取 CSV header，并与数据库真实 schema 对照。

------

# 五、数据设计原则

这次是 **破坏式全量替换**，不是 append / merge。

新的知识点体系以 `knowledge_points_replace.csv` 为准。

新知识点来自严格的 408 Markdown 考纲层级：

- 章
- 节
- 细目

当前数据集预期约：

- 499 个知识点节点
- 26 个章节点
- 106 个节节点
- 367 个细目节点

图谱边预期约：

- 473 条 `parent`
- 366 条 `next`
- 总计 839 条

请以实际 CSV 为最终准则，不要把这些数字硬编码进业务代码。

------

# 六、知识图谱语义

本次导入的数据原则如下：

## parent

表示严格的考纲层级关系：

章 → 节 → 细目

## next

表示 Markdown 考纲中同级条目的顺序关系。

注意：

`next` 不是 prerequisite。

不要把它解释成“必须先学 A 才能学 B”。

## 不要自行生成

除非 CSV 中已有，否则不要额外使用 AI 或业务规则生成：

- prerequisite
- related
- depends_on
- similar
- contains
- prerequisite_of

等边。

这次数据库内容必须忠实于 `artifacts/data_reshape/`。

------

# 七、需要清理的旧数据

因为新的 knowledge point ID 会重新建立，所以旧引用不能保留。

必须检查所有引用 knowledge point / syllabus knowledge point 的表。

典型可能包括但不限于：

- `question_knowledge_points`
- `question_version_knowledge_points`
- `user_knowledge_states`
- `user_knowledge_adaptive_state`
- recommendation / mastery / progress 相关表
- syllabus mapping 表
- syllabus membership 表
- knowledge graph edge 表
- knowledge_points 表

特别重要：

如果旧关联表继续保留，而新 knowledge point 又重新使用 ID 1、2、3……

就可能出现：

**旧题目关联 ID=10，在重构后静默指向完全不同的新知识点 ID=10。**

这种问题比 FK 报错更危险。

所以在导入新 knowledge point 之前：

必须清理所有可能产生这种错误绑定的旧关联数据。

如果数据库 FK 关系要求按顺序删除，请按依赖关系正确执行。

------

# 八、不要删除题目主体

这次主要重建：

- 知识点
- 考纲
- 图谱
- 相关知识状态

原则上：

**不要删除 questions / question_versions 本身的题目内容。**

应该删除或重置它们与旧知识点的关系。

之后题目知识点可以重新回填。

如果实际数据库设计导致无法单独清理，请先分析并说明，再选择最安全方案。

------

# 九、推荐执行顺序

请根据实际 FK 关系调整，但原则上应类似：

### Phase 1：备份

完整数据库 backup。

### Phase 2：清理 dependent data

先清理所有引用旧：

- `knowledge_point_id`
- `syllabus_knowledge_point_id`
- `syllabus_version_id`

且无法继续保留的数据。

### Phase 3：清理旧知识体系

清理：

1. syllabus knowledge point mappings
2. syllabus knowledge points
3. syllabus versions
4. knowledge edges
5. knowledge points

必要时 reset sequence / identity。

### Phase 4：导入新数据

按 FK 依赖导入：

1. `knowledge_points_replace.csv`
2. `knowledge_edges_replace.csv`
3. `syllabus_versions_replace.csv`
4. `syllabus_knowledge_points_replace.csv`
5. `syllabus_knowledge_point_mappings_replace.csv`

如果 mappings 文件只有 header、没有数据，这是正常情况。

------

# 十、root_subject_id 不要盲目使用 6

数据文件中可能暂时包含：

```
root_subject_id = 6
```

但不要直接相信这个值。

必须先查询实际数据库中的 subject / exam subject 数据。

确认 408 根节点是什么。

重点确认四科：

- 数据结构
- 计算机组成原理
- 操作系统
- 计算机网络

对应实际 subject ID。

如果真实数据库当前就是：

- 数据结构 = 7
- 计算机组成原理 = 8
- 操作系统 = 9
- 计算机网络 = 10

并且它们的父节点 / 根节点确实是 6，则可以使用 6。

如果不是：

必须根据真实数据库修正 `syllabus_versions.root_subject_id`。

不要为了适配 CSV 修改现有正确的 subject 主数据。

------

# 十一、保留 Markdown 原始语义

不要擅自修改新数据中的知识点编号或标题。

特别注意：

原考纲中存在一个编号重复：

计算机组成原理 CPU / 数据通路部分有两个：

```
5.3.4
```

分别对应两个不同知识点。

这是源 Markdown 本身的情况。

不要擅自把第二个改成 5.3.5。

数据库节点由独立 ID 区分，不要把 `outline_code` 当作全局唯一标识。

------

# 十二、CSV 导入必须正确处理

注意以下问题：

### UTF-8

中文必须正确导入。

优先使用 UTF-8 / UTF-8 BOM 兼容方式。

### JSON aliases

`aliases` 字段可能是 JSON array，例如：

```
["栈的基本概念"]
```

如果数据库字段是 JSON / JSONB：

正确解析后写入。

不要把 JSON array 当普通字符串错误存进去。

如果数据库字段本身就是 string 类型，则遵循现有代码设计。

### Boolean

CSV 中可能出现：

```
t`
`f
```

需要适配数据库实际 boolean 类型。

### NULL

空字段根据真实 schema 写 NULL，而不是不加区分地写空字符串。

### Timestamp

根据实际数据库 timestamp 类型处理。

------

# 十三、sequence / identity

如果主键是 auto increment / serial / identity，而 CSV 显式导入了 ID：

导入完成后必须修复 sequence。

例如 PostgreSQL：

确保：

```
nextval(sequence) > max(id)
```

否则后续新建知识点时可能发生主键冲突。

请检查至少：

- knowledge_points
- knowledge_edges
- syllabus_versions
- syllabus_knowledge_points
- mappings

相关 sequence。

------

# 十四、事务要求

如果数据库和数据规模允许：

尽量把 destructive rebuild 核心过程放在一个 transaction 中。

例如：

BEGIN

清理旧关系

清理旧知识体系

导入 knowledge points

导入 edges

导入 syllabus

执行验证

COMMIT

如果任何关键验证失败：

ROLLBACK

但是数据库完整备份仍然必须在 transaction 之前完成。

如果因为 DDL / bulk import 工具限制无法一个事务完成，请分阶段执行，并明确可恢复节点。

------

# 十五、导入后的强制验证

导入完不能只看 command success。

必须主动查询数据库验证。

至少检查：

## Knowledge Points

总数是否与：

```
knowledge_points_replace.csv
```

一致。

检查：

- ID 唯一
- `(subject_id, normalized_name)` 不发生非预期重复
- subject_id 全部有效
- aliases 数据格式合法
- description 正常
- 中文未乱码

## Knowledge Edges

总数与：

```
knowledge_edges_replace.csv
```

一致。

检查：

- source knowledge point 全部存在
- target knowledge point 全部存在
- 无 dangling edge
- `parent` 数量一致
- `next` 数量一致
- edge subject 与 source / target subject 一致
- 不存在意外跨学科 parent / next

## Syllabus

检查：

- 只有预期的新 syllabus version
- active 状态正确
- root_subject 正确
- syllabus knowledge point 数量与 CSV 一致
- 每个 membership 都能对应 knowledge point
- snapshot name 与当前 knowledge point 一致

## Hierarchy

至少抽查：

数据结构：
第2章 → 2.1 → 2.1.1

操作系统：
第2章 → 2.3 → 信号量 / 经典同步问题等

计算机网络：
第4章 → IPv4 / IPv6 / 路由相关

组成原理：
第5章 → 数据通路

确保 parent 方向和前端读取逻辑一致。

------

# 十六、运行仓库现有测试

数据导入完成后执行仓库已有：

- unit test
- integration test
- backend test
- lint
- typecheck

如果项目有知识图谱 API 测试，必须执行。

同时实际调用相关接口验证，例如：

- syllabus tree API
- knowledge graph API
- subject knowledge point API
- question detail API

使用仓库实际 route，不要凭空创造 endpoint。

------

# 十七、检查小程序兼容性

检查小程序代码如何展示：

- knowledge point name
- parent hierarchy
- graph edge
- syllabus version
- question knowledge points

重点确认新的：

```
3.1 栈
3.1.1 栈的基本概念
```

这种带编号 name 不会导致：

- UI 崩溃
- 排序异常
- key 冲突
- 搜索失效
- graph node label 解析错误

如果前端代码错误地假设知识点名称不含编号，应修复前端解析逻辑，而不是删除新数据的编号。

------

# 十八、旧题目知识点回填

这一步本次可以不做完整 AI 重标注，但是必须为后续回填做好准备。

目录中存在：

```
question_backfill_leaf_catalog.csv
```

它定义了建议用于题目最终标注的叶子知识点。

原则：

题目知识点映射优先映射到最细粒度的叶子节点。

不要把大量题目只映射到：

- 第X章
- X.X 某节

除非题目确实无法更细分类。

另有：

```
old_knowledge_point_exact_crosswalk.csv
```

这个文件只能作为参考。

其中：

```
exact_unique
```

表示旧 canonical name 能在同科目精确映射到一个新知识点。

不要把：

```
unmatched
```

自动通过 fuzzy matching 强行映射。

旧 AI aliases 不可信。

------

# 十九、最好新增可重复运行的数据重构脚本

不要只手工改数据库。

优先在仓库里新增一个明确的数据维护脚本，例如：

```
scripts/rebuild_408_knowledge_graph.*
```

或遵循项目现有 scripts 结构。

脚本要求：

- 从 `artifacts/data_reshape/` 读取数据
- 默认先 backup
- 默认要求明确确认 destructive 操作，或者提供：
  `--yes`
- 支持：
  `--dry-run`
- 输出导入前后的 row count
- 遇到异常立即退出
- 返回非 0 exit code
- 不静默吞掉错误

如果项目已有 CLI / admin task 系统，优先集成到现有体系，不要重复造轮子。

------

# 二十、Dry Run

正式改数据库之前先执行 dry run。

Dry run 至少验证：

- CSV 可读取
- header 正确
- ID 唯一
- FK 引用在数据集内部闭合
- subject ID 合法
- normalized_name 唯一规则满足 schema
- aliases 可解析
- parent / next edge 引用合法
- syllabus membership 引用合法

dry run 成功后才能执行正式 destructive rebuild。

------

# 二十一、不要做的事情

禁止：

1. 不备份直接清库
2. 为了兼容旧数据保留错误知识点
3. 自己用 AI 增加考纲外知识点
4. 自己发明 prerequisite / related 图谱边
5. 擅自修正 Markdown 的重复编号
6. 为了避免 FK 问题删除题目主体
7. 静默忽略导入错误
8. 只修改 CSV、不真正更新数据库
9. 只修改数据库、不留下可重复运行的脚本
10. 不验证就宣称完成
11. 将数据库密码或敏感连接字符串提交到 Git
12. 提交数据库 backup 到 Git

如果 backup 位于仓库目录中，确保 `.gitignore` 正确忽略实际数据库备份文件，但不要误删已有规则。

------

# 二十二、Git 改动原则

尽量只修改本次任务相关文件。

不要顺手格式化整个仓库。

不要重构无关代码。

在修改完成后执行：

```
git diff
```

并检查：

- 没有数据库密码
- 没有 backup 文件
- 没有大体积临时文件
- 没有无关改动
- 没有误删业务代码

------

# 二十三、最终交付结果

执行完成后，请给出清晰报告，包括：

### 1. 数据库备份

- backup 路径
- backup 类型
- 文件大小
- 创建时间
- backup 验证结果

### 2. 代码改动

列出修改 / 新增文件。

说明每个文件作用。

### 3. 数据清理

列出实际清空/删除了哪些表的数据，以及删除前 row count。

### 4. 数据导入

列出每个表：

- 导入前数量
- 导入数量
- 导入后数量

### 5. 验证结果

至少报告：

- knowledge point 数量
- parent edge 数量
- next edge 数量
- syllabus knowledge point 数量
- orphan edge 数量
- invalid FK 数量
- duplicate normalized name 数量
- active syllabus version
- root_subject_id

### 6. Tests

列出实际运行过的命令和结果。

### 7. 风险

如果仍有待处理事项，例如：

- questions 尚未重新标注
- 用户知识状态已经清空
- 某些旧题知识点关联已失效

明确列出来。

### 8. 回滚方法

明确说明如何通过刚才的 backup 恢复。

------

# 二十四、执行方式

不要只给我方案。

请：

1. 检查仓库
2. 检查数据库
3. 检查 CSV
4. 生成 backup
5. dry-run
6. 实现或完善 rebuild script
7. 执行 destructive rebuild
8. 验证数据库
9. 运行测试
10. 给我最终结果

如果发现数据文件与真实 schema 有差异：

优先适配导入脚本，不要随意修改权威 CSV 内容。

如果发现 CSV 本身存在会导致数据错误的问题：

停止正式 destructive import，明确指出具体行、字段和问题；不要导入一个已知错误的数据集。

本次任务的最高优先级依次是：

**可恢复性 > 数据正确性 > 严格符合考纲 > 代码兼容性 > 历史数据兼容性。**
