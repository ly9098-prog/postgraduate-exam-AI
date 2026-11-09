const assert = require('assert')
const fs = require('fs')
const path = require('path')

const {
  normalizeAiMathDelimiters,
  repairAiLatexControlEscapes,
  buildAiRichText,
} = require('../subpackages/study/utils/ai-math-render')
const katex = require('../subpackages/study/components/mp-html/latex/katex.min')

// mp-html parser reads platform information at require time.
global.wx = global.wx || {
  getWindowInfo() { return { windowWidth: 375, pixelRatio: 2 } },
  getDeviceInfo() { return { system: 'Node.js regression test' } },
  canIUse() { return true },
  setNavigationBarTitle() {},
}
const StudyLatex = require('../subpackages/study/components/mp-html/latex/index')
const ExamLatex = require('../subpackages/exam/components/mp-html/latex/index')

// Mirror the runtime tokenizer in mp-html/latex/index.js: it splits text on
// /\${1,2}/ and pairs delimiters; mismatched delimiters degrade to literal
// text. Test helpers MUST use this grammar, otherwise '$$'-adjacency
// corruption is invisible to CI.
function tokenizeMath(html) {
  const parts = String(html || '').split(/(\${1,2})/)
  const math = []
  const prose = []
  let status = 0
  for (let i = 0; i < parts.length; i++) {
    if (i % 2 === 0) {
      if (!parts[i]) continue
      if (status === 0) prose.push(parts[i])
      else math.push(parts[i])
    } else {
      const next = parts[i + 2]
      if (parts[i] === '$' && next === '$') {
        status = 1
        parts[i + 2] = ''
      } else if (parts[i] === '$$' && next === '$$') {
        status = 2
        parts[i + 2] = ''
      } else {
        if (parts[i] && parts[i] !== '$$') {
          parts[i + 1] = parts[i] + (parts[i + 1] || '')
        }
        status = 0
      }
    }
  }
  return { math, prose: prose.join('') }
}

function formulaBodies(html) {
  return tokenizeMath(html).math
}

function assertKatexParses(html, message) {
  const formulas = formulaBodies(html)
  assert(formulas.length > 0, message + ': expected at least one math span')
  formulas.forEach((formula) => {
    assert.doesNotThrow(() => katex.renderToString(formula), message + ': KaTeX should parse ' + formula)
  })
}

// Regression from the device screenshot. `\\neq` and `\\text` were decoded as
// newline/tab and the page rendered: "$X.lchild eq ext{NULL}".
const corrupted = '掌握中序前驱判定：若 $X.lchild' + '\n' + 'eq' + '\t' + 'ext{NULL}$，前驱为左子树最右结点。'
const repaired = repairAiLatexControlEscapes(corrupted)
assert.strictEqual(
  repaired,
  '掌握中序前驱判定：若 $X.lchild\\neq\\text{NULL}$，前驱为左子树最右结点。'
)

const card = buildAiRichText(corrupted)
assert.strictEqual(card.needsRich, true, 'AI math must use mp-html/KaTeX')
assert(card.html.includes('$X.lchild\\neq\\text{NULL}$'), 'repaired LaTeX must reach mp-html intact')
assert(!card.html.includes('$X.lchild<br>eq'), 'corrupted newline must not split the formula')
assert(!card.html.includes('&nbsp;&nbsp;&nbsp;&nbsp;ext{NULL}'), 'corrupted tab must not leak into HTML')
assertKatexParses(card.html, 'screenshot regression')

// Full screenshot-shaped regression: \text, \frac and \binom can each be
// decoded by JSON.parse as tab/form-feed/backspace when an AI response embeds
// LaTeX in a JSON string without double escaping the backslash.
const screenshotKnowledge =
  '①非递归化可 $' + '\t' + 'ext{用循环或队列替代栈}$，非必须；' +
  '②入栈序列对应出栈序列数为 $C_n=' + '\f' + 'rac{1}{n+1}' + '\b' + 'inom{2n}{n}$；' +
  '③栈是仅允许在栈顶操作的受限线性表。'
const screenshotCard = buildAiRichText(screenshotKnowledge)
assert.strictEqual(screenshotCard.needsRich, true)
assert(screenshotCard.html.includes('$\\text{用循环或队列替代栈}$'), 'screenshot \\text must be restored')
assert(screenshotCard.html.includes('$C_n=\\frac{1}{n+1}\\binom{2n}{n}$'), 'Catalan formula must be restored')
assertKatexParses(screenshotCard.html, 'full screenshot regression')

// mp-html only recognizes $ delimiters. Normalize the other LaTeX delimiters
// frequently returned by models so formulas do not leak as raw \(...\)/\[...\].
assert.strictEqual(
  normalizeAiMathDelimiters('行内 \\(x^2+1\\)，块级 \\[\\frac{1}{2}\\]'),
  '行内 $x^2+1$，块级 $$\\frac{1}{2}$$'
)
const alternateDelimiterCard = buildAiRichText('结论：\\(a_n=n^2\\)，且 \\[\\frac{1}{n}\\]')
assert.strictEqual(alternateDelimiterCard.needsRich, true, 'alternate LaTeX delimiters must use mp-html/KaTeX')
assert(!/[\\][(\[]/.test(alternateDelimiterCard.html), 'alternate delimiters must not leak to rendered HTML')
assertKatexParses(alternateDelimiterCard.html, 'alternate delimiter regression')

// Wrong-detail AI review screenshot regression: the model delimited some
// formulas ($2^{32}B$) but left bare scripts (2^{32}) in prose. Bare script
// runs outside $...$ spans must be wrapped for KaTeX instead of leaking
// literal ^{...} next to rendered math.
function outsideMathText(html) {
  return tokenizeMath(html).prose
}
const mixedScriptCard = buildAiRichText(
  '作答核对：你选择 C（1MB+2^{32}MB），正确答案为 D。32位地址最多可寻址 $2^{32}B$，与主存、外存容量无关。'
)
assert.strictEqual(mixedScriptCard.needsRich, true, 'mixed delimited/bare passage must use mp-html/KaTeX')
assert(mixedScriptCard.html.includes('1MB+$2^{32}$MB'), 'bare 2^{32} must be wrapped: ' + mixedScriptCard.html)
assert(mixedScriptCard.html.includes('$2^{32}B$'), 'pre-delimited formula must stay untouched')
assert(!/[\^_]\{/.test(outsideMathText(mixedScriptCard.html)), 'no bare script may remain outside math spans')
assertKatexParses(mixedScriptCard.html, 'mixed bare/delimited script regression')

// Multi-digit unbraced scripts must be consumed whole and braced, otherwise
// 2^32 renders as 2^3 followed by a stray 2 (a wrong numeric value).
const multiDigitCard = buildAiRichText('地址空间为 2^32 字节，$x^2$ 为对照')
assert(multiDigitCard.html.includes('$2^{32}$'), 'multi-digit bare exponent must be braced: ' + multiDigitCard.html)
assert(!/[\^_]/.test(outsideMathText(multiDigitCard.html)), 'no bare script may remain outside math spans')
assertKatexParses(multiDigitCard.html, 'multi-digit bare exponent regression')

// A bare run directly touching a delimited span must not insert a delimiter
// that forms '$$': the runtime tokenizer would then destroy both formulas.
const adjacencyCard = buildAiRichText('公式 $x^2$2^{10} 与相邻的 x^2y^3 对照')
assert(adjacencyCard.html.includes('$x^2$'), 'pre-existing formula must still render')
assert(!adjacencyCard.html.includes('$$'), 'inserted delimiters must never form $$: ' + adjacencyCard.html)
assert(tokenizeMath(adjacencyCard.html).math.includes('x^2'), 'adjacent formula must stay a math span')

// An unpaired '$' (currency) must not be re-paired with an inserted delimiter.
const orphanDollarCard = buildAiRichText('面积 $S=\\pi r^2$，价格 $5，上限 2^{32}B')
assert(!orphanDollarCard.html.includes('$$'), 'orphan $ must not pair with inserted delimiters: ' + orphanDollarCard.html)
assert(orphanDollarCard.html.includes('2^{32}'), 'prose next to an orphan $ must stay untouched')

// Wrapping must not swallow identifiers or LaTeX commands into script bases.
const identifierCard = buildAiRichText('寄存器 x10、x_axis 与 flag_used 保持原样，\\log_{2} n 增长，内存 10^{6} 次，$x^2$ 对照')
assert(!identifierCard.html.includes('x$10'), 'letter+digit compound token must not become a script base')
assert(!identifierCard.html.includes('used$'), 'snake_case identifier must not become a script base')
assert(!identifierCard.html.includes('$x_a$'), 'single-letter snake_case prefix must not become a script base')
assert(identifierCard.html.includes('x_axis'), 'x_axis identifier must stay untouched')
assert(identifierCard.html.includes('\\log_{2}'), 'LaTeX command subscript must stay one token')
assert(identifierCard.html.includes('$10^{6}$'), 'multi-digit base wraps as a whole: ' + identifierCard.html)
assertKatexParses(identifierCard.html, 'identifier guard regression')

// Nested-brace bodies must not be half-wrapped into x^{$a_{1}$}.
const nestedBraceCard = buildAiRichText('矩阵元素 x^{a_{1}} 与公式 $2^{32}B$ 有关')
assert(nestedBraceCard.html.includes('x^{a_{1}}'), 'nested-brace script must stay untouched: ' + nestedBraceCard.html)
assertKatexParses(nestedBraceCard.html, 'nested-brace regression')

// HTML-formatted AI answers must get the same bare-script wrapping in their
// text nodes, without touching tags or attributes.
const htmlSourceCard = buildAiRichText('<p>地址宽度 2^{32}MB，公式 $2^{32}B$ 对照</p>')
assert(htmlSourceCard.html.includes('$2^{32}$MB'), 'HTML text nodes must be wrapped: ' + htmlSourceCard.html)
assert(htmlSourceCard.html.includes('<p>') && htmlSourceCard.html.includes('</p>'), 'HTML tags must stay intact')

// Prose-only bare text without any $ delimiter keeps the lightweight path.
const bareOnlyCard = buildAiRichText('增长到 2^{32} 数量级')
assert.strictEqual(bareOnlyCard.needsRich, false, 'bare-only prose keeps the lightweight <text> path')

// Other JSON control escapes that can damage common LaTeX commands.
const structural = '$' + '\f' + 'rac{a}{b}=' + '\b' + 'eta,' + '\r' + 'ight)$'
const structuralCard = buildAiRichText(structural)
assert(structuralCard.html.includes('$\\frac{a}{b}=\\beta,\\right)$'))
assert(formulaBodies(structuralCard.html).includes('\\frac{a}{b}=\\beta,\\right)'), 'control-escape recovery must preserve repaired math source')
assertKatexParses('$\\frac{a}{b}=\\beta$', 'control-escape recovery')

// A real prose newline outside math must remain a prose newline.
const multiline = '第一行\n第二行：$x' + '\n' + 'eq0$'
const multilineRepaired = repairAiLatexControlEscapes(multiline)
assert(multilineRepaired.startsWith('第一行\n第二行：'), 'prose newline must be preserved')
assert(multilineRepaired.endsWith('$x\\neq0$'), 'math newline escape must be repaired')

// Normal prose without math should keep the lightweight <text> path.
const prose = buildAiRichText('先回顾中序遍历，再手动画一棵二叉树。')
assert.strictEqual(prose.needsRich, false)
assert.strictEqual(prose.html, '')

// Integration guard: wrong-detail must use the dedicated AI renderer.
const wrongDetailJs = fs.readFileSync(path.join(__dirname, '../subpackages/study/wrong-detail/wrong-detail.js'), 'utf8')
assert(wrongDetailJs.includes("require('../utils/ai-math-render')"), 'wrong-detail must import ai-math-render')
assert(wrongDetailJs.includes('return buildAiRichText(value)'), 'wrong-detail must delegate AI rich text rendering')

function assertNativeRichTextTree(value, at) {
  at = at || 'root'
  if (Array.isArray(value)) {
    value.forEach((item, index) => assertNativeRichTextTree(item, at + '[' + index + ']'))
    return
  }
  if (!value || typeof value !== 'object') return
  assert.ok(!Object.prototype.hasOwnProperty.call(value, 'attributes'), at + ' leaked KaTeX private attributes')
  assert.ok(!Object.prototype.hasOwnProperty.call(value, 'classes'), at + ' leaked KaTeX private classes')
  if (value.name && value.attrs !== undefined) {
    assert.strictEqual(typeof value.attrs, 'object', at + '.attrs must be an object')
    assert.ok(!Array.isArray(value.attrs), at + '.attrs must not be an array')
  }
  if (value.children) assertNativeRichTextTree(value.children, at + '.children')
}

function parseAiHtmlThroughLatex(LatexPlugin, html) {
  const Parser = require('../subpackages/study/components/mp-html/parser')
  const host = {
    properties: { editable: false, containerStyle: '', mathLayout: '' },
    imgList: [],
    plugins: [new LatexPlugin()],
  }
  return new Parser(host).parse(String(html || ''))
}

function countKatexNodes(value) {
  var count = 0
  function walk(item) {
    if (Array.isArray(item)) {
      item.forEach(walk)
      return
    }
    if (!item || typeof item !== 'object') return
    var className = item.attrs ? String(item.attrs.class || '') : ''
    if (className.split(/\s+/).indexOf('katex') >= 0) count += 1
    if (item.children) walk(item.children)
  }
  walk(value)
  return count
}

function classTokens(node) {
  return String(node && node.attrs && node.attrs.class || '').split(/\s+/).filter(Boolean)
}

function assertKatexLayoutCompatibility(value) {
  var spanCount = 0
  var vlistCount = 0
  var fractionCount = 0
  function walk(item) {
    if (Array.isArray(item)) {
      item.forEach(walk)
      return
    }
    if (!item || typeof item !== 'object') return
    const classes = classTokens(item)
    if (item.name === 'span' && classes.some((name) => name === 'katex' || name === 'katex-html' || name === 'base' || name === 'vlist' || name === 'mfrac' || name === 'msupsub' || name === 'pstrut' || name === 'frac-line')) {
      spanCount += 1
      assert(classes.includes('katex-span'), 'every KaTeX span must carry katex-span so katex.wxss selectors apply')
    }
    if (classes.includes('vlist')) {
      vlistCount += 1
      ;(item.children || []).forEach((child) => {
        if (child && child.name === 'span') {
          assert(classTokens(child).includes('katex-span'), 'vlist direct children need katex-span for zero-height relative positioning')
        }
      })
    }
    if (classes.includes('mfrac')) fractionCount += 1
    if (item.children) walk(item.children)
  }
  walk(value)
  assert(spanCount > 0, 'expected converted KaTeX spans')
  assert(vlistCount > 0, 'screenshot formula should exercise vlist positioning')
  assert(fractionCount > 0, 'screenshot formula should exercise fraction layout')
}

const studyNodes = parseAiHtmlThroughLatex(StudyLatex, card.html)
assertNativeRichTextTree(studyNodes)
assert.ok(Array.isArray(studyNodes) && studyNodes.length > 0, 'study latex plugin must emit rich-text nodes')
assert.ok(countKatexNodes(studyNodes) > 0, 'study latex plugin must render a katex tree')

// Reproduce the exact Catalan-number formula from the screenshot through the
// full AI renderer + mp-html latex plugin path. The previous implementation
// converted KaTeX HTML with the generic parser, which dropped the synthetic
// `katex-span` class required by katex.wxss. As a result vlist rules did not
// apply and C_n / fractions were vertically scrambled on device.
const screenshotNodes = parseAiHtmlThroughLatex(StudyLatex, screenshotCard.html)
assertNativeRichTextTree(screenshotNodes)
assertKatexLayoutCompatibility(screenshotNodes)

const directCatalanNodes = StudyLatex.parseKatexToNodes('C_n=\\frac{1}{n+1}\\binom{2n}{n}', {
  displayMode: false,
  throwOnError: true,
})
assertNativeRichTextTree(directCatalanNodes)
assertKatexLayoutCompatibility(directCatalanNodes)

// Stretchy/SVG primitives must be converted to native rich-text-compatible
// images instead of leaking KaTeX private DOM nodes.
const sqrtNodes = StudyLatex.parseKatexToNodes('\\sqrt{x^2+1}', { displayMode: false, throwOnError: true })
assertNativeRichTextTree(sqrtNodes)
assert(JSON.stringify(sqrtNodes).includes('katex-svg'), 'SVG-based KaTeX glyphs must remain renderable')

const examNodes = parseAiHtmlThroughLatex(ExamLatex, card.html)
assertNativeRichTextTree(examNodes)
assert.ok(countKatexNodes(examNodes) > 0, 'exam latex plugin must render a katex tree')

const studyLatexSrc = fs.readFileSync(path.join(__dirname, '../subpackages/study/components/mp-html/latex/index.js'), 'utf8')
assert(studyLatexSrc.includes('katex-span'), 'study latex adapter must preserve katex-mini compatibility classes')
assert(studyLatexSrc.includes('vertical-align:middle;line-height:normal'), 'inline formula wrapper must isolate KaTeX from prose line-height')

console.log('✓ wrong-detail AI KaTeX regression tests passed')
