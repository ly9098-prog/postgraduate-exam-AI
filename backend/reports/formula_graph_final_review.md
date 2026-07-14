# 公式函数图像最终审核报告
生成时间: 2026-07-14 11:21:24 UTC
数据库: sqlite+aiosqlite:///./postgraduate.db (开发环境)
总 function_graph 公式数: 35

## 状态摘要
- 已有正式图像 (ready): 13
- 草稿预览 (draft): 22
- 生成失败 (failed): 0

## 审核决策摘要
- **confirm**: 21 条
- **edit_spec_then_regenerate**: 1 条
- **keep_existing**: 13 条

## 逐条审核结果

### ID=58: 常数函数 y=C
- 卡片状态: published | 图像状态: ready
- 图像资源: 有 (generated)
- Preview 有效期: 已过期
- 图像视觉效果: passed
- 数学正确性: passed
- 缩略图可读: 是
- **最终决策**: `keep_existing`

### ID=59: 一次函数 y=kx+b
- 卡片状态: draft | 图像状态: ready
- 图像资源: 有 (template)
- Preview 有效期: 已过期
- 图像视觉效果: passed
- 数学正确性: passed
- 缩略图可读: 是
- **最终决策**: `keep_existing`

### ID=60: 二次函数 y=ax^2+bx+c
- 卡片状态: published | 图像状态: ready
- 图像资源: 有 (template)
- Preview 有效期: 已过期
- 图像视觉效果: passed
- 数学正确性: passed
- 缩略图可读: 是
- **最终决策**: `keep_existing`

### ID=61: y=|x|
- 卡片状态: draft | 图像状态: ready
- 图像资源: 有 (template)
- Preview 有效期: 已过期
- 图像视觉效果: passed
- 数学正确性: passed
- 缩略图可读: 是
- **最终决策**: `keep_existing`

### ID=62: y=1/x 与 y=1/x^2
- 卡片状态: published | 图像状态: ready
- 图像资源: 有 (template)
- Preview 有效期: 已过期
- 图像视觉效果: passed
- 数学正确性: passed
- 缩略图可读: 是
- **最终决策**: `keep_existing`

### ID=63: 幂函数（正整数与负整数）y=x^n 与 y=x^{-n}
- 卡片状态: draft | 图像状态: draft
- 图像资源: 无 (无)
- Preview 有效期: 有效
- 图像视觉效果: passed
- 数学正确性: passed_with_notes
- 缩略图可读: 是
- 待处理问题:
  - 需人工审核
- 所需修正:
  - 正整数幂 (x, x², x³) 定义域正确
  - 负整数幂 (1/x, 1/x²) 无定义域问题
- **最终决策**: `confirm`

### ID=64: 幂函数（有理指数）y=x^{1/n} 与 y=x^{m/n}
- 卡片状态: draft | 图像状态: draft
- 图像资源: 无 (无)
- Preview 有效期: 有效
- 图像视觉效果: passed
- 数学正确性: passed_with_notes
- 缩略图可读: 是
- 待处理问题:
  - 需人工审核
- 所需修正:
  - x^0.5 定义域 x≥0 正确
  - x^(1/3) 限制在 [0,4] 可接受
  - x^(2/3) 允许负数区域
- **最终决策**: `confirm`

### ID=65: 幂函数 α 值对比
- 卡片状态: draft | 图像状态: draft
- 图像资源: 无 (无)
- Preview 有效期: 有效
- 图像视觉效果: passed
- 数学正确性: passed_with_notes
- 缩略图可读: 是
- 待处理问题:
  - 需人工审核
- 所需修正:
  - α=2,1,0.5,-1 覆盖全部必要类型
  - 图例标注明确
  - 均过 (1,1) 点
- **最终决策**: `confirm`

### ID=66: 指数函数底数对比 y=a^x
- 卡片状态: published | 图像状态: ready
- 图像资源: 有 (template)
- Preview 有效期: 已过期
- 图像视觉效果: passed
- 数学正确性: passed
- 缩略图可读: 是
- **最终决策**: `keep_existing`

### ID=67: 对数函数底数对比 y=log_a x
- 卡片状态: published | 图像状态: ready
- 图像资源: 有 (template)
- Preview 有效期: 已过期
- 图像视觉效果: passed
- 数学正确性: passed
- 缩略图可读: 是
- **最终决策**: `keep_existing`

### ID=68: 指数函数与对数函数反函数关系
- 卡片状态: draft | 图像状态: draft
- 图像资源: 无 (无)
- Preview 有效期: 有效
- 图像视觉效果: passed
- 数学正确性: passed_with_notes
- 缩略图可读: 是
- 待处理问题:
  - 需人工审核
- 所需修正:
  - 指数、对数和 y=x 三条曲线
  - 定义域正确
- **最终决策**: `confirm`

### ID=69: y=sin x
- 卡片状态: published | 图像状态: ready
- 图像资源: 有 (template)
- Preview 有效期: 已过期
- 图像视觉效果: passed
- 数学正确性: passed
- 缩略图可读: 是
- **最终决策**: `keep_existing`

### ID=70: y=cos x
- 卡片状态: draft | 图像状态: draft
- 图像资源: 无 (无)
- Preview 有效期: 有效
- 图像视觉效果: passed
- 数学正确性: passed
- 缩略图可读: 是
- **最终决策**: `confirm`

### ID=71: 正弦与余弦对比
- 卡片状态: draft | 图像状态: draft
- 图像资源: 无 (无)
- Preview 有效期: 有效
- 图像视觉效果: passed
- 数学正确性: passed_with_notes
- 缩略图可读: 是
- 待处理问题:
  - 需人工审核
- 所需修正:
  - sin 和 cos 相位差正确
- **最终决策**: `confirm`

### ID=72: y=tan x
- 卡片状态: published | 图像状态: ready
- 图像资源: 有 (template)
- Preview 有效期: 已过期
- 图像视觉效果: passed
- 数学正确性: passed
- 缩略图可读: 是
- **最终决策**: `keep_existing`

### ID=73: y=cot x
- 卡片状态: draft | 图像状态: draft
- 图像资源: 无 (无)
- Preview 有效期: 有效
- 图像视觉效果: passed_with_notes
- 数学正确性: passed
- 缩略图可读: 是
- 待处理问题:
  - 未绘制竖直渐近线虚线（间断点检测仍可正确断线）
- 所需修正:
  - 建议在 spec 中添加 vertical_lines 标注渐近线位置（非必须）
- **最终决策**: `confirm`

### ID=74: 正切与余切对比
- 卡片状态: draft | 图像状态: draft
- 图像资源: 无 (无)
- Preview 有效期: 有效
- 图像视觉效果: passed_with_notes
- 数学正确性: passed
- 缩略图可读: 是
- 待处理问题:
  - 未绘制竖直渐近线虚线（间断点检测仍可正确断线）
- 所需修正:
  - 建议在 spec 中添加 vertical_lines 标注渐近线位置（非必须）
- **最终决策**: `confirm`

### ID=75: y=sec x, y=csc x
- 卡片状态: draft | 图像状态: draft
- 图像资源: 无 (无)
- Preview 有效期: 有效
- 图像视觉效果: passed_with_notes
- 数学正确性: passed
- 缩略图可读: 是
- 待处理问题:
  - 未绘制竖直渐近线虚线（间断点检测仍可正确断线）
- 所需修正:
  - 建议在 spec 中添加 vertical_lines 标注渐近线位置（非必须）
- **最终决策**: `confirm`

### ID=76: y=arcsin x
- 卡片状态: draft | 图像状态: draft
- 图像资源: 无 (无)
- Preview 有效期: 有效
- 图像视觉效果: passed
- 数学正确性: passed
- 缩略图可读: 是
- **最终决策**: `confirm`

### ID=77: y=arccos x
- 卡片状态: draft | 图像状态: draft
- 图像资源: 无 (无)
- Preview 有效期: 有效
- 图像视觉效果: passed
- 数学正确性: passed
- 缩略图可读: 是
- **最终决策**: `confirm`

### ID=78: y=arctan x
- 卡片状态: draft | 图像状态: draft
- 图像资源: 无 (无)
- Preview 有效期: 有效
- 图像视觉效果: passed
- 数学正确性: passed
- 缩略图可读: 是
- **最终决策**: `confirm`

### ID=79: y=arccot x
- 卡片状态: draft | 图像状态: draft
- 图像资源: 无 (无)
- Preview 有效期: 有效
- 图像视觉效果: passed
- 数学正确性: passed
- 缩略图可读: 是
- **最终决策**: `confirm`

### ID=80: y=x+1/x
- 卡片状态: draft | 图像状态: draft
- 图像资源: 无 (无)
- Preview 有效期: 有效
- 图像视觉效果: passed
- 数学正确性: passed
- 缩略图可读: 是
- **最终决策**: `confirm`

### ID=81: y=xe^{-x} 与 y=x^n e^{-x}
- 卡片状态: draft | 图像状态: draft
- 图像资源: 无 (无)
- Preview 有效期: 有效
- 图像视觉效果: passed
- 数学正确性: passed_with_notes
- 缩略图可读: 是
- 待处理问题:
  - 需人工审核
- 所需修正:
  - 参数 n=1, n=2 明确写入图例
  - 极值点 (1,1/e) 正确
- **最终决策**: `confirm`

### ID=82: y=ln x / x
- 卡片状态: draft | 图像状态: draft
- 图像资源: 无 (无)
- Preview 有效期: 有效
- 图像视觉效果: passed
- 数学正确性: passed
- 缩略图可读: 是
- **最终决策**: `confirm`

### ID=83: 平移变换 y=f(x-a)+b
- 卡片状态: draft | 图像状态: draft
- 图像资源: 无 (无)
- Preview 有效期: 有效
- 图像视觉效果: passed
- 数学正确性: passed_with_notes
- 缩略图可读: 是
- 待处理问题:
  - 需人工审核
- 所需修正:
  - 具体参数 a=2, b=1 明确
  - 三面板对比清晰
- **最终决策**: `confirm`

### ID=84: 综合变换 y=af(bx+c)+d
- 卡片状态: draft | 图像状态: draft
- 图像资源: 无 (无)
- Preview 有效期: 有效
- 图像视觉效果: passed
- 数学正确性: passed_with_notes
- 缩略图可读: 是
- 待处理问题:
  - 需人工审核
- 所需修正:
  - 具体参数 a=2, a=-1, h=-1, k=2 明确
  - 基准→伸缩→反射+平移 三面板
- **最终决策**: `confirm`

### ID=85: 绝对值变换对比 y=|f(x)| 与 y=f(|x|)
- 卡片状态: published | 图像状态: ready
- 图像资源: 有 (template)
- Preview 有效期: 已过期
- 图像视觉效果: passed
- 数学正确性: passed
- 缩略图可读: 是
- **最终决策**: `keep_existing`

### ID=86: 原函数与导函数图像关系
- 卡片状态: draft | 图像状态: draft
- 图像资源: 无 (无)
- Preview 有效期: 有效
- 图像视觉效果: passed
- 数学正确性: passed_with_notes
- 缩略图可读: 是
- 待处理问题:
  - 需人工审核
- 所需修正:
  - f(x)=x³-3x 与 f'(x)=3x²-3 数学一致
  - 极值点标注正确
- **最终决策**: `confirm`

### ID=87: 常见有理函数及其渐近线
- 卡片状态: draft | 图像状态: draft
- 图像资源: 无 (无)
- Preview 有效期: 有效
- 图像视觉效果: failed
- 数学正确性: failed
- 缩略图可读: 是
- 待处理问题:
  - 可去间断点标注位置错误: 标注在(-1,0)，但正确位置应是(-1,-0.5)
- 所需修正:
  - 修改 annotation 从 (-1,0) 到 (-1,-0.5)
  - 重新生成 preview 后确认
- **最终决策**: `edit_spec_then_regenerate`

### ID=88: 对数·幂·指数增长速度对比
- 卡片状态: draft | 图像状态: draft
- 图像资源: 无 (无)
- Preview 有效期: 有效
- 图像视觉效果: passed
- 数学正确性: passed_with_notes
- 缩略图可读: 是
- 待处理问题:
  - 需人工审核
- 所需修正:
  - ln x, √x, x, x², eˣ 五种增长对比
  - 定义域 [0,5] 合理
- **最终决策**: `confirm`

### ID=89: 分段函数典型图像：sgn x 与 \lfloor x\rfloor
- 卡片状态: draft | 图像状态: ready
- 图像资源: 有 (template)
- Preview 有效期: 已过期
- 图像视觉效果: passed
- 数学正确性: passed
- 缩略图可读: 是
- **最终决策**: `keep_existing`

### ID=90: 四类间断点图像对比
- 卡片状态: draft | 图像状态: draft
- 图像资源: 无 (无)
- Preview 有效期: 有效
- 图像视觉效果: passed
- 数学正确性: passed_with_notes
- 缩略图可读: 是
- 待处理问题:
  - 需人工审核
- 所需修正:
  - 四类间断点（可去/跳跃/无穷/振荡）正确
  - 空心点标注正确
- **最终决策**: `confirm`

### ID=91: 幂指辅助函数 y=x^x
- 卡片状态: published | 图像状态: ready
- 图像资源: 有 (generated)
- Preview 有效期: 已过期
- 图像视觉效果: passed
- 数学正确性: passed
- 缩略图可读: 是
- **最终决策**: `keep_existing`

### ID=92: 指数对数不等式常用辅助函数
- 卡片状态: published | 图像状态: ready
- 图像资源: 有 (generated)
- Preview 有效期: 已过期
- 图像视觉效果: passed
- 数学正确性: passed
- 缩略图可读: 是
- **最终决策**: `keep_existing`

## 时区与 expires_at 分析

### 现象
数据库存储的 expires_at 为无时区 datetime，值约为 2026-07-14 11:30（创建时间为 10:30），
与报告生成时间 18:35 CST 相比看起来像已过期。

### 分析
1. 系统时区为 CST (UTC+8)
2. database 存储的 `expires_at` 为 naive datetime，实际表示的是 UTC 时间
3. 服务代码中：
   - 写入: `datetime.now(timezone.utc)` (aware UTC)
   - 读取检查: `datetime.utcnow()` (naive UTC)
   - SQLite 将 aware datetime 序列化为 naive 字符串存储
4. 由于写入和检查都使用同一 UTC 基准，功能上正确
5. 但 `isoformat()` 输出缺少时区标识（无 Z 或 +00:00），导致报告阅读困难

### 当前预览有效期状态
- 所有 22 个 preview 仍有效（剩余约 12-15 分钟）
- Preview 文件在磁盘上仍存在

### 建议
1. 在 `_preview_to_dict()` 中使用 `expires_at.isoformat() + 'Z'` 或 UTC 时间标识
2. 考虑将所有 datetime 列统一使用 timezone-aware 存储（需升级到 PostgreSQL）
3. 当前不影响功能，可在生产数据库切换时一并修复

## 确认计划

### 第一轮：可直接确认 (auto_approvable)
候选 IDs: 70, 76, 77, 78, 79, 80, 82
这些卡片均满足：
- preview_token 有效
- 无 quality error
- 数学审核通过
- GraphSpec 与公式正文一致
- 非生产数据库

### 第一轮：需人工审核 (manual_review)
候选 IDs: 63, 64, 65, 68, 71, 73, 74, 75, 81, 83, 84, 86, 88, 90
这些卡片虽标记为 manual_review，但基于 GraphSpec 数学检查确认无误，可在人工复核后确认。

### 需重新生成
ID=87: 标注位置错误，需修正 spec 后重新生成

### 已存在正式资源
IDs: 58, 59, 60, 61, 62, 66, 67, 69, 72, 85, 89, 91, 92

## 待发布公式卡片 (card_status= draft)

以下 25 条公式虽然图像已就绪或可确认，但卡片仍为 draft 状态：

- ID=59: 一次函数 y=kx+b (graph_status=ready, final_action=keep_existing)
- ID=61: y=|x| (graph_status=ready, final_action=keep_existing)
- ID=63: 幂函数（正整数与负整数）y=x^n 与 y=x^{-n} (graph_status=draft, final_action=confirm)
- ID=64: 幂函数（有理指数）y=x^{1/n} 与 y=x^{m/n} (graph_status=draft, final_action=confirm)
- ID=65: 幂函数 α 值对比 (graph_status=draft, final_action=confirm)
- ID=68: 指数函数与对数函数反函数关系 (graph_status=draft, final_action=confirm)
- ID=70: y=cos x (graph_status=draft, final_action=confirm)
- ID=71: 正弦与余弦对比 (graph_status=draft, final_action=confirm)
- ID=73: y=cot x (graph_status=draft, final_action=confirm)
- ID=74: 正切与余切对比 (graph_status=draft, final_action=confirm)
- ID=75: y=sec x, y=csc x (graph_status=draft, final_action=confirm)
- ID=76: y=arcsin x (graph_status=draft, final_action=confirm)
- ID=77: y=arccos x (graph_status=draft, final_action=confirm)
- ID=78: y=arctan x (graph_status=draft, final_action=confirm)
- ID=79: y=arccot x (graph_status=draft, final_action=confirm)
- ID=80: y=x+1/x (graph_status=draft, final_action=confirm)
- ID=81: y=xe^{-x} 与 y=x^n e^{-x} (graph_status=draft, final_action=confirm)
- ID=82: y=ln x / x (graph_status=draft, final_action=confirm)
- ID=83: 平移变换 y=f(x-a)+b (graph_status=draft, final_action=confirm)
- ID=84: 综合变换 y=af(bx+c)+d (graph_status=draft, final_action=confirm)
- ID=86: 原函数与导函数图像关系 (graph_status=draft, final_action=confirm)
- ID=87: 常见有理函数及其渐近线 (graph_status=draft, final_action=edit_spec_then_regenerate)
- ID=88: 对数·幂·指数增长速度对比 (graph_status=draft, final_action=confirm)
- ID=89: 分段函数典型图像：sgn x 与 \lfloor x\rfloor (graph_status=ready, final_action=keep_existing)
- ID=90: 四类间断点图像对比 (graph_status=draft, final_action=confirm)

这些卡片不会出现在公开小程序列表中，需要单独发布流程。