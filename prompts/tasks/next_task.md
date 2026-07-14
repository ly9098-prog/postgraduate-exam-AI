你正在继续维护 MemoGrad / 22408AI刷题小程序中的“考研数学二公式图像 Phase 2”。

当前 Phase 2 已经完成：

- GraphSpec 区域着色；
- 等轴坐标；
- 箭头标注；
- 9 个可渲染预览；
- 67 项自动化测试；
- 11 个逻辑图表主题中的大部分实现。

但目前仍不能将 Phase 2 标记为完整完成。请直接在当前仓库中完成以下收尾工作，不要只输出方案。

------

# 一、开始前审计

先阅读并遵循：

1. 根目录 `CLAUDE.md`
2. `prompts/tasks/current_task.md`
3. `prompts/tasks/math_chart/phase_2_diagrams.md`
4. `backend/app/services/formula_graph_spec_renderer.py`
5. `backend/app/services/formula_graph_spec_service.py`
6. `backend/scripts/generate_math2_diagrams.py`
7. `backend/app/data/formula_library/math2_diagram_specs.json`
8. `backend/tests/test_formula_diagrams.py`
9. 与以下模型相关的 ORM、schema、API 和迁移：
   - 公式卡；
   - GraphSpec；
   - 预览记录；
   - FormulaGraphAsset；
   - 审核状态；
   - 版本记录；
   - 审计日志。

先输出一个简短审计结果，然后继续实现，不要等待确认。

审计重点：

- 一个公式卡当前是否只能保存一个 `graph_spec`；
- 多张预览实际存储在何处；
- 后生成的 GraphSpec 是否会覆盖先前 GraphSpec；
- 已确认资产是否支持一卡多图；
- 预览、GraphSpec 和最终资产的关系；
- 是否存在可复用的一对多表；
- 是否有稳定 slug/source_ref；
- 是否在数据文件、路径或正文中硬编码数据库数字 ID；
- 当前 9 个预览是否都仍能通过原始 GraphSpec 重现；
- `conic_sections` 是否已有合适卡片；
- 当前所有图是否仍为预览、待审核或已确认状态。

------

# 二、核心目标

完成后必须达到：

1. 一个公式卡可安全关联多个独立数学图表；
2. 每个图表都有独立稳定标识；
3. 不再发生后生成 GraphSpec 覆盖前一个的问题；
4. “常见二次曲线”拥有正式关联卡片和预览；
5. 所有 11 个逻辑主题都有可审核预览，或有明确且可验证的阻塞项；
6. 字体缺失警告消除；
7. 定义域边界 RuntimeWarning 消除；
8. X 型和 Y 型区域着色语义正确；
9. 预览生成具有幂等性；
10. 审核确认通过现有工作流完成；
11. 公共端只能看到已确认、已发布资源；
12. 所有修改有测试和文档支撑。

------

# 三、解决“一张卡只能保存一个 GraphSpec”

这是最高优先级。

当前受影响的至少包括：

- `两个重要极限`
  - 三个基本极限；
  - 第二重要极限。
- `二重积分交换次序模板`
  - X 型与 Y 型区域；
  - 需要分区的换序区域；
  - 双曲线围成区域。

不要继续依赖公式卡表中的单一 `graph_spec` 字段保存多个逻辑图表。

## 推荐数据模型

优先检查现有结构是否已有可复用的一对多关系。

若没有，则新增一个独立模型，例如：

```text
FormulaGraphSpec
```

字段按项目实际规范确定，但至少应支持：

```text
id
formula_card_id
slug
source_ref
title
description
alt_text
spec_json
spec_hash
schema_version
renderer_version
status
sort_order
created_at
updated_at
reviewed_by
reviewed_at
confirmed_asset_id
```

必要时也可让 `FormulaGraphAsset` 直接承载 GraphSpec，但必须保证：

- 一个公式卡可有多个图表；
- 每个图表有独立审核状态；
- 每个图表有独立 GraphSpec；
- 每个图表有独立预览；
- 每个图表可独立确认；
- 不覆盖其他图表；
- 已确认图表的 GraphSpec 可追溯；
- GraphSpec 更新后不会静默覆盖已发布资产。

必须通过 Alembic 完成数据库结构变化，并兼容：

- SQLite；
- PostgreSQL。

不要删除现有公式卡的 `graph_spec` 字段。

需要提供兼容迁移逻辑：

- 旧单图 GraphSpec 可继续读取；
- 新逻辑优先读取一对多图表；
- 有必要时将旧数据迁移到新表；
- 不破坏已有正式图表资产。

------

# 四、稳定标识与跨环境路径

禁止将以下数字 ID 作为永久身份：

```text
ID=1
ID=178
ID=179
ID=180
ID=181
ID=187
```

数字 ID 只能用于本地调试输出。

每个图表必须使用稳定身份，例如：

```text
math2_diagram_v1:curvature_circle
math2_diagram_v1:arc_differential
math2_diagram_v1:surface_revolution
math2_diagram_v1:double_int_xy_region
math2_diagram_v1:exchange_order_split
math2_diagram_v1:hyperbola_sector
math2_diagram_v1:conic_sections
math2_diagram_v1:three_basic_limits
math2_diagram_v1:second_important_limit
math2_diagram_v1:exponential_decay_family
```

关联公式卡时使用：

- `source_ref`；
- stable slug；
- 规范化标题作为兜底。

不要在 JSON、数据库正文、描述或路径中永久保存数据库数字 ID。

预览和正式资源路径优先改为：

```text
static/formulas/graphs/{diagram_slug}/preview/{spec_hash}.png
```

或项目存储服务中的等价 storage key。

若现有生产路径必须保留 card ID，则至少确保：

- 数据库中使用稳定 storage key；
- 每个环境可重新生成；
- 不依赖开发库 ID 对应的 Git 文件；
- 迁移和部署时不会发生卡片错配。

------

# 五、新建“常见二次曲线与积分区域识别”卡片

当前 `conic_sections` 没有可附加卡片。请新建正式卡片，不要继续留作阻塞项。

建议：

```text
标题：常见二次曲线与积分区域识别
source_ref：math2_core_v2:calculus:conic_sections
类型：优先使用 concept / comparison / diagram；若系统不支持，再使用最接近的类型
章节：高等数学 / 二重积分或定积分几何应用下的规范分类
标签：
- syllabus_required
- must_memorize
- high_frequency
```

内容至少包括：

## 圆

```latex
x^2+y^2=R^2
```

## 椭圆

```latex
\frac{x^2}{a^2}+\frac{y^2}{b^2}=1
```

## 抛物线

```latex
y^2=2px
```

## 双曲线

```latex
\frac{x^2}{a^2}-\frac{y^2}{b^2}=1
```

内容重点：

- 对称轴；
- 顶点；
- 截距；
- 开口方向；
- 常见积分区域识别；
- 不要求加入超出数学二范围的复杂焦点性质。

建立 `conic_sections` 图表关系，并生成预览。

------

# 六、检查并修复 X 型与 Y 型着色

当前报告只说明增加了 `fill_between`。

必须检查 Y 型区域是否真正使用：

```python
ax.fill_betweenx(...)
```

或等价的通用 polygon/path 填充。

不能用 `fill_between(x, ...)` 伪装 Y 型区域。

建议使用同一几何区域验证：

```latex
D=\{(x,y):0\le x\le1,\ x^2\le y\le x\}
```

等价 Y 型描述：

```latex
D=\{(x,y):0\le y\le1,\ y\le x\le\sqrt y\}
```

应实现或确认 GraphSpec 支持：

```json
{
  "orientation": "vertical"
}
```

与：

```json
{
  "orientation": "horizontal"
}
```

字段名称按现有 schema 规范确定。

新增自动测试：

1. 两个 GraphSpec 数值计算面积相同；
2. 随机内部点同时属于两种描述；
3. 随机外部点均不属于区域；
4. Y 型着色确实走 `fill_betweenx` 或通用多边形逻辑；
5. 预览没有横纵轴颠倒。

------

# 七、修复字体警告

当前存在 Unicode `ˣ` 字体缺失警告。

不要保留这个已知限制。

执行：

1. 搜索所有 GraphSpec、标签和测试中的 `ˣ`；
2. 替换为普通 `x`；
3. 或使用 Matplotlib mathtext：

```text
$x$
```

1. 检查其他 Unicode 上标、下标和特殊字形；
2. 渲染日志中不应再出现 glyph missing 警告。

新增测试或日志捕获：

- 渲染 11 个主题时不存在 `Glyph ... missing from font`；
- 中文标签仍可显示；
- 数学变量使用 mathtext；
- Docker 或 CI 字体环境下可复现。

不要提交或分发字体文件。

------

# 八、消除定义域 RuntimeWarning

当前存在由函数边界求值产生的 RuntimeWarning。

不要仅依赖 `_discontinuity_gap()` 在计算后修补。

正确流程：

1. 解析函数定义域；
2. 生成合法采样 mask；
3. 只对合法采样点求值；
4. 使用 `np.errstate` 捕获预期浮点状态；
5. 将非有限值设为 `NaN`；
6. 再执行断点检测；
7. 不跨越空点、渐近线或断开定义域连线。

重点检查：

```latex
\frac{\sin x}{x}
\frac{e^x-1}{x}
\frac{\ln(1+x)}{x}
(1+x)^{1/x}
\left(1+\frac1x\right)^x
```

定义域要求：

- `sin(x)/x`：`x != 0`
- `(e^x-1)/x`：`x != 0`
- `ln(1+x)/x`：`x > -1, x != 0`
- `(1+x)^(1/x)`：`x > -1, x != 0`
- `(1+1/x)^x`：本图仅绘制 `x > 0`

新增测试：

- 非法定义域点从不送入函数求值；
- 渲染时没有 divide-by-zero、invalid-value、invalid-log、invalid-power RuntimeWarning；
- 图线不跨过 `x=0`；
- 对数图不进入 `x<=-1`；
- 空心点 `(0,1)` 正确显示。

非预期 RuntimeWarning 应使测试失败。

------

# 九、箭头标注改为 annotate

当前实现使用：

```python
ax.arrow()
```

请评估并优先改为：

```python
ax.annotate(
    label,
    xy=end_point,
    xytext=text_point,
    arrowprops={"arrowstyle": "->"},
)
```

原因：

- 缩放时箭头头部更稳定；
- 标签和箭头统一；
- 支持数据坐标与偏移坐标；
- 更适合曲率半径、法线、旋转方向等标注。

保持 GraphSpec 的向后兼容：

- 旧 `annotation.type = arrow` 仍可工作；
- renderer 内部可改用 `annotate`；
- 不改变已有 JSON 的必要字段，除非确实需要 schema version 升级。

新增测试验证：

- 箭头起终点正确；
- 标签存在；
- 不超出画布；
- 等轴坐标时箭头方向没有失真。

------

# 十、预览、确认与审核工作流

默认只能生成预览或待审核记录。

不要自动确认所有图表。

脚本应支持安全模式，例如：

```bash
python scripts/generate_math2_diagrams.py --dry-run
python scripts/generate_math2_diagrams.py --generate-previews
python scripts/generate_math2_diagrams.py --confirm --reviewer-id <id>
```

实际参数按项目已有 CLI 风格调整。

## 确认要求

确认必须：

- 使用现有审核服务；
- 验证 reviewer/admin 有效；
- 写入 `reviewed_by`；
- 写入 `reviewed_at`；
- 写入确认时间；
- 创建审计记录；
- 关联最终 FormulaGraphAsset；
- 保留原 GraphSpec；
- 保存 spec hash 和资源 checksum；
- 不确认无关历史预览；
- 已确认相同 spec 时保持幂等。

如果现有服务不支持安全批量确认：

- 保留后台人工确认；
- 脚本只生成预览；
- 在最终报告中明确需要人工审核。

------

# 十一、幂等性和版本行为

相同稳定 slug + 相同规范化 spec hash：

- 不新建重复 GraphSpec；
- 不新建重复预览；
- 不新建重复资产；
- 报告为 `unchanged` 或 `reused`。

相同 slug 但 GraphSpec 发生变化：

- 创建新 spec version 或更新待审核版本；
- 已确认资产不得静默覆盖；
- 旧正式资源保留；
- 新版本进入待审核；
- 记录版本和审计日志。

人工修改过的 GraphSpec：

- 不自动覆盖；
- 报告 conflict；
- 除非有明确 `--force-managed-update` 且环境非生产。

失败时：

- 回滚数据库；
- 删除临时文件；
- 不留下孤立预览记录；
- 不留下无关联资源文件。

------

# 十二、补齐 11 个逻辑主题

最终主题清单：

1. `curvature_circle`
2. `arc_differential`
3. `surface_revolution`
4. `double_int_x_region`
5. `double_int_y_region`
6. `exchange_order_split`
7. `hyperbola_sector`
8. `conic_sections`
9. `three_basic_limits`
10. `second_important_limit`
11. `exponential_decay_family`

X 型和 Y 型可在一个双面板资源中展示，但数据库中必须能明确识别两个逻辑内容，至少通过：

- panel slug；
- 子图元数据；
- 或两个独立图表记录。

不要只用“4+5”作为一个无法分别检索的模糊记录。

------

# 十三、数学样例固定

继续使用并验证以下样例。

## 曲率圆

```latex
x=t^2,\qquad y=t,\qquad t_0=0
```

预期：

```latex
P=(0,0)
C=\left(\frac12,0\right)
\rho=\frac12
\left(x-\frac12\right)^2+y^2=\frac14
```

切线：

```latex
x=0
```

法线：

```latex
y=0
```

## 分区换序

```latex
D=\{(x,y):0\le x\le1,\ x^2\le y\le2-x\}
```

交换后：

```latex
D_1=\{(x,y):0\le y\le1,\ 0\le x\le\sqrt y\}
D_2=\{(x,y):1\le y\le2,\ 0\le x\le2-y\}
```

## 双曲线区域

```latex
1\le xy\le2,\qquad x\le y\le2x
```

边界：

```latex
xy=1,\quad xy=2,\quad y=x,\quad y=2x
```

必须形成第一象限有界区域，并标出四个交点。

## 指数衰减族

固定参数：

```text
(alpha, beta) = (1,1), (2,1), (2,2)
```

验证：

```latex
x_{\max}=\frac{\alpha}{\beta}
f_{\max}=
\left(\frac{\alpha}{\beta e}\right)^\alpha
```

------

# 十四、公共 API 与前端验证

检查公共公式卡 API 和小程序展示逻辑。

要求：

- 草稿 GraphSpec 不公开；
- 待审核预览不公开；
- 只有已确认且关联已发布卡片的图表公开；
- 一张卡能返回多张图表；
- 返回值有稳定排序；
- 每张图包含：
  - slug；
  - title；
  - alt_text；
  - description；
  - width；
  - height；
  - asset URL；
  - status；
  - sort_order。

确保旧客户端仍可工作：

- 保留原单图字段作为兼容字段；
- 或提供首图作为 legacy graph；
- 新客户端读取 `graphs[]`。

小程序端验证：

- 一卡多图可滑动或纵向展示；
- 图片不互相覆盖；
- 预设宽高避免布局抖动；
- 手机宽度下文字可读；
- 多面板图可点击查看大图；
- 深色模式背景可辨认；
- 不能只靠颜色表达不同区域。

------

# 十五、测试要求

在现有 67 项测试基础上补充。

至少覆盖：

## 数据模型

1. 一个公式卡可关联多个 GraphSpec。
2. 每个 GraphSpec slug 唯一。
3. 删除或更新一个图表不影响同卡其他图表。
4. 旧单 graph_spec 兼容读取。
5. Alembic upgrade/downgrade 可执行。
6. SQLite 执行通过。
7. PostgreSQL 迁移语法兼容。

## 幂等性

1. 相同 spec 第二次运行不创建重复记录。
2. 相同 spec 第二次运行不创建重复文件。
3. 修改 spec 后生成新待审核版本。
4. 已确认资产不被静默覆盖。
5. 人工修改冲突可检测。

## 数学正确性

1. 曲率圆圆心、半径和切点正确。
2. X 型和 Y 型区域面积一致。
3. 分区区域并集等于原区域。
4. 双曲线区域有四条边界且有界。
5. 极限函数不在非法定义域求值。
6. 曲线不跨越空点连线。
7. 指数衰减极值点正确。
8. 二次曲线方程和面板匹配。

## 渲染质量

1. 无字体缺失警告。
2. 无非预期 RuntimeWarning。
3. 所有预览文件存在且非空。
4. 图片尺寸和文件大小在限制内。
5. 等轴图比例正确。
6. Y 型区域使用横向填充逻辑。
7. 箭头标签不会越界。
8. 所有资源都有 alt_text。

## API

1. 草稿图表不出现在公共 API。
2. 待审核预览不出现在公共 API。
3. 已确认图表通过公共 API 返回。
4. 一张卡可返回多张图。
5. 图表排序稳定。
6. 旧单图兼容字段仍可用。

## 清理

1. 渲染失败不留下孤立数据库记录。
2. 渲染失败不留下临时文件。
3. dry-run 不写数据库、不写正式资源。

------

# 十六、执行验证

实际运行：

1. 数据库迁移；
2. dry-run；
3. 生成全部预览；
4. 再运行一次验证幂等；
5. 运行全部图表测试；
6. 运行公式 seed 测试；
7. 运行相关 API 测试；
8. 运行后端完整测试；
9. 如修改小程序或后台，运行对应 lint/typecheck/build；
10. 检查渲染日志中：

- 无 glyph missing；
- 无非预期 RuntimeWarning；
- 无孤立资源；

1. 审计 11 个主题的数据库记录和文件；
2. 验证一卡多图公共 API 返回。

不要对生产数据库自动执行迁移或确认。

------

# 十七、最终状态要求

Phase 2 只有在以下条件全部满足时才能标记完成：

- 11 个逻辑主题均有预览或正式记录；
- `conic_sections` 已有卡片；
- 不再发生一卡单 GraphSpec 覆盖；
- 字体警告已修复；
- RuntimeWarning 已修复；
- X/Y 区域语义验证通过；
- 所有自动化测试通过；
- 公共 API 支持一卡多图；
- 未确认资源不会公开；
- 人工审核状态明确。

若预览仍未人工确认，可写：

```text
Implementation complete, pending manual visual review and confirmation.
```

不要写成公共端发布全部完成。

------

# 十八、最终汇报格式

## 1. 审计结果

- 原数据模型；
- 覆盖风险；
- ID 硬编码情况；
- 当前图表状态。

## 2. 数据模型修改

按文件列出：

```text
文件路径
- 修改内容
- 修改原因
```

## 3. 迁移结果

- migration revision；
- SQLite 结果；
- PostgreSQL 兼容情况；
- upgrade/downgrade 结果。

## 4. 图表完成表

| Slug | 关联卡片 source_ref | GraphSpec | Preview | Review | Asset | Public |
| ---- | ------------------- | --------- | ------- | ------ | ----- | ------ |
|      |                     |           |         |        |       |        |

## 5. 一卡多图验证

列出：

- “两个重要极限”关联的图；
- “二重积分交换次序模板”关联的图；
- 是否仍存在覆盖。

## 6. 警告清理

- 字体警告；
- RuntimeWarning；
- 其他渲染警告。

## 7. 幂等性

```text
Created specs:
Updated specs:
Unchanged specs:
Created previews:
Reused previews:
Created assets:
Conflicts:
Errors:
```

## 8. 测试结果

逐条列出执行命令和结果。

## 9. 人工审核项

列出需要人工查看的预览，不要自动声称视觉审核通过。

## 10. 未完成事项

只列出真实未完成项，并说明具体原因。

请直接修改仓库、执行迁移和测试、生成缺失预览，并给出最终结果。不要只提供代码片段或实现建议。
