请直接修改当前项目，在公式表/公式库中新增以下两项内容：

1. 华里士公式（点火公式）
2. 特殊函数：关系 x=sin y 在 0≤y≤2π 上的分支公式及高清图像

重要说明：

- 本任务没有可供读取的参考图片。
- 不要寻找或等待图片附件。
- 以下文字中给出的公式、分段条件、图像关键点和绘图要求，就是完整且唯一的参考依据。
- 请直接检查项目代码、数据库结构、公式导入机制和图像生成机制，然后完成实际修改。
- 不要只给出修改建议。
- 必须修改代码或数据文件、同步当前数据库、生成高清图片并进行验证。
- 不得引用任何外部低清教材截图作为最终图片。

---

# 一、先检查项目结构

开始前，请检查当前项目并确定：

1. 公式卡片的数据模型和数据库表；
2. 公式分类的数据模型和数据库表；
3. 公式标签及关联表；
4. 公式图像、图像规格和图像资产相关表；
5. 公式库的 JSON、YAML、Python 种子文件或其他源数据；
6. 公式导入、同步、upsert 或初始化脚本；
7. 公式查询和详情 API；
8. 公式图像渲染器；
9. 当前项目实际使用的 SQLite 数据库。

可能存在但不限定于以下命名：

- `formula_cards`
- `formula_categories`
- `formula_tags`
- `formula_card_tags`
- `formula_graph_specs`
- `formula_graph_assets`
- `formula_graph_spec_renderer.py`
- `formula_graph_asset_service.py`
- `postgraduate.db`

请以项目的实际结构为准，不要因为名称不同而停止。

在修改数据库前，为当前数据库创建备份，例如：

```text
postgraduate.db.bak_before_wallis_special_function
```

所有新增逻辑必须幂等。重复运行导入、初始化或同步命令时，不得生成：

- 重复公式卡片；
- 重复分类；
- 重复标签；
- 重复卡片标签关联；
- 重复图像规格；
- 重复图像资产。

优先使用稳定且唯一的 `source_ref` 或项目内等价字段执行 upsert。

分类必须通过分类 code、slug 或名称查询，不要在代码中硬编码数据库自增 ID。

------

# 二、新增公式卡片：华里士公式（点火公式）

## 1. 卡片基本信息

标题：

```text
华里士公式（点火公式）
```

别名或搜索关键词至少包含：

```text
华里士公式
Wallis公式
Wallis integral
点火公式
正弦幂积分
余弦幂积分
正弦余弦幂积分
三角函数幂积分
```

建议元数据：

```text
exam_scope: math2
card_type: pure_formula
status: published
source_type: manual
source_title: 华里士公式（点火公式）
source_ref: math2_manual:calculus:wallis_formula
graph_status: not_applicable
```

建议标签：

```text
syllabus_required
high_frequency
must_memorize
error_prone
```

优先放入已有的定积分公式分类，例如：

```text
math2_high_math__定积分__公式
```

如果不存在，则选择项目已有的“一元函数积分学”“定积分公式”或含义最接近的分类。

不要新建含义重复的分类。

## 2. 摘要

摘要可写为：

```text
华里士公式用于计算正弦、余弦整数次幂在 [0,π/2] 或 [0,π] 上的定积分。其核心是相差 2 次幂的递推关系，并根据 n 的奇偶性得到不同的连乘表达式。
```

## 3. 完整公式内容

以下公式必须全部录入。

不得只保存递推公式。

不得省略 `[0,π]` 上的正弦积分和余弦积分。

不得用双阶乘形式替代原始连乘形式。

### 公式块 1：基本定义和递推公式

```latex
I_n
=
\int_0^{\frac{\pi}{2}}\sin^n x\,dx
=
\int_0^{\frac{\pi}{2}}\cos^n x\,dx
I_n=\frac{n-1}{n}I_{n-2},
\qquad n\ge 2
I_0=\frac{\pi}{2},
\qquad
I_1=1
```

可以将以上三式保存为一个公式块，也可以保存为多个有序公式块，但前端展示时必须完整。

### 公式块 2：`[0,π/2]` 上的正弦、余弦幂积分

必须保存为完整分段公式：

```latex
\int_0^{\frac{\pi}{2}}\sin^n x\,dx
=
\int_0^{\frac{\pi}{2}}\cos^n x\,dx
=
\begin{cases}
\displaystyle
\frac{n-1}{n}\cdot
\frac{n-3}{n-2}\cdot
\ldots\cdot
\frac{2}{3}\cdot 1,
&
n\text{ 为大于 }1\text{ 的奇数},
\\[10pt]
\displaystyle
\frac{n-1}{n}\cdot
\frac{n-3}{n-2}\cdot
\ldots\cdot
\frac{1}{2}\cdot
\frac{\pi}{2},
&
n\text{ 为正偶数}.
\end{cases}
```

其数学含义必须保持为：

- 当 `n` 是大于 1 的奇数时，连乘最终为 `2/3·1`；
- 当 `n` 是正偶数时，连乘最终为 `1/2·π/2`。

### 公式块 3：`[0,π]` 上的正弦幂积分

```latex
\int_0^\pi\sin^n x\,dx
=
\begin{cases}
\displaystyle
2\cdot
\frac{n-1}{n}\cdot
\frac{n-3}{n-2}\cdot
\ldots\cdot
\frac{2}{3}\cdot 1,
&
n\text{ 为大于 }1\text{ 的奇数},
\\[10pt]
\displaystyle
2\cdot
\frac{n-1}{n}\cdot
\frac{n-3}{n-2}\cdot
\ldots\cdot
\frac{1}{2}\cdot
\frac{\pi}{2},
&
n\text{ 为正偶数}.
\end{cases}
```

也就是说：

```latex
\int_0^\pi\sin^n x\,dx=2I_n
```

### 公式块 4：`[0,π]` 上的余弦幂积分

```latex
\int_0^\pi\cos^n x\,dx
=
\begin{cases}
0,
&
n\text{ 为正奇数},
\\[8pt]
\displaystyle
2\cdot
\frac{n-1}{n}\cdot
\frac{n-3}{n-2}\cdot
\ldots\cdot
\frac{1}{2}\cdot
\frac{\pi}{2},
&
n\text{ 为正偶数}.
\end{cases}
```

必须正确体现：

- `n` 为正奇数时，结果为 `0`；
- `n` 为正偶数时，结果为 `2I_n`。

### 公式块 5：可选的双阶乘补充

可以将下式作为“等价形式”或“常用推论”补充，但不能取代前面的连乘公式：

```latex
I_n=
\begin{cases}
\displaystyle
\frac{(n-1)!!}{n!!},
&
n\text{ 为正奇数},
\\[8pt]
\displaystyle
\frac{(n-1)!!}{n!!}\cdot\frac{\pi}{2},
&
n\text{ 为非负偶数}.
\end{cases}
```

## 4. 使用条件

至少录入以下条件：

```text
n 为非负整数。
当 n≥2 时可使用递推关系 I_n=((n-1)/n)I_{n-2}。
n=0 和 n=1 分别使用初值 I_0=π/2、I_1=1。
连乘分段式中的奇数情形按大于 1 的正奇数书写，偶数情形按正偶数书写。
```

## 5. 推论

至少录入：

```latex
\int_0^\pi\sin^n x\,dx=2I_n
\int_0^\pi\cos^n x\,dx=
\begin{cases}
0,&n\text{ 为正奇数},\\
2I_n,&n\text{ 为正偶数}.
\end{cases}
```

## 6. 易错点

至少录入：

```text
奇数连乘最终到 2/3·1。
偶数连乘最终到 1/2·π/2，不能漏掉 π/2。
在 [0,π] 上，正弦幂积分相当于 [0,π/2] 上结果的 2 倍。
在 [0,π] 上，余弦正奇次幂积分为 0，但正弦正奇次幂积分不为 0。
不要混淆积分区间 [0,π/2] 和 [0,π]。
n=0、n=1 应使用初值，不能机械套用图中的正奇数或正偶数连乘式。
```

------

# 三、新增公式卡片：特殊函数公式及图像

## 1. 卡片基本信息

标题：

```text
特殊函数：x=sin y 的分支表示与图像
```

别名或搜索关键词至少包含：

```text
x=sin y
正弦关系曲线
正弦函数反解
反正弦分支
arcsin分支
反正弦多分支
特殊函数图像
横向正弦曲线
```

建议元数据：

```text
exam_scope: math2
card_type: function_graph
status: published
source_type: manual
source_title: x=sin y 在 0≤y≤2π 上的分支表示
source_ref: math2_manual:function:x_equals_sin_y_branches
```

建议标签：

```text
syllabus_required
error_prone
common_inference
```

优先放入已有的反三角函数或函数图像分类，例如：

```text
math2_high_math__函数__反三角函数
```

以项目已有分类体系为准，不要创建语义重复分类。

## 2. 关系式

该卡片讨论的关系为：

```latex
x=\sin y,
\qquad
0\le y\le 2\pi
```

必须明确：

```text
它不是普通的 y=sin x 图像。
横轴是 x，纵轴是 y。
由于一个 x 值通常对应多个 y 值，所以在整个区间内不能只写成 y=arcsin x，必须分支表示。
```

## 3. 摘要

摘要可写为：

```text
在 0≤y≤2π 上，关系 x=sin y 对同一个 x 通常可能对应多个 y，因此不能用单个反正弦主值函数表示。根据 y 所处的区间，可拆分为三个反正弦分支。其图像是以 x 为横轴、y 为纵轴的横向正弦曲线。
```

## 4. 完整分段公式

以下公式必须作为完整公式块保存：

```latex
y=
\begin{cases}
\arcsin x,
&
0\le y\le\frac{\pi}{2},
\\[8pt]
\pi-\arcsin x,
&
\frac{\pi}{2}<y\le\frac{3\pi}{2},
\\[8pt]
2\pi+\arcsin x,
&
\frac{3\pi}{2}<y\le2\pi.
\end{cases}
```

这里采用反正弦主值：

```latex
\arcsin x\in
\left[-\frac{\pi}{2},\frac{\pi}{2}\right]
```

## 5. 各分支的 x 范围

另外保存以下对应关系：

```latex
\begin{aligned}
y&=\arcsin x,
&
x&\in[0,1],
&
y&\in\left[0,\frac{\pi}{2}\right],
\\[4pt]
y&=\pi-\arcsin x,
&
x&\in[-1,1),
&
y&\in\left(\frac{\pi}{2},\frac{3\pi}{2}\right],
\\[4pt]
y&=2\pi+\arcsin x,
&
x&\in(-1,0],
&
y&\in\left(\frac{3\pi}{2},2\pi\right].
\end{aligned}
```

必须严格处理端点：

```text
(0,0) 属于第一分支。
(1,π/2) 只属于第一分支。
(0,π) 属于第二分支。
(-1,3π/2) 只属于第二分支。
(0,2π) 属于第三分支。
```

分支边界不得造成同一端点被重复定义。

## 6. 条件

至少录入：

```text
反正弦函数采用主值范围 arcsin x∈[-π/2,π/2]。
关系中限定 0≤y≤2π。
整个关系的 x 取值范围为 [-1,1]。
```

## 7. 推论与说明

至少录入：

```latex
(x,y)=(\sin t,t),
\qquad
0\le t\le2\pi
```

并说明关键点：

```text
(0,0)
(1,π/2)
(0,π)
(-1,3π/2)
(0,2π)
```

还应说明：

```text
对 x∈(0,1)，通常有两个对应的 y。
对 x∈(-1,0)，通常也有两个对应的 y。
对 x=0，在区间 0≤y≤2π 内有 y=0、π、2π 三个对应值。
因此该关系在整个区间上不是单值函数 y=f(x)。
```

## 8. 易错点

至少录入：

```text
不能把整个关系直接写成 y=arcsin x。
arcsin x 只表示反正弦函数的主值。
第二分支中的 π 不能漏掉。
第三分支中的 2π 不能漏掉。
不要把 x=sin y 错画成 y=sin x。
横轴应为 x，纵轴应为 y。
注意 π/2 和 3π/2 两个分界点的归属。
```

------

# 四、生成全新的高清函数图像

本任务没有原始图像可用。

请根据数学关系重新绘制，不得等待图片，不得使用教材截图，不得从网上下载相同图像。

## 1. 绘图关系

绘制：

```latex
x=\sin y,
\qquad
0\le y\le2\pi
```

可以优先使用参数方程：

```text
x = sin(t)
y = t
0 ≤ t ≤ 2π
```

如果现有绘图系统不支持参数曲线，则使用以下三个显式分支：

```text
分支 1：
y = asin(x)
x ∈ [0,1]

分支 2：
y = π - asin(x)
x ∈ [-1,1)

分支 3：
y = 2π + asin(x)
x ∈ (-1,0]
```

不得通过关闭安全校验或执行任意表达式来实现。

## 2. 图像整体形状

最终曲线从原点开始，按 y 增大的方向依次经过：

```text
(0,0)
(1,π/2)
(0,π)
(-1,3π/2)
(0,2π)
```

视觉上应当是竖直方向延伸的横向正弦曲线：

1. 从 `(0,0)` 向右弯曲；
2. 在 `(1,π/2)` 到达最右端；
3. 再向左回到 `(0,π)`；
4. 继续向左弯曲；
5. 在 `(-1,3π/2)` 到达最左端；
6. 最后向右回到 `(0,2π)`。

这不是普通的水平正弦波 `y=sin x`。

## 3. 图片规范

生成 PNG 图片，建议尺寸：

```text
1600×1000
```

要求：

```text
白色背景
高清
坐标轴清晰
横轴标记为 x
纵轴标记为 y
曲线连续且平滑
不模拟拍照或扫描效果
不添加水印
不添加教材页码
不添加模糊说明文字
```

建议坐标范围：

```text
x ∈ [-1.35,1.35]
y ∈ [-0.25,2π+0.35]
```

建议 x 轴刻度：

```text
-1
0
1
```

建议 y 轴刻度：

```text
0
π/2
π
3π/2
2π
```

标注以下关键点：

```text
(0,0)
(1,π/2)
(0,π)
(-1,3π/2)
(0,2π)
```

图例或曲线标题可写为：

```text
x=sin y
```

可加入浅色网格，但网格不得影响曲线阅读。

曲线颜色和整体排版应遵循项目现有公式图像主题。

请优先使用项目已有中文字体和数学字体，避免中文乱码。

## 4. 图片替代文本

`alt_text` 可设置为：

```text
关系 x=sin y 在 0≤y≤2π 上的图像，由三个反正弦分支组成
```

图片说明可设置为：

```text
横轴为 x，纵轴为 y。曲线依次经过 (0,0)、(1,π/2)、(0,π)、(-1,3π/2)、(0,2π)，表示关系 x=sin y 在一个完整周期内的三个反正弦分支。
```

## 5. 缩略图

除主图外，还应按项目当前机制生成缩略图。

缩略图不得简单指向不存在的地址。

主图和缩略图均必须：

- 能被正常读取；
- MIME 类型正确；
- 数据库记录正确；
- 能通过前端或 API 访问。

------

# 五、检查和修复图像渲染器

请先检查现有图像规格和渲染器是否支持每条表达式使用独立定义域。

例如三个分支应具有不同的 x 区间。

如果现有代码错误地只读取 panel 或画布级别的 domain，而忽略 expression 自身的 domain，请做最小且向后兼容的修复。

逻辑可以类似：

```python
expr_domain = expr_data.get("domain", panel_domain)
```

每个 expression 应能独立定义：

```text
domain
intervals
exclude_points
```

如果已经支持，则不要重复修改。

如果 renderer 不支持自定义刻度，而现有架构允许安全扩展，可增加可选字段，例如：

```json
{
  "x_ticks": [-1, 0, 1],
  "x_tick_labels": ["-1", "0", "1"],
  "y_ticks": [
    0,
    1.5707963267948966,
    3.141592653589793,
    4.71238898038469,
    6.283185307179586
  ],
  "y_tick_labels": [
    "0",
    "π/2",
    "π",
    "3π/2",
    "2π"
  ]
}
```

扩展要求：

- 所有新增字段均为可选；
- 不提供字段时维持旧行为；
- 更新相应 Schema；
- 不破坏现有图像；
- 增加单元测试。

如果现有图像机制不适合扩展，可以使用项目允许的 Python/Matplotlib 离线生成方式，但最终仍须接入项目已有的图像资产存储与访问机制。

------

# 六、图像规格建议

若项目使用 JSON graph spec，可按现有 Schema 转换为等价结构。

示意内容如下，字段名须适配项目实际 Schema，不要机械照抄：

```json
{
  "type": "function_graph",
  "title": "x=sin y, 0≤y≤2π",
  "canvas": {
    "width": 1600,
    "height": 1000,
    "background": "white"
  },
  "axes": {
    "x_label": "x",
    "y_label": "y",
    "x_min": -1.35,
    "x_max": 1.35,
    "y_min": -0.25,
    "y_max": 6.633185307179586,
    "x_ticks": [-1, 0, 1],
    "x_tick_labels": ["-1", "0", "1"],
    "y_ticks": [
      0,
      1.5707963267948966,
      3.141592653589793,
      4.71238898038469,
      6.283185307179586
    ],
    "y_tick_labels": ["0", "π/2", "π", "3π/2", "2π"]
  },
  "expressions": [
    {
      "expression": "asin(x)",
      "domain": {
        "min": 0,
        "max": 1,
        "include_min": true,
        "include_max": true
      }
    },
    {
      "expression": "pi-asin(x)",
      "domain": {
        "min": -1,
        "max": 1,
        "include_min": true,
        "include_max": false
      }
    },
    {
      "expression": "2*pi+asin(x)",
      "domain": {
        "min": -1,
        "max": 0,
        "include_min": false,
        "include_max": true
      }
    }
  ],
  "points": [
    {"x": 0, "y": 0, "label": "(0,0)"},
    {"x": 1, "y": 1.5707963267948966, "label": "(1,π/2)"},
    {"x": 0, "y": 3.141592653589793, "label": "(0,π)"},
    {"x": -1, "y": 4.71238898038469, "label": "(-1,3π/2)"},
    {"x": 0, "y": 6.283185307179586, "label": "(0,2π)"}
  ]
}
```

请根据项目正式 Schema 修改字段结构。

不要把这段示例作为未经校验的任意 JSON 直接落库。

------

# 七、数据源与当前数据库同步

不要只修改当前数据库。

也不要只修改种子数据而不更新当前数据库。

必须同时满足：

1. 新部署环境可通过项目正式初始化或导入流程获得这两张卡片；
2. 当前数据库立即可查询到这两张卡片；
3. 重复执行不会插入重复数据；
4. `source_ref` 唯一且稳定；
5. 分类关联正确；
6. 标签关联正确；
7. 华里士公式卡片不需要图像；
8. 特殊函数卡片必须有主图和缩略图；
9. 特殊函数卡片的图像状态必须为 ready 或项目中的等价成功状态。

建议使用：

```text
math2_manual:calculus:wallis_formula
```

以及：

```text
math2_manual:function:x_equals_sin_y_branches
```

作为两个稳定的唯一来源标识。

如果项目存在公式库版本文件，可新增一个补充文件，例如：

```text
data/formula_library/math2_core_v3_supplements.json
```

如果项目已有固定的扩展文件，则应优先更新现有扩展文件。

如果项目使用迁移、Seeder、CLI 或管理命令，请沿用项目已有机制，不要创建只能执行一次的临时代码。

------

# 八、图像入库与资产处理

特殊函数图像不能只保存在临时文件夹。

请使用项目正式图像资产流程完成：

1. 保存 graph spec；
2. 生成高清主图；
3. 生成缩略图；
4. 创建或更新图像资产数据库记录；
5. 绑定到特殊函数卡片；
6. 更新图像状态；
7. 确认 API 返回有效图片地址；
8. 确认前端可访问主图和缩略图。

如果项目同时存在卡片内嵌的 `graph_spec` 与独立的 `formula_graph_specs` 表，请确认哪一个是权威来源。

不得留下两个内容冲突的图像规格。

不要手工伪造 URL。

------

# 九、测试要求

完成后必须实际运行测试。

## 1. 幂等性测试

连续执行两次新增或导入命令。

然后确认每个 `source_ref` 只有一条卡片。

SQL 可参考：

```sql
SELECT source_ref, COUNT(*) AS card_count
FROM formula_cards
WHERE source_ref IN (
  'math2_manual:calculus:wallis_formula',
  'math2_manual:function:x_equals_sin_y_branches'
)
GROUP BY source_ref;
```

预期：

```text
math2_manual:calculus:wallis_formula                         1
math2_manual:function:x_equals_sin_y_branches                1
```

表名或字段名不同则按实际数据库结构调整。

## 2. 华里士公式内容测试

确认：

- 能查询到“华里士公式”；
- 能查询到“点火公式”；
- 卡片状态为 published；
- 卡片类型为 pure_formula 或项目等价类型；
- 图像状态为 not_applicable 或项目等价状态；
- 包含基本递推公式；
- 包含 `I_0=π/2` 和 `I_1=1`；
- 包含 `[0,π/2]` 上的完整分段公式；
- 包含 `[0,π]` 上的正弦完整分段公式；
- 包含 `[0,π]` 上的余弦完整分段公式；
- 奇数、偶数条件正确；
- LaTeX 反斜线未因 JSON 转义而丢失；
- 前端 KaTeX、MathJax 或当前公式组件可以正常渲染。

## 3. 特殊函数内容测试

确认：

- 能查询到 `x=sin y`；
- 能查询到“反正弦多分支”；
- 卡片状态为 published；
- 卡片类型为 function_graph 或项目等价类型；
- 公式中包含 `x=sin y, 0≤y≤2π`；
- 包含三个完整分支；
- 三个分支的端点开闭正确；
- 包含对应的 x 范围；
- 图像状态为 ready；
- 存在有效主图资产；
- 存在有效缩略图资产；
- API 返回有效图片 URL。

## 4. 图像数学正确性测试

检查曲线是否经过：

```text
(0,0)
(1,π/2)
(0,π)
(-1,3π/2)
(0,2π)
```

可以通过采样或程序断言验证：

```text
sin(0)=0
sin(π/2)=1
sin(π)=0
sin(3π/2)=-1
sin(2π)=0
```

确认：

- 图像横轴为 x；
- 图像纵轴为 y；
- 图像是横向正弦关系；
- 图像不是 `y=sin x`；
- 三段曲线连接后视觉连续；
- 关键点位置正确；
- y 轴刻度标签正确。

## 5. 图片文件测试

使用 PIL、项目图片工具或等价方式检查：

- 主图能打开；
- 缩略图能打开；
- 主图尺寸正确；
- 图片不是空白；
- MIME 类型正确；
- 数据库记录中的文件路径真实存在；
- 图片访问 URL 返回成功。

## 6. 数据库完整性

运行：

```sql
PRAGMA foreign_key_check;
```

结果必须为空。

如不为空，修复后重新验证。

## 7. 回归测试

运行与以下模块有关的现有测试：

```text
公式卡片
公式分类
公式导入
公式搜索
公式详情 API
图像规格
图像渲染器
图像资产
静态文件访问
```

若项目缺少关键测试，请增加最小必要测试。

------

# 十、最终执行报告

任务完成后，请输出实际执行结果，不要只给出方案。

报告至少包括：

1. 检查到的公式库架构；
2. 修改或新增的文件列表；
3. 修改或新增的数据库表记录；
4. 两张新卡片的最终数据库 ID；
5. 两个卡片的最终 `source_ref`；
6. 关联的分类；
7. 关联的标签；
8. 华里士公式最终包含的公式块数量；
9. 特殊函数最终包含的公式块数量；
10. 高清图片实际文件路径；
11. 缩略图实际文件路径；
12. API 返回的图片 URL；
13. 是否修改图像 renderer；
14. 如修改，说明修改原因和兼容性；
15. 实际执行过的命令；
16. 实际运行的测试；
17. 测试通过和失败数量；
18. 两次导入后的幂等性检查结果；
19. `PRAGMA foreign_key_check` 的结果；
20. 尚未解决的问题。

请现在直接开始检查项目并实施修改。

不要要求我补传参考图片，因为所有必要公式和图像信息已经完整写在本任务说明中。

