/**
 * math-question 组件测试用 mock 数据
 * 包含典型 segments 场景，供 Stage 4 并行开发和验收使用
 */

/** 场景 1：纯文本段，无公式 */
var PLAIN_TEXT = [
  { type: 'text', text: '设集合 A={1,2,3,4}，B={2,4,6}，则 A∩B 等于什么？' }
]

/** 场景 2：行内公式（inline），文字与公式混排 */
var INLINE_FORMULA = [
  { type: 'text', text: '设函数 ' },
  {
    type: 'math_image',
    url: 'http://localhost:8000/static/formulas/202506/1_0_a1b2c3d4.png',
    alt: 'f(x) = x^2 + 1',
    display: false
  },
  { type: 'text', text: '，求 ' },
  {
    type: 'math_image',
    url: 'http://localhost:8000/static/formulas/202506/1_0_b2c3d4e5.png',
    alt: "f'(x)",
    display: false
  },
  { type: 'text', text: '。' }
]

/** 场景 3：Display 公式（独立行），如积分 */
var DISPLAY_FORMULA = [
  { type: 'text', text: '计算定积分：' },
  {
    type: 'math_image',
    url: 'http://localhost:8000/static/formulas/202506/2_1_c3d4e5f6.png',
    alt: '\\int_0^1 x^2 \\, dx',
    display: true
  },
  { type: 'text', text: '的值。' }
]

/** 场景 4：混合 inline + display */
var MIXED_FORMULA = [
  { type: 'text', text: '已知矩阵 ' },
  {
    type: 'math_image',
    url: 'http://localhost:8000/static/formulas/202506/3_0_d4e5f6a7.png',
    alt: 'A \\in \\mathbb{R}^{n \\times n}',
    display: false
  },
  { type: 'text', text: '，其特征方程为：' },
  {
    type: 'math_image',
    url: 'http://localhost:8000/static/formulas/202506/3_1_e5f6a7b8.png',
    alt: '\\det(A - \\lambda I) = 0',
    display: true
  },
  { type: 'text', text: '求所有特征值。' }
]

/** 场景 5：图片加载失败（模拟 binderror），应降级展示 alt 文本 */
var IMG_ERROR_FALLBACK = [
  { type: 'text', text: '以下公式图片加载失败，应显示备用文本：' },
  {
    type: 'math_image',
    url: 'http://invalid-host/nonexistent.png',
    alt: '\\sum_{n=1}^{\\infty} \\frac{1}{n^2} = \\frac{\\pi^2}{6}',
    display: true
  }
]

/** 场景 6：多段文本 + 换行 */
var MULTILINE_TEXT = [
  { type: 'text', text: '第一问：求极限 ' },
  {
    type: 'math_image',
    url: 'http://localhost:8000/static/formulas/202506/4_0_f6a7b8c9.png',
    alt: '\\lim_{x \\to 0} \\frac{\\sin x}{x}',
    display: false
  },
  { type: 'newline' },
  { type: 'text', text: '第二问：证明该极限存在。' }
]

/** 场景 7：希腊字母 + 多个 inline 公式 */
var GREEK_INLINE = [
  { type: 'text', text: '设 ' },
  {
    type: 'math_image',
    url: 'http://localhost:8000/static/formulas/202506/5_0_a7b8c9d0.png',
    alt: '\\alpha > 0',
    display: false
  },
  { type: 'text', text: '，' },
  {
    type: 'math_image',
    url: 'http://localhost:8000/static/formulas/202506/5_0_b8c9d0e1.png',
    alt: '\\beta \\in \\mathbb{R}',
    display: false
  },
  { type: 'text', text: '，则 ' },
  {
    type: 'math_image',
    url: 'http://localhost:8000/static/formulas/202506/5_0_c9d0e1f2.png',
    alt: '\\alpha + \\beta',
    display: false
  },
  { type: 'text', text: ' 的符号为？' }
]

/** 场景 8：长题干，多个 display 公式 */
var LONG_STEM = [
  { type: 'text', text: '设 n 阶方阵 A 满足：' },
  {
    type: 'math_image',
    url: 'http://localhost:8000/static/formulas/202506/6_0_d0e1f2a3.png',
    alt: 'A^2 - 3A + 2I = 0',
    display: true
  },
  { type: 'text', text: '（1）证明 A 可逆，并求 ' },
  {
    type: 'math_image',
    url: 'http://localhost:8000/static/formulas/202506/6_0_e1f2a3b4.png',
    alt: 'A^{-1}',
    display: false
  },
  { type: 'text', text: '；（2）求矩阵 ' },
  {
    type: 'math_image',
    url: 'http://localhost:8000/static/formulas/202506/6_1_f2a3b4c5.png',
    alt: '(A - I)^{-1}',
    display: false
  },
  { type: 'text', text: '。' }
]

/** 场景 9：纯 display 公式（无文字，仅公式） */
var DISPLAY_ONLY = [
  {
    type: 'math_image',
    url: 'http://localhost:8000/static/formulas/202506/7_0_a3b4c5d6.png',
    alt: '\\nabla f(x^*) = 0',
    display: true
  }
]

/** 场景 10：空 segments（降级处理，不渲染） */
var EMPTY_SEGMENTS = []

module.exports = {
  PLAIN_TEXT,
  INLINE_FORMULA,
  DISPLAY_FORMULA,
  MIXED_FORMULA,
  IMG_ERROR_FALLBACK,
  MULTILINE_TEXT,
  GREEK_INLINE,
  LONG_STEM,
  DISPLAY_ONLY,
  EMPTY_SEGMENTS
}
