# OCR真实案例回归集建设

基于上一轮审计结果：

当前 OCR Regression 覆盖率仅 21/100。

主要原因：

- 全部 Case 为人工构造文本
- 没有真实 OCR 输入
- 没有真实图片参与测试
- 无法验证 OCR → OCR纠错 → Normalizer → Splitter → Matcher 全链路

项目中已有：

ocr_test/

包含：

- success 图片（1张）
- failed 图片（4张）

请不要新增规则。

请基于这些真实图片完成一次真实案例审计。

任务：

1. 扫描 ocr_test 目录
2. 对每张图片执行完整导题链路
3. 输出：
   - OCR原始结果
   - OCR纠错结果
   - 最终导题结果
4. 判断问题出在哪一层：
   - PaddleOCR
   - Qwen纠错层（如存在）
   - FormulaNormalizer
   - TextNormalizer
   - QuestionSplitter
   - Matcher
5. 对失败案例分类：
   - 两栏串行
   - 跨页断裂
   - 水印污染
   - 页眉页脚
   - 表格丢失
   - 题号错误
   - 选项错误
   - 公式错误
   - OCR误识别
   - 其他
6. 输出每张图片的错误归因分析。

最终生成：

| 图片 | 是否成功 | 错误类型 | 根因模块 |
| ---- | -------- | -------- | -------- |
|      |          |          |          |

并评估：

这些真实案例是否应该纳入 OCR Regression。

对于适合作为长期回归样本的案例：

生成对应：

tests/ocr_regression/cases/

目录结构建议。

不要修改业务代码。

不要新增规则。

只做真实案例分析与回归集规划。