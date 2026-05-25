# 数学检测测试夹具

> 所有测试 PDF 均为开发者自制，使用 pymupdf `insert_htmlbox` 生成，不含版权真题内容。

## 生成方式

```bash
python3 -c "
import fitz
doc = fitz.open()
page = doc.new_page()
page.insert_htmlbox((50, 50, 500, 700), '<p>...Unicode 数学字符...</p>')
doc.save('xxx.pdf')
"
```

字符通过 CharisSIL 字体（pymupdf HTML 渲染自带）嵌入，支持希腊字母和常见数学运算符的 Unicode 字形。

## 文件清单

| 文件 | 说明 | 页数 | 公式特征 |
|------|------|------|----------|
| `t01_latex_math.pdf` | LaTeX 编译风格 | 3 | 积分∫、极限 lim、级数Σ、矩阵、希腊字母 αβγ、梯度∇、全称量词∀ε-∃δ |
| `t02_mathtype_export.pdf` | MathType 导出风格 | 3 | 期望/方差/正态分布公式、内积⟨⟩、SVD、牛顿法、梯形法则 |
| `t03_ascii_formula.pdf` | 408 ASCII 表达式 | 3 | 纯 ASCII：T(n)=O(nlogn)、IEEE 754、银行家算法、Cache 命中率等 |

## 验收阈值

| 指标 | 测试 PDF | 要求 |
|------|----------|------|
| 召回率 | T01 | ≥ 60% |
| 召回率 | T02 | ≥ 50%（MathType 字体名不稳定，阈值较低） |
| 误检率 | T03 | ≤ 10% |
| 无公式页面误检 | 所有 | = 0 |
| 空白页 / 无文字层 | 运行时生成 | 返回空列表，不抛异常 |
