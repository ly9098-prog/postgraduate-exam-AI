你是一名资深微信小程序、KaTeX、FastAPI 和 SQLite 工程师。请直接检查并修改当前代码库，修复公式阅读页中行列式被显示成 `det(A)` 字样的问题。

## 问题说明

微信小程序页面：

subpackages/formulas/reader/index

目前会出现类似：

    det(A^T) = det(A)

的视觉形式。

本项目要求行列式使用标准的竖线数学记法，目标效果为：

    \left|A^{T}\right| = \left|A\right|

不要继续显示字母 `det`，也不要通过普通文本、CSS 字体或伪元素模拟。必须生成合法 LaTeX，并由现有 KaTeX 渲染链路渲染。

## 已知代码结构

不要只修改 `subpackages/formulas/reader/index.js`。该页面主要负责请求和切换公式，真正的公式处理链路还包括：

- subpackages/formulas/reader/index.js
- subpackages/formulas/reader/index.wxml
- components/formula-card/index.js
- components/formula-card/index.wxml
- components/formula-card/index.wxss
- utils/formula-content.js
- components/mp-html/latex/
- 后端 GET /formulas/{id}
- SQLite 数据库 postgraduate.db 中的 formula_cards 表

当前数据库中已经发现以下相关数据：

1. formula_cards.id = 39
   标题：行列式的定义与基本性质

   formula_blocks 中包含：

       "\\det(A^T) = \\det(A)"

2. formula_cards.id = 40 中存在疑似脏数据：

       "\\det = \\prod_{i=1}^n a_{ii}"

   这里缺少行列式对象，不能仅靠前端盲目猜测。结合该卡片“特殊行列式的值”和“上（下）三角”语境，应核实并修正为类似：

       "\\left|A\\right| = \\prod_{i=1}^n a_{ii}"

3. 数据库中还存在以下写法：

       \det(A)
       \det A
       \det Q
       \operatorname{det}(A)
       det(A)
       det A
       (\det A)^{n-1}
       \frac{1}{\det(A)}
       \det\begin{pmatrix}...\end{pmatrix}

请扫描所有相关记录，不要只修复 id=39。

## 第一阶段：定位根因

先完整追踪一次 id=39 的数据链路：

1. 查询数据库 formula_cards.formula_blocks 的原始值。
2. 检查后端 `/formulas/39` 返回的 JSON。
3. 检查 `subpackages/formulas/reader/index.js` 收到的数据。
4. 检查 `utils/formula-content.js`：
   - normalizeLatexSource
   - normalizeMathRun
   - normalizeFunctionNames
   - prepareFormulaBlocks
5. 检查 `components/formula-card/index.js` 传给 KaTeX 的最终字符串。
6. 判断问题究竟属于：
   - 数据库内容格式；
   - 后端序列化；
   - 前端公式标准化；
   - KaTeX 渲染；
   - 或多处共同导致。

不要凭感觉修改。可以加入仅开发环境生效的临时日志，但完成后删除无用日志。

## 第二阶段：实现统一的行列式标准化

在公式进入 KaTeX 之前增加一个职责明确、可测试的标准化函数，例如：

    normalizeDeterminantNotation(source)

应将能够安全识别的行列式表达式转换成竖线形式。

至少支持：

    \det(A^T)
    → \left|A^T\right|
    
    det(A)
    → \left|A\right|
    
    \operatorname{det}(A)
    → \left|A\right|
    
    \det A
    → \left|A\right|
    
    \det Q
    → \left|Q\right|
    
    \det(AB)
    → \left|AB\right|
    
    \det(A^{-1})
    → \left|A^{-1}\right|
    
    \det(A)\det(B)
    → \left|A\right|\left|B\right|
    
    \frac{1}{\det(A)}
    → \frac{1}{\left|A\right|}
    
    (\det A)^{n-1}
    → \left|A\right|^{n-1}
    
    \det\begin{pmatrix}
      a & b \\
      c & d
    \end{pmatrix}
    →
    \begin{vmatrix}
      a & b \\
      c & d
    \end{vmatrix}

目标示例必须最终成为：

    \left|A^{T}\right|=\left|A\right|

### 解析要求

不要使用一个不受约束的全局正则直接替换所有 `det`。

实现时必须正确处理：

- 成对圆括号；
- 嵌套括号；
- LaTeX 花括号；
- 上下标；
- 矩阵环境；
- 同一公式中多个 determinant；
- 分式中的 determinant；
- determinant 后面的单个矩阵符号或完整分组。

建议使用字符扫描器或小型状态机识别参数边界，而不是仅使用：

    /det\((.*?)\)/

因为该正则无法可靠处理嵌套内容。

## 严禁误改

以下内容不能被错误替换：

- `\text{...}` 中的普通文字；
- URL、路径、代码片段；
- 单词的一部分；
- 数据库标题、搜索文本中的普通英文说明；
- 已经是 `\begin{vmatrix}...\end{vmatrix}` 的公式；
- `\operatorname{tr}`、`\log`、`\exp` 等其他运算符；
- 绝对值本身；
- 包含歧义的裸 `\det`。

例如下面记录中的 `det` 位于文字环境内，不应被转换成破坏性的嵌套竖线：

    \text{相似：方阵，保持特征多项式、特征值、det、tr、秩}

该处可以保持文字，或者在不破坏 `\text{}` 的前提下按项目内容规范处理，但不能让 KaTeX 解析失败。

## 第三阶段：处理数据库

检查 `postgraduate.db` 中 `formula_cards` 表的以下字段：

- formula_blocks
- conditions
- symbol_notes
- secondary_conclusions
- error_tips
- examples

扫描所有 `det`、`\det` 和 `\operatorname{det}`。

处理原则：

1. 可安全、确定转换的公式数据，应统一为规范的竖线 LaTeX。
2. 普通说明文字不要误改。
3. 像 id=40 的 `\det = ...` 属于缺少参数的数据问题，应结合卡片标题、块标签和上下文修复数据库，而不是在前端默认补一个 A。
4. 数据迁移必须幂等，重复执行不会继续增加转义符、竖线或括号。
5. 修改数据库前先创建备份，例如：

       postgraduate.db.bak-det-fix-<timestamp>

6. 使用事务执行，任意记录失败时回滚。
7. 优先使用项目现有 ORM、服务层或迁移机制，不要直接以二进制方式修改 SQLite。
8. 如项目依赖以下字段，必须同步正确维护：
   - content_hash
   - version
   - updated_at
   - formula_card_versions 历史记录
9. 输出迁移前后的受影响记录 ID、字段名和旧值/新值摘要。
10. 不要修改无关数据。

即使最终根因主要在前端，也要修复已经确认存在的数据库脏数据；即使数据库被修复，前端仍需具备向后兼容能力，防止旧数据或接口数据再次显示 `det`。

## 第四阶段：测试

为标准化逻辑增加单元测试，至少覆盖：

1. `\det(A^T) = \det(A)`
2. `det(A)=det(A^T)`
3. `\det A`
4. `\det(A^{-1})`
5. `\det(A)\det(B)`
6. `\frac{1}{\det(A)}`
7. `(\det A)^{n-1}`
8. 嵌套括号：`\det(P^{-1}AP)`
9. 矩阵参数：`\det\begin{pmatrix}...\end{pmatrix}`
10. 已有 `vmatrix` 不重复转换
11. `\text{det、tr、秩}` 不被破坏
12. 英文单词中的 `det` 不被替换
13. 多次执行标准化结果保持一致
14. id=39 的真实数据库数据
15. id=40 的脏数据修复结果

还要运行现有公式渲染相关测试，确保：

- 分式正常；
- 矩阵正常；
- `\operatorname{tr}` 正常；
- 普通绝对值正常；
- 公式滑动和换页不受影响；
- KaTeX 不出现 parse error；
- 页面不回退为源码文本。

## 验收标准

必须满足：

1. `subpackages/formulas/reader/index` 中不再显示字面量 `det(A)`。
2. id=39 的“转置不变”最终渲染为：

       \left|A^{T}\right|=\left|A\right|

3. `A^T` 中的 T 正确显示为上标。
4. 两侧竖线由 KaTeX 生成，大小和内容匹配。
5. 不通过截图、图片、CSS 伪元素或硬编码某一张卡片实现。
6. 列表、随机阅读、收藏切换和上一条/下一条功能保持正常。
7. 新旧数据格式均可正确渲染。
8. 数据库脏数据得到可追溯、可回滚的修复。
9. 所有新增和现有相关测试通过。

## 最终交付

请直接完成代码和数据库修复，不要只给方案。

完成后输出：

1. 根因分析。
2. 修改过的文件列表。
3. 数据库迁移或修复脚本位置。
4. 被修改的数据库记录 ID。
5. 关键旧值与新值示例。
6. 测试命令及测试结果。
7. id=39 最终传入 KaTeX 的完整 LaTeX 字符串。
8. 是否还存在不能自动安全转换的 determinant 数据，并列出具体记录。