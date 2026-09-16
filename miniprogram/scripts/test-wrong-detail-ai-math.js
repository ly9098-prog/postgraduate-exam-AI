const assert = require('assert')
const fs = require('fs')
const path = require('path')

const {
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

function formulaBodies(html) {
  const text = String(html || '')
  const results = []
  const re = /(\$\$|\$)([\s\S]*?)\1/g
  let match
  while ((match = re.exec(text))) results.push(match[2])
  return results
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

const studyNodes = parseAiHtmlThroughLatex(StudyLatex, card.html)
assertNativeRichTextTree(studyNodes)
assert.ok(Array.isArray(studyNodes) && studyNodes.length > 0, 'study latex plugin must emit rich-text nodes')
assert.ok(countKatexNodes(studyNodes) > 0, 'study latex plugin must render a katex tree')

const examNodes = parseAiHtmlThroughLatex(ExamLatex, card.html)
assertNativeRichTextTree(examNodes)
assert.ok(countKatexNodes(examNodes) > 0, 'exam latex plugin must render a katex tree')

const studyLatexSrc = fs.readFileSync(path.join(__dirname, '../subpackages/study/components/mp-html/latex/index.js'), 'utf8')
const examLatexSrc = fs.readFileSync(path.join(__dirname, '../subpackages/exam/components/mp-html/latex/index.js'), 'utf8')
assert(!studyLatexSrc.includes('__renderToDomTree'), 'study latex plugin must not pass KaTeX DOM trees to rich-text')
assert(!examLatexSrc.includes('__renderToDomTree'), 'exam latex plugin must not pass KaTeX DOM trees to rich-text')

console.log('✓ wrong-detail AI KaTeX regression tests passed')
