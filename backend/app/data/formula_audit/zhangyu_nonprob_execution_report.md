# 公式库完整性审计与补全 — 张宇非概率扩展执行报告

> 任务：以《27张宇数学公式手册.pdf》目录为覆盖边界，审计 SQLite 公式库并补全缺失内容。
> 范围：全部目录内容，唯一排除「第三部分 概率论与数理统计」。

## 1. 文件与数据库

| 项目 | 值 |
|------|-----|
| PDF 路径 | `/home/lmh/projects/postgraduate-ai/ocr_test/import/27张宇数学公式手册.pdf` |
| PDF 总页数 | 190（纯扫描版，无文本层） |
| 数据库路径 | `/home/lmh/projects/postgraduate-ai/backend/postgraduate.db` |
| 数据库连接 | `DATABASE_URL=sqlite+aiosqlite:///./postgraduate.db`（相对 backend/ 运行） |
| 备份数据库 | `/home/lmh/projects/postgraduate-ai/backend/postgraduate.db.bak_before_zhangyu_nonprob_20260802_013804` |

## 2. 页码映射

PDF 为纯扫描版，目录无书签，章节页码经 OCR 逐一核对。

- **映射关系：0-indexed PDF 页 = 印刷页码 + 7**（已在 PDF 页 8=印刷页1 的「第一部分」扉页、PDF 页9=印刷页2 的「第一章」、以及 46/47/48/49/50/51/54/55/…/126 等页角数字逐一验证）
- OCR 引擎：PaddleOCR（远程 `http://172.27.64.1:8080/ocr`），识别后逐条人工校验

## 3. 修改前后数量对比

| 表 | 修改前 | 修改后 | 增量 |
|----|-------|-------|------|
| `formula_categories` | 113 | 128 | **+15** |
| `formula_cards` | 227 | 257 | **+30** |
| `formula_card_tags` | 200 | 270 | **+70**（30 张新卡片的标签关系） |
| `formula_tags` | 6 | 6 | 0（全部复用已有标签 code） |
| `formula_card_versions` | 357 | 387 | **+30**（每张新卡片 1 条 create 版本快照） |
| `formula_graph_assets` / `formula_graph_specs` / `formula_graph_previews` | 46 / 10 / 7 | 不变 | 0 |

## 4. 新增分类（15 个）

```
高等数学 / 向量代数与空间解析几何            (chapter, code=vector_space_geometry)
高等数学 / 向量代数与空间解析几何 / 向量代数
高等数学 / 向量代数与空间解析几何 / 空间平面与直线
高等数学 / 向量代数与空间解析几何 / 空间曲面与曲线
高等数学 / 多元函数微分学 / 偏导数在几何中的应用
高等数学 / 二重积分 / 三重积分的计算
高等数学 / 二重积分 / 重积分的应用
高等数学 / 二重积分 / 曲线积分
高等数学 / 二重积分 / 曲面积分
高等数学 / 级数                              (chapter, code=series)
高等数学 / 级数 / 数项级数
高等数学 / 级数 / 幂级数
高等数学 / 级数 / 傅里叶级数
高等数学 / 常微分方程 / 差分方程
线性代数 / 向量 / n维向量空间
```

复用已有章节（不重复创建）：`multivariable`、`double_integral`、`ode`、`vector`。所有新分类 `exam_scope=math2`，沿用父级。

## 5. 新增卡片（30 张，ID 228–257）

| ID | 分类路径 | 标题 | source_ref | PDF 印刷页 | 公式块 |
|----|---------|------|-----------|-----------|-------|
| 228 | 高等数学/向量代数与空间解析几何/向量代数 | 向量的数量积、向量积与混合积 | `:nonprob:vector_space_geometry:scalar_vector_mixed_product` | 39 | 5 |
| 229 | 高等数学/向量代数与空间解析几何/向量代数 | 两向量的夹角、垂直与平行条件 | `:nonprob:vector_space_geometry:vector_angle_direction_cosines` | 40 | 5 |
| 230 | 高等数学/向量代数与空间解析几何/空间平面与直线 | 平面的方程与点到平面的距离 | `:nonprob:vector_space_geometry:plane_equations_point_distance` | 40-41 | 4 |
| 231 | 高等数学/向量代数与空间解析几何/空间平面与直线 | 直线的方程与点到直线的距离 | `:nonprob:vector_space_geometry:line_equations_point_distance` | 41-42 | 5 |
| 232 | 高等数学/向量代数与空间解析几何/空间曲面与曲线 | 空间曲面与曲线的方程 | `:nonprob:vector_space_geometry:surface_curve_equations` | 42-43 | 5 |
| 233 | 高等数学/向量代数与空间解析几何/空间曲面与曲线 | 常见二次曲面 | `:nonprob:vector_space_geometry:quadric_surfaces` | 43-44 | 7 |
| 234 | 高等数学/多元函数微分学/偏导数在几何中的应用 | 空间曲线的切线与法平面 | `:nonprob:multivariable:tangent_normal_plane_curve` | 47-48 | 3 |
| 235 | 高等数学/多元函数微分学/偏导数在几何中的应用 | 曲面的切平面与法线 | `:nonprob:multivariable:tangent_plane_normal_surface` | 48 | 3 |
| 236 | 高等数学/二重积分/三重积分的计算 | 三重积分的直角坐标与柱坐标计算 | `:nonprob:multivariable:triple_integral_rectangular_cylindrical` | 51-52 | 4 |
| 237 | 高等数学/二重积分/三重积分的计算 | 三重积分的球坐标计算 | `:nonprob:multivariable:triple_integral_spherical` | 52 | 3 |
| 238 | 高等数学/二重积分/重积分的应用 | 重积分的几何应用 | `:nonprob:multivariable:multiple_integral_geometric_apps` | 53-54 | 4 |
| 239 | 高等数学/二重积分/重积分的应用 | 重积分的物理应用 | `:nonprob:multivariable:multiple_integral_physical_apps` | 54-55 | 5 |
| 240 | 高等数学/二重积分/曲线积分 | 两类曲线积分的计算(化定积分) | `:nonprob:multivariable:line_integral_to_definite` | 56 | 2 |
| 241 | 高等数学/二重积分/曲线积分 | 格林公式、路径无关与斯托克斯公式 | `:nonprob:multivariable:green_stokes_path_independent` | 56-57 | 3 |
| 242 | 高等数学/二重积分/曲线积分 | 全微分求积 | `:nonprob:multivariable:exact_differential` | 57-58 | 2 |
| 243 | 高等数学/二重积分/曲面积分 | 两类曲面积分的计算(化二重积分) | `:nonprob:multivariable:surface_integral_to_double` | 58 | 3 |
| 244 | 高等数学/二重积分/曲面积分 | 高斯公式 | `:nonprob:multivariable:gauss_formula` | 59 | 1 |
| 245 | 高等数学/二重积分/曲面积分 | 两类积分的关系与梯度散度旋度 | `:nonprob:multivariable:grad_div_rot_relations` | 59-60 | 5 |
| 246 | 高等数学/级数/数项级数 | 数项级数的定义与基本性质 | `:nonprob:series:numerical_series_basics` | 61-62 | 5 |
| 247 | 高等数学/级数/数项级数 | 正项级数的敛散性判别法 | `:nonprob:series:positive_series_criteria` | 62-64 | 5 |
| 248 | 高等数学/级数/数项级数 | 交错级数与任意项级数 | `:nonprob:series:alternating_absolute_conditional` | 64-65 | 4 |
| 249 | 高等数学/级数/幂级数 | 幂级数的定义与收敛半径 | `:nonprob:series:power_series_radius` | 65-66 | 4 |
| 250 | 高等数学/级数/幂级数 | 幂级数的性质 | `:nonprob:series:power_series_properties` | 66-67 | 5 |
| 251 | 高等数学/级数/幂级数 | 泰勒级数与麦克劳林级数 | `:nonprob:series:taylor_maclaurin_series` | 67-68 | 4 |
| 252 | 高等数学/级数/幂级数 | 常用幂级数展开式 | `:nonprob:series:common_maclaurin_expansions` | 68-69 | 7 |
| 253 | 高等数学/级数/傅里叶级数 | 周期为2π的傅里叶级数 | `:nonprob:series:fourier_series_2pi` | 70-71 | 3 |
| 254 | 高等数学/级数/傅里叶级数 | 周期为2l的傅里叶级数与奇偶延拓 | `:nonprob:series:fourier_series_2l_extension` | 71-73 | 7 |
| 255 | 高等数学/常微分方程/差分方程 | 差分的定义与一阶线性差分方程 | `:nonprob:ode:difference_equation_first_order` | 81-82 | 5 |
| 256 | 线性代数/向量/n维向量空间 | 向量空间、基与坐标 | `:nonprob:linalg:n_dim_vector_space_basis` | 119-120 | 4 |
| 257 | 线性代数/向量/n维向量空间 | 基变换与坐标变换 | `:nonprob:linalg:n_dim_vector_space_change_of_basis` | 120-121 | 3 |

> source_ref 完整前缀统一为 `zhangyu_formula_manual:nonprob:<章节code>:<slug>`。所有新卡片 `status=draft`、`card_type=pure_formula`、`source_type=manual`。

## 6. 更新卡片

无。未修改任何已有卡片（保留既有 published 状态、收藏关系与版本）。

## 7. 跳过的重复项

第二次/第三次执行 `--apply`：**Created: 0 / Skipped: 30 / Categories created: 0 / Tags created: 0**。无重复新增。

## 8. manual_review 项

| 项目 | 说明 |
|------|------|
| 常见二次曲面·双叶双曲面 | 印刷页44 的符号在 OCR 中模糊，采用标准式 `x²/a²+y²/b²-z²/c²=-1`，建议对照原页复核 |
| 双曲抛物面 | 印刷页44 方程为 `x²/2p-y²/2q=z`（p,q 同号），符号约定与个别教材相反，建议复核 |

## 9. 明确排除的范围

- 第三部分 概率论与数理统计（印刷页 138–168，PDF idx 145–175）
  - 随机事件、概率分布、随机变量数字特征、大数定律、中心极限定理、数理统计、参数估计 等全部内容
- 未创建任何概率统计分类或卡片（已做范围隔离扫描）

## 10. 新增/修改文件

| 文件 | 类型 |
|------|------|
| `backend/app/data/formula_library/zhangyu_nonprob_extensions_v1.json` | **新增** 源数据（30 张卡片） |
| `backend/scripts/seed_zhangyu_nonprob_formulas.py` | **新增** 幂等导入脚本 |
| `backend/app/data/formula_audit/zhangyu_nonprob_inventory.json` | **新增** 审计-目录覆盖清单 |
| `backend/app/data/formula_audit/zhangyu_nonprob_diff.json` | **新增** 审计-差异分析 |
| `backend/app/data/formula_audit/zhangyu_nonprob_formulas.json` | **新增** 审计-公式提取（含页码） |
| `backend/app/data/formula_audit/zhangyu_nonprob_execution_report.md` | **新增** 本报告 |
| `backend/tests/test_seed_zhangyu_nonprob.py` | **新增** 测试（18 项） |
| `backend/postgraduate.db` | 已应用 |

历史审计文件（`zhangyu_formula_manual_inventory/diff/formulas.json`、`execution_report.md`）**未覆盖**，保留原样。

## 11. 验证结果

### SQLite
- `PRAGMA integrity_check` → `ok`
- `PRAGMA foreign_key_check` → 空（无违规）

### 数据完整性
- 30 张新卡片 formula_blocks 均为合法 JSON 数组，每卡 ≥1 块且 latex 非空
- source_ref 无重复；同分类 title 无重复
- 新分类 parent_id 全部合法（指向真实父级）
- formula_card_tags 无重复关系（+70 均为新关系）
- 每张新卡片均有 version=1 / action=create 版本快照（+30）

### LaTeX
- `{}`、`()`、`[]` 配对均通过
- `\left`/`\right` 配对通过
- `\begin`/`\end` 配对通过（vmatrix、cases 环境）
- 无 OCR 控制字符、无 Unicode 上下标残留
- `\Omega` 的大写 O 触发校验器误报，经人工确认为合法符号

### 范围隔离
- 分类名/标题/aliases/search_text/summary/source_ref 扫描：**无概率统计术语泄漏**
- 「排列组合」「二项式」属初等代数，未因含组合记号被排除

### 幂等性
- 第二次执行 `--apply`：inserted=0, updated=0, skipped=30, categories=0
- 分类数、卡片数、标签关系数不再变化

### 项目测试
- 新增 `tests/test_seed_zhangyu_nonprob.py`：18 项全部通过（schema、概率排除、LaTeX、dry-run 非变更、幂等、生产保护）
- 既有公式相关测试：`test_seed_formula_v2.py` + `test_formulas.py` + `test_formulas_api.py` + `test_admin_formulas.py` = **120 项全部通过**

## 12. 回滚方法

```bash
# 恢复备份（在仓库根目录执行）
cp backend/postgraduate.db.bak_before_zhangyu_nonprob_20260802_013804 backend/postgraduate.db

# 或删除本次新增（谨慎，仅当确认无需保留时）
# 先删除 source_ref 前缀为 zhangyu_formula_manual:nonprob: 的卡片（连同版本/标签/收藏级联），
# 再删除新增分类 code（vector_space_geometry、series 及其下 group）
```

## 13. 运行命令

```bash
cd backend && source .venv/bin/activate

# 预览（不写入）
python scripts/seed_zhangyu_nonprob_formulas.py --dry-run

# 应用（新卡片全部 draft）
python scripts/seed_zhangyu_nonprob_formulas.py --apply

# 幂等验证（第二次执行）
python scripts/seed_zhangyu_nonprob_formulas.py --apply   # Created: 0, Skipped: 30
```
