你现在位于我的本地项目仓库中。请直接执行一次“数学公式库完整性审计与补全”，不要只给建议或示例代码。

## 一、任务目标

以本地《27张宇数学公式手册.pdf》的目录为公式库覆盖边界，对本地 SQLite 数据库中的公式分类和公式卡片进行审计，补充确认缺失的公式。

唯一需要排除的内容是：

- 第三部分：概率论与数理统计
- 该部分下的随机事件、概率分布、随机变量数字特征、大数定律、中心极限定理、数理统计、参数估计等全部内容

除此之外，PDF 目录中的其他章节全部属于本次范围。

特别注意：

1. 不要按照“数学二是否要求”决定范围。
2. 即使目录标注“数学二不作要求”，本次仍然要纳入。
3. 包括但不限于：
   - 向量代数和空间解析几何
   - 偏导数在几何中的应用
   - 重积分的应用
   - 曲线积分与曲面积分
   - 数项级数、幂级数、傅里叶级数
   - 差分方程
   - n 维向量空间
4. 初等数学附录也要审计，但已有内容不得重复插入。
5. 压缩包中已有的旧审计文件可能采用“仅数学二”的旧范围，必须重新核实，不能直接采信其“只有初等数学缺失”等结论。

## 二、首先定位并检查项目文件

不要假定绝对路径，先在仓库内查找：

- `27张宇数学公式手册.pdf`
- `postgraduate.db`
- `models/formula.py`
- `schemas/formula.py`
- `services/formula_normalizer.py`
- `api/v1/admin_formulas.py`
- `data/formula_library/`
- `data/formula_audit/`
- 所有名称中含 `seed_formula`、`formula_library`、`zhangyu` 的脚本和数据文件

如果仓库结构带有 `app/`、`backend/` 等前缀，请自动适配。

检查实际代码和数据库后再操作，不要仅依赖本提示中的字段说明。

## 三、PDF 目录覆盖清单

先根据 PDF 目录生成结构化 coverage manifest，至少包含以下部分。

### 第一部分：高等数学

#### 第一章 函数、极限、连续
- 函数
- 极限
- 无穷小量与无穷大量
- 连续

#### 第二章 一元函数微分学
- 导数与微分
- 导数的计算
- 微分中值定理
- 洛必达法则
- 函数及其性态的研究
- 曲率、曲率半径、曲率圆

#### 第三章 一元函数积分学
- 不定积分
- 定积分
- 反常积分

#### 第四章 向量代数和空间解析几何
- 向量代数
- 空间平面与直线
- 空间曲面与曲线

#### 第五章 多元函数微分学
- 偏导数与全微分
- 隐函数求导法
- 方向导数
- 偏导数在几何中的应用
- 多元函数的极值

#### 第六章 多元函数积分学
- 重积分的计算
- 重积分的应用
- 曲线积分
- 曲面积分

#### 第七章 级数
- 数项级数
- 幂级数
- 傅里叶级数

#### 第八章 常微分方程及差分方程
- 一阶微分方程的类型及解法
- 可降阶的高阶微分方程
- 线性微分方程解的结构定理
- 常系数齐次线性微分方程
- 二阶常系数非齐次线性微分方程
- 欧拉方程
- 差分方程

### 第二部分：线性代数

#### 第一章 行列式
- 行列式的定义与性质
- 行列式的展开定理
- 几种特殊行列式
- n 阶行列式的重要公式

#### 第二章 矩阵
- 矩阵的定义与运算
- 矩阵的秩
- 分块矩阵
- 初等变换与初等矩阵

#### 第三章 向量
- n 维向量的定义及运算
- 向量组的线性相关与线性无关
- 极大无关组与向量组的秩
- 内积与施密特正交化
- n 维向量空间

#### 第四章 线性方程组
- 四种表示形式
- 有解的判别条件
- 齐次线性方程组解的结构
- 非齐次线性方程组解的结构

#### 第五章 特征值和特征向量
- 特征值和特征向量
- 矩阵的对角化

#### 第六章 二次型
- 二次型及其表示法
- 正定二次型及其判定

### 附录：初等数学
- 初等代数
- 初等几何
- 三角函数
- 平面解析几何

不要创建“概率论与数理统计”分类或卡片。

## 四、审计数据库

使用 Python 的 `sqlite3` 模块读取数据库，至少检查：

- `formula_categories`
- `formula_cards`
- `formula_card_tags`
- `formula_tags`
- `formula_card_versions`
- 与公式图形相关的表

输出当前：

- 分类树
- 每个章节、分组的卡片数
- 每张卡片的标题、aliases、search_text、formula_blocks、source_ref
- 卡片状态和 card_type
- 重复 source_ref
- 同分类重复标题
- 空 formula_blocks
- JSON 格式错误
- 外键异常

比较时不能只按标题精确匹配。需要综合使用：

- 分类路径
- title
- aliases
- search_text
- formula_blocks 中的 LaTeX
- source_ref
- 公式语义

对每个 PDF 目录小节给出以下状态之一：

- `existing_complete`
- `existing_incomplete`
- `missing`
- `manual_review`
- `excluded_probability_statistics`

章节名称存在，不代表其公式已经完整覆盖。

重点检查但不要预设最终结论：

- “向量代数和空间解析几何”是否完全缺失
- “级数”是否完全缺失
- 多元积分是否只有二重积分而缺少三重积分、重积分应用、曲线积分和曲面积分
- 多元微分是否缺少几何应用
- 常微分方程是否缺少差分方程
- 线性代数各章节是否只有概括卡片而缺少目录所列的重要公式
- 初等数学已有卡片是否已经真实存在，避免重复导入

## 五、从 PDF 提取缺失内容

PDF 是主要内容依据，目录只是覆盖边界。

操作要求：

1. 先根据章节标题确定“印刷页码”和实际 PDF 页码的对应关系，不要写死页码偏移。
2. 只对确认缺失或不完整的章节进行局部页面渲染/OCR，不要无目的地重复 OCR 整本 PDF。
3. 保存每个公式对应的 PDF 页码或印刷页码。
4. OCR 识别后必须检查：
   - 分子分母
   - 上下标
   - 根号范围
   - 积分上下限
   - 求和上下限
   - 矩阵行列
   - 正负号
   - 希腊字母
   - `\left`、`\right`
   - 括号和花括号配对
5. PDF 字符无法明确辨认时，不要猜测，将该项列入 `manual_review`。
6. 通用数学知识只能用于校验和规范 LaTeX，不能用来凭空扩大 PDF 的章节范围。

## 六、补全数据的格式要求

必须先检查当前模型和 Pydantic schema，并完全遵循现有格式。

已知公式卡片通常包含：

- `title`
- `aliases`
- `search_text`
- `card_type`
- `summary`
- `formula_blocks`
- `conditions`
- `symbol_notes`
- `secondary_conclusions`
- `error_tips`
- `examples`
- `function_properties`
- `sort_order`
- `status`
- `source_type`
- `source_title`
- `source_ref`
- `content_hash`
- `version`

`formula_blocks` 中每项通常为：

```json
{
  "label": "公式名称",
  "latex": "规范 LaTeX",
  "note": "可选说明"
}
```

要求：

1. 每张卡片至少 1 个 formula block。
2. 遵守项目 schema 对 formula block 数量的限制；若当前限制为最多 8 个，超过时拆分为多张语义清晰的卡片。
3. 不要把整章所有公式塞进一张超大卡片。
4. 优先使用 `pure_formula`。
5. 只有确实需要函数图像并且项目已有成熟 graph spec 时才使用 `function_graph`。
6. 新卡片默认设为 `draft`，不要自动发布。
7. `source_type` 使用项目已有合法值，优先 `manual` 或项目现有导入约定。
8. 新公式的 `source_ref` 必须稳定、唯一、可重复运行，例如：

```text
zhangyu_formula_manual:nonprob:<chapter_code>:<slug>
```

1. 已有 `source_ref` 不得重新创建。
2. source_ref 为空的旧卡片要通过分类、标题、别名和公式语义判断重复。
3. aliases、search_text、conditions、error_tips 使用简体中文，LaTeX 使用项目已有风格。
4. 不要在 LaTeX 中使用无法被前端渲染的自定义宏。
5. 复用项目现有的 content hash 计算函数和公式 normalizer，不要自行设计不兼容算法。
6. 标签只能使用 `formula_tags` 中真实存在的标签 code/ID。

## 七、分类处理

保持现有三级结构：

```text
subject -> chapter -> group
```

新增分类时：

- 使用稳定的 ASCII `snake_case` code
- 不硬编码数据库 ID
- 通过父级 code 查找 parent_id
- 继承父分类的 `exam_scope`
- 不擅自新增新的 exam_scope 枚举或重构学科系统
- 不修改已有分类的 ID
- 不删除已有分类
- 新章节加入已有“高等数学”“线性代数”或“初等数学”根分类下

本次收录范围由 PDF 决定，不再依据旧文件中的 `math2_relevant` 字段过滤。

## 八、持久化方式

不要只直接修改数据库。

优先采用项目现有的“源数据文件 + 幂等 seed/upsert 脚本”机制：

1. 保留已有 v1、v2、v3 历史源文件。
2. 新建独立扩展文件，建议名称：

```text
data/formula_library/zhangyu_nonprob_extensions_v1.json
```

实际路径按仓库结构调整。

1. 新建或扩展幂等导入脚本，建议：

```text
scripts/seed_zhangyu_nonprob_formulas.py
```

1. 支持：

```bash
python scripts/seed_zhangyu_nonprob_formulas.py --dry-run
python scripts/seed_zhangyu_nonprob_formulas.py --apply
```

1. 幂等判定顺序：
   - source_ref
   - category_id + 规范化 title
   - aliases 和 LaTeX 语义相似性检查
2. 第二次执行必须：
   - 0 个重复新增
   - 不重复创建分类
   - 不重复创建标签关系
   - 不重复创建无意义版本记录

如果仓库已经有统一 seed 框架，应接入现有框架，而不是重复造轮子。

## 九、数据库安全

正式修改前：

1. 确认实际使用的数据库路径。
2. 使用 SQLite backup API 或文件复制创建带时间戳备份：

```text
postgraduate.db.bak_before_zhangyu_nonprob_<timestamp>
```

1. 开启外键检查。
2. 所有写操作放在事务内。
3. 发生任意校验失败时回滚。
4. 不删除任何现有公式卡片。
5. 不改变用户收藏关系。
6. 不改变已有 published 卡片的发布状态。
7. 修改已有卡片时：
   - 保存修改前快照
   - 正确递增 version
   - 创建 `formula_card_versions` 记录
   - 重新计算 content_hash
8. 新卡片也应按项目现有约定创建初始 version snapshot。

如果一个 published 卡片疑似不完整但修改风险较高，优先生成明确的待审核补丁并列入报告，不要静默破坏线上内容。

## 十、需要重新生成的审计文件

已有以下文件可能是旧的“仅数学二”审计结果：

- `zhangyu_formula_manual_inventory.json`
- `zhangyu_formula_manual_diff.json`
- `zhangyu_formula_manual_formulas.json`
- `execution_report.md`

不要覆盖历史文件，建议新建：

```text
data/formula_audit/zhangyu_nonprob_inventory.json
data/formula_audit/zhangyu_nonprob_diff.json
data/formula_audit/zhangyu_nonprob_formulas.json
data/formula_audit/zhangyu_nonprob_execution_report.md
```

diff 文件中必须分别列出：

- 已完整覆盖
- 已有但不完整
- 完全缺失
- OCR 或符号需人工复核
- 明确排除的概率统计内容
- 新增分类
- 新增卡片
- 更新卡片
- 因重复而跳过的卡片

## 十一、验证

应用后必须运行以下检查：

### SQLite

```sql
PRAGMA integrity_check;
PRAGMA foreign_key_check;
```

### 数据完整性

- formula_blocks 均为合法 JSON 数组
- 每张卡片至少一个公式块
- 每个 formula block 均有非空 latex
- source_ref 无重复
- 同分类 title 无重复
- category 的 parent_id 合法
- formula_card_tags 无重复关系
- 每张新卡片都有初始版本记录
- 更新卡片的 version 与版本表一致

### LaTeX

检查：

- `{}` 配对
- `()`、`[]` 配对
- `\left` 与 `\right` 配对
- `\begin` 与 `\end` 配对
- 不存在 OCR 控制字符和乱码
- 不存在 Unicode 上下标残留
- 不存在明显的 `O/0`、`l/1`、`x/×` 混淆
- 矩阵和 cases 环境可以被项目渲染器处理

### 范围隔离

扫描新增内容的：

- 分类名称
- 标题
- aliases
- search_text
- summary
- source_ref

确保没有新增概率论与数理统计章节或卡片。

注意：“排列组合”和“二项式定理”属于初等代数，不应因含有组合记号而错误排除。

### 幂等性

连续运行两次 apply：

- 第二次 inserted = 0
- 第二次 updated = 0，除非源数据确实发生变化
- 分类数、卡片数、标签关系数不再变化

### 项目测试

运行与公式模型、公式 API、seed 脚本有关的现有测试；如果没有测试，至少增加：

- seed dry-run 测试
- seed 幂等测试
- formula schema 校验测试
- source_ref 去重测试
- 概率统计排除测试

## 十二、最终交付

任务完成后，不要只说“已完成”。请输出：

1. 实际 PDF 路径和数据库路径
2. 备份数据库路径
3. 修改前后的分类数、卡片数和版本记录数
4. 新增分类清单
5. 新增卡片清单，包含：
   - 分类路径
   - title
   - source_ref
   - PDF 页码
   - formula block 数量
6. 更新卡片清单及更新原因
7. 跳过的重复项
8. manual_review 项
9. 明确排除的概率统计范围
10. 新增或修改的文件路径
11. 完整验证结果
12. 回滚方法
13. dry-run 和 apply 的运行命令

请现在开始检查实际仓库、PDF 和数据库，并执行完整流程。除非缺少必要文件或无法确认数据库路径，否则不要停下来向我询问。

```

```
