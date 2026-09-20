/* eslint-disable no-console */
const assert = require('assert')

const formulaContent = require('../subpackages/formulas/utils/formula-content')

global.wx = global.wx || {
  getWindowInfo() { return { windowWidth: 375 } },
  getDeviceInfo() { return { system: 'Node.js regression test' } },
}

const Parser = require('../subpackages/study/components/mp-html/parser')
const LatexPlugin = require('../subpackages/formulas/utils/katex/index')

const conditions = '两个重要极限适用的前提是极限过程分别符合x → 0和x → ∞（或x → 0时(1 + x)^(1/x)）。'
const errorTips = '易错：lim(x → 0)(sin x)/x = 1，不是0；lim(x → 0)(sin 2x)/x = 2，不是1。第二个重要极限底数是(1 + 1/x)，不是(1 + x)。'
const blockLabel = 'e^x展开'
const greekExponentBlockLabel = '(1+x)^α展开'
const piecewiseTitle = '分段函数典型图像：sgn x 与 \\lfloor x\\rfloor'
const floorErrorTips = JSON.stringify([
  '\\operatorname{sgn}x 在 x = 0 处函数值为 0，但左右极限分别为 -1 和 1。',
  '\\lfloor x\\rfloor 在每个整数处发生跳跃，左极限为 k-1，函数值与右极限为 k。',
  '正式公式使用 \\lfloor x\\rfloor，不使用容易与区间混淆的 [x]。',
])
const structuredConditions = '[{"expression":"a ≠ 0","note":""}]'
const structuredSymbols = '[{"symbol":"Delta = b^2 - 4ac","note":"判别式，决定与 x 轴交点个数"}]'
const structuredConclusions = '["二次函数的二阶导数为非零常数 2a","顶点公式：(-b/(2a), (4ac-b^2)/(4a))"]'
const structuredErrors = '["a = 0 时退化为一次函数，不是二次函数","极值点坐标与顶点坐标相同"]'

const expectedConditions = '两个重要极限适用的前提是极限过程分别符合$\\displaystyle x \\to 0$和$\\displaystyle x \\to \\infty$（或$\\displaystyle x \\to 0$时$\\displaystyle (1 + x)^{\\frac{1}{x}}$）。'
const expectedErrorTips = '易错：$\\displaystyle \\lim_{x\\to 0}\\frac{\\sin x}{x}=1$，不是0；$\\displaystyle \\lim_{x\\to 0}\\frac{\\sin 2x}{x}=2$，不是1。第二个重要极限底数是$\\displaystyle (1 + \\frac{1}{x})$，不是$\\displaystyle (1 + x)$。'
const expectedBlockLabel = '$\\displaystyle e^x$展开'
const expectedGreekExponentBlockLabel = '$\\displaystyle (1+x)^\\alpha{}$展开'
const expectedPiecewiseTitle = '分段函数典型图像：$\\displaystyle \\operatorname{sgn} x$ 与 $\\displaystyle \\lfloor x\\rfloor$'

function parse(html) {
  const host = {
    properties: { editable: false, containerStyle: '', mathLayout: '' },
    imgList: [],
    plugins: [new LatexPlugin()],
  }
  return new Parser(host).parse(html)
}

function collectClasses(nodes, result) {
  result = result || []
  ;(nodes || []).forEach((node) => {
    if (node && node.attrs && node.attrs.class) result.push(String(node.attrs.class))
    if (node && node.classes) result.push(node.classes.join(' '))
    if (node && node.children) collectClasses(node.children, result)
  })
  return result
}

function collectText(nodes, result) {
  result = result || []
  ;(nodes || []).forEach(function (node) {
    if (node && node.type === 'text') {
      result.push(String(node.text))
    } else if (node && node.latexSource) {
      // KaTeX DOM trees retain raw LaTeX only as defensive metadata.
      collectText(node.children, result)
    } else if (node && node.children) {
      collectText(node.children, result)
    }
  })
  return result
}

// =============================
// Existing regression tests
// =============================

const conditionsHtml = formulaContent.normalizeMixedContent(conditions)
const errorTipsHtml = formulaContent.normalizeMixedContent(errorTips)
const blockLabelHtml = formulaContent.normalizeMixedContent(blockLabel)
const greekExponentBlockLabelHtml = formulaContent.normalizeMixedContent(greekExponentBlockLabel)
const piecewiseTitleHtml = formulaContent.normalizeMixedContent(piecewiseTitle)
const floorErrorTipsHtml = formulaContent.normalizeStructuredContent(floorErrorTips, 'errors')

assert.strictEqual(conditionsHtml, expectedConditions)
assert.strictEqual(errorTipsHtml, expectedErrorTips)
assert.strictEqual(blockLabelHtml, expectedBlockLabel)
assert.strictEqual(greekExponentBlockLabelHtml, expectedGreekExponentBlockLabel)
assert.strictEqual(piecewiseTitleHtml, expectedPiecewiseTitle)
assert.strictEqual(formulaContent.normalizeMixedContent(conditionsHtml), conditionsHtml)
assert.strictEqual(formulaContent.normalizeMixedContent(errorTipsHtml), errorTipsHtml)
assert.strictEqual(
  formulaContent.normalizeMixedContent(piecewiseTitleHtml).replace(/\s{2,}/g, ' '),
  piecewiseTitleHtml,
)

assert.strictEqual(formulaContent.normalizeMathRun('sin x/x'), '\\frac{\\sin x}{x}')
assert.strictEqual(formulaContent.normalizeMathRun('sin 2x/x'), '\\frac{\\sin 2x}{x}')
assert.strictEqual(formulaContent.normalizeMathRun('x/sin x'), '\\frac{x}{\\sin x}')
assert.strictEqual(formulaContent.normalizeMathRun('(1+x)^(1/x)'), '(1+x)^{\\frac{1}{x}}')
assert.strictEqual(formulaContent.normalizeMathRun('(1+x)^{1/x}'), '(1+x)^{\\frac{1}{x}}')
assert.strictEqual(formulaContent.normalizeMathRun('sgn x'), '\\operatorname{sgn} x')
assert.strictEqual(formulaContent.normalizeMixedContent('2026/07/13'), '2026/07/13')
assert.strictEqual(formulaContent.normalizeMixedContent('v1.2.3'), 'v1.2.3')
assert.strictEqual(formulaContent.normalizeMixedContent('https://example.com/a/b'), 'https://example.com/a/b')
assert.strictEqual(formulaContent.normalizeMixedContent('/api/v1/formulas'), '/api/v1/formulas')
assert.strictEqual(formulaContent.normalizeMixedContent('不是0，不是1，共2种情况'), '不是0，不是1，共2种情况')

const structuredConditionsHtml = formulaContent.normalizeStructuredContent(structuredConditions, 'conditions')
const structuredSymbolsHtml = formulaContent.normalizeStructuredContent(structuredSymbols, 'symbols')
const structuredConclusionsHtml = formulaContent.normalizeStructuredContent(structuredConclusions, 'secondary')
const structuredErrorsHtml = formulaContent.normalizeStructuredContent(structuredErrors, 'errors')

assert(!structuredConditionsHtml.includes('[{'), 'conditions JSON must not be rendered as raw source')
assert(!structuredSymbolsHtml.includes('"symbol"'), 'symbol_notes JSON must not be rendered as raw source')
assert(!structuredConclusionsHtml.includes('["'), 'secondary conclusions JSON must not be rendered as raw source')
assert(!structuredErrorsHtml.includes('["'), 'error tips JSON must not be rendered as raw source')
assert(structuredConditionsHtml.includes('fc-structured-list is-plain'))
assert(structuredSymbolsHtml.includes('判别式'))
assert(structuredConclusionsHtml.includes('fc-structured-list is-bulleted'))
assert(structuredErrorsHtml.includes('fc-structured-list is-bulleted'))

const structuredConditionsNodes = parse(structuredConditionsHtml)
const structuredSymbolsNodes = parse(structuredSymbolsHtml)
const structuredConclusionsNodes = parse(structuredConclusionsHtml)
assert(collectClasses(structuredConditionsNodes).some((name) => /katex/.test(name)), 'condition expressions must render through KaTeX')
assert(collectClasses(structuredSymbolsNodes).some((name) => /katex/.test(name)), 'symbol expressions must render through KaTeX')
assert(collectClasses(structuredConclusionsNodes).some((name) => /mfrac/.test(name)), 'structured conclusions must preserve fraction rendering')

const preparedStructured = formulaContent.prepareContentHtml({
  conditions: structuredConditions,
  symbol_notes: structuredSymbols,
  secondary_conclusions: structuredConclusions,
  error_tips: structuredErrors,
})
assert.strictEqual(preparedStructured.conditionsHtml, structuredConditionsHtml)
assert.strictEqual(preparedStructured.symbolNotesHtml, structuredSymbolsHtml)
assert.strictEqual(preparedStructured.secondaryHtml, structuredConclusionsHtml)
assert.strictEqual(preparedStructured.errorTipsHtml, structuredErrorsHtml)

const conditionClasses = collectClasses(parse(conditionsHtml))
const errorClasses = collectClasses(parse(errorTipsHtml))
const blockLabelClasses = collectClasses(parse(blockLabelHtml))
const greekExponentBlockLabelNodes = parse(greekExponentBlockLabelHtml)
const greekExponentBlockLabelClasses = collectClasses(greekExponentBlockLabelNodes)
const piecewiseTitleNodes = parse(piecewiseTitleHtml)
const floorErrorTipNodes = parse(floorErrorTipsHtml)
const piecewiseTitleClasses = collectClasses(piecewiseTitleNodes)
const floorErrorTipClasses = collectClasses(floorErrorTipNodes)
assert(conditionClasses.some((name) => /mfrac/.test(name)), 'condition exponent must contain a real KaTeX fraction')
assert(errorClasses.filter((name) => /mfrac/.test(name)).length >= 3, 'error tips must contain real KaTeX fractions')
assert(errorClasses.filter((name) => /op-limits/.test(name)).length >= 2, 'error tips must contain limit operators with lower limits')
assert(blockLabelClasses.some((name) => /katex/.test(name)), 'formula block label must be parsed into a KaTeX tree')
assert(greekExponentBlockLabelClasses.some((name) => /katex/.test(name)), 'Greek exponent label must be parsed into a KaTeX tree')
assert(!JSON.stringify(greekExponentBlockLabelNodes).includes('color:red'), 'Greek exponent label must not contain a KaTeX parse error')
assert(piecewiseTitleClasses.filter((name) => /(?:^|\s)katex(?:\s|$)/.test(name)).length >= 2, 'piecewise title must render both sgn and floor notation through KaTeX')
assert(floorErrorTipClasses.filter((name) => /(?:^|\s)katex(?:\s|$)/.test(name)).length >= 3, 'error tips must render operatorname and floor notation through KaTeX')
assert(!JSON.stringify(piecewiseTitleNodes).includes('color:red'), 'piecewise title must not contain a KaTeX parse error')
assert(!JSON.stringify(floorErrorTipNodes).includes('color:red'), 'floor error tips must not contain a KaTeX parse error')
assert(!piecewiseTitleHtml.includes(' 与 \\lfloor'), 'floor source must not remain outside math delimiters in the title')
assert(!JSON.stringify(floorErrorTipNodes).includes('\\\\lfloor'), 'floor source must not remain as visible rich-text content')

const fs = require('fs')
const path = require('path')
const cardJs = fs.readFileSync(path.join(__dirname, '../subpackages/formulas/components/formula-card/index.js'), 'utf8')
const cardWxml = fs.readFileSync(path.join(__dirname, '../subpackages/formulas/components/formula-card/index.wxml'), 'utf8')
const cardWxss = fs.readFileSync(path.join(__dirname, '../subpackages/formulas/components/formula-card/index.wxss'), 'utf8')
assert(/labelNodes:\s*parseRichNodes\(formulaContent\.normalizeMixedContent\(block\.label\)\)/.test(cardJs), 'block.label must be converted into rich LaTeX nodes')
assert(/nodes="\{\{block\.labelNodes\}\}"/.test(cardWxml), 'upper-left formula block label must render labelNodes')
assert(!/<text class="fc-block-label"[^>]*>\{\{block\.label\}\}<\/text>/.test(cardWxml), 'raw block.label text rendering must be removed')
assert(/class="fc-graph-viewport"/.test(cardWxml), 'graph image must be wrapped in a crop viewport')
assert(/\.fc-graph-image\s*\{[\s\S]*?height:\s*100%/.test(cardWxss), 'graph image must fill the fixed-ratio viewport')
assert(!/transform:\s*scale\(/.test(cardWxss), 'graph image must not be scaled up (causes zoomed-in rendering)')
assert(/padding-bottom:\{\{graphViewportRatio\}\}%/.test(cardWxml), 'graph viewport height must be pinned by the image aspect ratio')

console.log('✓ Existing regression tests passed')

// =============================
// New Issue 1: block.note rendering with mixed prose/LaTeX
// =============================

var noteText = 'y=x^n（n为正整数）与 y=x^{-n}（n为正整数）对比。前者定义域为 R，过 (0,0) 和 (1,1)；后者 x≠0，过 (1,1)，以坐标轴为渐近线。'
var noteHtml = formulaContent.normalizeMixedContent(noteText)

// The note text contains math fragments that should be wrapped in $...$
assert(noteHtml.indexOf('$') >= 0, 'block.note must contain $ LaTeX delimiters after normalizeMixedContent')
assert(noteHtml.indexOf('x^n') >= 0, 'x^n must appear in the normalized note HTML')
assert(noteHtml.indexOf('x^{-n}') >= 0, 'x^{-n} must appear in the normalized note HTML')
assert(noteHtml.indexOf('x\\ne 0') >= 0, 'x≠0 must be converted to x\\ne 0 in the normalized note HTML')
// Ensure no raw LaTeX source is exposed without delimiters
assert(noteHtml.indexOf('\\displaystyle') < 0 || /\\displaystyle[^$]*\$/.test(noteHtml), '\\displaystyle should only appear inside $...$ delimiters')

var noteNodes = parse(noteHtml)
var noteClasses = collectClasses(noteNodes)
assert(noteClasses.some(function (name) { return /katex/.test(name) }), 'block.note must contain KaTeX-rendered nodes for math expressions')
assert(noteClasses.filter(function (name) { return /mord/.test(name) || /mbin/.test(name) || /msup/.test(name) || /mfrac/.test(name) }).length >= 3, 'block.note must contain real math operator/superscript nodes')
// x^n should produce a superscript (msup or similar KaTeX class)
assert(noteClasses.some(function (name) { return /msup/.test(name) || /^m.*sup/.test(name) }), 'block.note must render x^n with a superscript')

var noteTextJson = JSON.stringify(noteNodes)
assert(noteTextJson.indexOf('color:red') < 0, 'block.note must not contain KaTeX error nodes')
// x^{-n} must not appear as raw source text (it must be inside KaTeX)
assert(noteTextJson.indexOf('x^{-n}') < 0 || /katex/.test(noteTextJson), 'x^{-n} should not appear as raw unrendered source')

console.log('✓ Issue 1 (block.note) tests passed')

// =============================
// New Issue 2: KaTeX parse error in conditions
// =============================

// Incomplete \text{ should not produce visible error
var dirtyLatex = '\\text{且换元过程满足公式条件"'
// sanitizeLatexContent should handle incomplete \text{
var sanitized = formulaContent.sanitizeLatexContent(dirtyLatex)
assert(sanitized.indexOf('}') >= 0, 'sanitizeLatexContent must close incomplete \\text{')

// NormalizeMathRun should not throw on dirty data
var dirtyResult = formulaContent.normalizeMathRun(dirtyLatex)
assert(typeof dirtyResult === 'string', 'normalizeMathRun must return string for dirty data')

// Dirty data passed through the full structured content pipeline must not produce errors
var dirtyConditionJson = JSON.stringify([{ expression: dirtyLatex, note: '常见充分条件' }])
var dirtyConditionHtml = formulaContent.normalizeStructuredContent(dirtyConditionJson, 'conditions')
assert(!dirtyConditionHtml.includes('parse error'), 'dirty condition HTML must not contain KaTeX parse error text')
assert(!dirtyConditionHtml.includes('color:red'), 'dirty condition HTML must not contain error styling')
// Should still have structured list markup
assert(dirtyConditionHtml.indexOf('fc-structured') >= 0, 'dirty condition must still produce structured content')

var dirtyConditionNodes = parse(dirtyConditionHtml)
assert(!JSON.stringify(dirtyConditionNodes).includes('color:red'), 'dirty condition parsed nodes must not contain KaTeX error styling')

// Normal condition a ≠ 0 must still render correctly
var normalConditionHtml = formulaContent.normalizeStructuredContent(structuredConditions, 'conditions')
var normalNodes = parse(normalConditionHtml)
var normalClasses = collectClasses(normalNodes)
assert(normalClasses.some(function (name) { return /katex/.test(name) }), 'normal condition a ≠ 0 must still render through KaTeX')
assert(!JSON.stringify(normalNodes).includes('color:red'), 'normal condition must not contain KaTeX error')

// Mixed text with →, ≠ must render cleanly
var mixedTest = '换元后 x → 0，且 g(x) ≠ 0'
var mixedHtml = formulaContent.normalizeMixedContent(mixedTest)
assert(mixedHtml.indexOf('$') >= 0, 'mixed text with arrow must produce $ delimiters')
assert(mixedHtml.indexOf('\\to ') >= 0 || mixedHtml.indexOf('\\rightarrow') >= 0, '→ must be converted to LaTeX arrow')

// JSON conditions with expression+note must not show raw JSON
var jsonCondition = JSON.stringify([{ expression: 'a ≠ 0', note: '常见充分条件' }])
var jsonConditionHtml = formulaContent.normalizeStructuredContent(jsonCondition, 'conditions')
assert(jsonConditionHtml.indexOf('fc-structured') >= 0, 'JSON conditions must produce structured HTML')
assert(jsonConditionHtml.indexOf('[{\\"') < 0, 'JSON conditions must not show raw JSON source')
assert(jsonConditionHtml.indexOf('expression') < 0, 'JSON conditions must not show field names')

// SanitizeLatexContent edge cases
assert.strictEqual(formulaContent.sanitizeLatexContent('\\frac{1}{2}'), '\\frac{1}{2}', 'valid LaTeX must not be modified by sanitize')
assert.strictEqual(formulaContent.sanitizeLatexContent(''), '', 'empty string sanitize must return empty')

// Nested unclosed braces: \textbf{粗体\textit{斜体 (2 opens, 0 closes)
var nestedDirty = formulaContent.sanitizeLatexContent('\\textbf{粗体\\textit{斜体')
assert(nestedDirty.indexOf('}}') >= 0, 'sanitize must close nested unclosed braces with multiple }}')
// After closing, the LaTeX becomes valid: \textbf{粗体\textit{斜体}}
var nestedClean = formulaContent.normalizeMathRun('\\textbf{粗体\\textit{斜体}}')
assert(typeof nestedClean === 'string', 'normalizeMathRun must handle repaired nested braces')

console.log('✓ Issue 2 (KaTeX error handling) tests passed')

// Complete structured LaTeX containing Chinese \text{...} must remain one
// formula. It must never be split into `f\text{}` + prose + `}T...\text{`.
var completeStructuredExpressions = [
  {
    expression: 'f\\text{ 在 }[a,b]\\text{ 上Riemann可积}',
    expectedText: ['f', '[a,b]', '在', '上Riemann可积'],
  },
  {
    expression: 'f\\text{ 周期为 }T>0\\text{ 且在局部可积}',
    expectedText: ['f', 'T', '0', '周期为', '且在局部可积'],
  },
  {
    expression: 'u(x)\\ne u_0\\text{ 最终成立，或 }f\\text{ 在 }u_0\\text{ 连续}',
    expectedText: ['u', 'x', 'f', '最终成立，或', '在', '连续'],
  },
]

completeStructuredExpressions.forEach(function (fixture) {
  var html = formulaContent.normalizeStructuredContent(
    JSON.stringify([{ expression: fixture.expression, note: '条件说明' }]),
    'conditions',
  )
  var delimiterCount = (html.match(/\$\\displaystyle/g) || []).length
  assert.strictEqual(delimiterCount, 1, 'complete structured expression must produce exactly one formula wrapper: ' + fixture.expression)
  assert(!/\$\\displaystyle\s*\}/.test(html), 'complete structured expression must not create an orphaned closing brace formula')

  var nodes = parse(html)
  var serialized = JSON.stringify(nodes)
  assert(!serialized.includes('KaTeX parse error'), 'complete structured expression must not expose KaTeX diagnostics')
  assert(!serialized.includes("Expected 'EOF'"), 'complete structured expression must not contain EOF parse errors')
  assert(!serialized.includes('color:red'), 'complete structured expression must not contain red error nodes')
  assert(!serialized.includes('katex-error'), 'complete structured expression must not contain katex-error nodes')
  assert(collectClasses(nodes).some(function (name) { return /katex/.test(name) }), 'complete structured expression must render through KaTeX')

  var text = collectText(nodes).join('')
  fixture.expectedText.forEach(function (fragment) {
    assert(text.indexOf(fragment) >= 0, 'rendered expression must preserve fragment "' + fragment + '"')
  })
  assert(text.indexOf('条件说明') >= 0, 'structured note must remain outside the formula')
})

// Plain mixed prose must keep using the conservative tokenizer.
var conservativeMixedHtml = formulaContent.normalizeMixedContent('换元后 x → 0，且 g(x) ≠ 0')
assert(conservativeMixedHtml.indexOf('换元后') >= 0 && conservativeMixedHtml.indexOf('且') >= 0, 'ordinary Chinese prose must remain outside KaTeX')
assert((conservativeMixedHtml.match(/\$\\displaystyle/g) || []).length >= 2, 'ordinary mixed prose must keep separate math fragments')

console.log('✓ Complete structured LaTeX with Chinese text tests passed')

// =============================
// Surgical per-fragment fallback: one broken formula must not
// degrade an entire paragraph to plain text.
// =============================

var mixedProseWithError = '已知公式 $\\displaystyle \\sin^2 x + \\cos^2 x = 1$，且 $\\text{未闭合的脏数据'
var mixedProseHtml = formulaContent.normalizeMixedContent(mixedProseWithError)
// The good formula source must be present (with brace-wrapped exponent after normalization)
assert(mixedProseHtml.indexOf('\\sin') >= 0, 'good formula source (\\sin) must be present')
assert(mixedProseHtml.indexOf('\\cos') >= 0, 'good formula source (\\cos) must be present')

var mixedProseNodes = parse(mixedProseHtml)
var mixedProseClasses = collectClasses(mixedProseNodes)
// The good formula (sin^2 x + cos^2 x = 1) must still produce KaTeX nodes
var hasGoodKatex = mixedProseClasses.some(function (name) { return /katex/.test(name) })
assert(hasGoodKatex, 'good formula must still render through KaTeX when co-located with broken formula')

// Chinese prose context must still be present in rendered output
var mixedProseStr = JSON.stringify(mixedProseNodes)
assert(mixedProseStr.indexOf('已知公式') >= 0, 'Chinese prose "已知公式" must be preserved')

var mixedProseNodes = parse(mixedProseHtml)
var mixedProseClasses = collectClasses(mixedProseNodes)
// The good formula (sin^2 x) must still produce KaTeX nodes
var hasGoodKatex = mixedProseClasses.some(function (name) { return /katex/.test(name) })
assert(hasGoodKatex, 'good formula must still render through KaTeX when co-located with broken formula')

// The "已知公式" and "，且" Chinese prose must still be present in rendered output
var mixedProseStr = JSON.stringify(mixedProseNodes)
assert(mixedProseStr.indexOf('已知公式') >= 0, 'Chinese prose "已知公式" must be preserved')
// No color:red errors anywhere in the result
assert(mixedProseStr.indexOf('color:red') < 0, 'no KaTeX error styling must appear in surgical fallback')

console.log('✓ Surgical per-fragment fallback tests passed')

// =============================
// New Issue 3: determinant notation normalization
// =============================

// det(A) must become \left|A\right| via normalizeLatexSource
var detSource = formulaContent.normalizeLatexSource('det(A)')
assert(detSource.indexOf('\\left|') >= 0, 'normalizeLatexSource must convert det(A) to \\left|A\\right|')
assert(detSource.indexOf('\\right|') >= 0, 'normalizeLatexSource must close with \\right|')
assert(detSource.indexOf('det') < 0 && detSource.indexOf('\\det') < 0, 'det(A) must not contain bare det or \\det')
assert(detSource.indexOf('\\\\det') < 0, '\\det must not be double-escaped')

// \det(A) must also be converted to \left|A\right|
var detPreEscaped = formulaContent.normalizeLatexSource('\\det(A)')
assert(detPreEscaped.indexOf('\\left|') >= 0, '\\det must be converted to \\left|...\\right|')
assert(detPreEscaped.indexOf('\\\\det') < 0, 'pre-escaped \\det must not be double-escaped')

// Within normalizeLatexSource, compound expressions
var detMathRun = formulaContent.normalizeLatexSource('det(A^T)=det(A)')
assert(detMathRun.indexOf('\\left|') >= 0, 'det must be converted in compound expressions')

// det(AB)=det(A)det(B) with multiple det
var detProduct = formulaContent.normalizeLatexSource('det(AB)=det(A)det(B)')
assert(detProduct.indexOf('\\left|') >= 0, 'det in product expression must be converted')
// Count occurrences of bare det (not preceded by backslash)
var bareDetRe = /(^|[^\\])det(?=[^A-Za-z]|$)/g
var bareDetMatches = detProduct.match(bareDetRe)
assert(bareDetMatches === null, 'all bare det must be converted — none should remain (found ' + (bareDetMatches || []).length + ')')

// Full rendering: det(A) should produce KaTeX vertical bars via \left|...\right|
var detHtml = formulaContent.normalizeMixedContent('det(A)')
assert(detHtml.indexOf('\\left|') >= 0, 'det(A) in mixed content must produce \\left|...\\right|')

var detNodes = parse(detHtml)
var detClasses = collectClasses(detNodes)
// \left|...\right| produces delimiter spans — no "mop" class since it's not an operator
// Instead, verify no KaTeX parse error appears
assert(!JSON.stringify(detNodes).includes('color:red'), 'det(A) rendering must not produce KaTeX error')

// sin, cos, tan, ln etc. must still work
assert(formulaContent.normalizeLatexSource('sin x').indexOf('\\sin') >= 0, 'sin must still be converted')
assert(formulaContent.normalizeLatexSource('cos x').indexOf('\\cos') >= 0, 'cos must still be converted')

// English words containing "det" substring should NOT be affected
assert.strictEqual(formulaContent.normalizeLatexSource('determine'), 'determine', 'words containing det must not be modified')

// =============================
// normalizeDeterminantNotation unit tests
// =============================

var normDet = formulaContent.normalizeDeterminantNotation

// 1. \det(A^T) = \det(A)
assert.strictEqual(
  normDet('\\det(A^T) = \\det(A)'),
  '\\left|A^T\\right| = \\left|A\\right|',
  '\\det(A^T) = \\det(A) must convert'
)

// 2. det(A)=det(A^T) through pipeline (bare det is handled by normalizeFunctionNames first)
assert(
  formulaContent.normalizeLatexSource('det(A)=det(A^T)').indexOf('\\left|') >= 0,
  'det(A)=det(A^T) through pipeline must produce \\left|'
)

// 3. \det A (single letter)
assert.strictEqual(
  normDet('\\det A'),
  '\\left|A\\right|',
  '\\det A must convert'
)

// 4. \det(A^{-1})
assert.strictEqual(
  normDet('\\det(A^{-1})'),
  '\\left|A^{-1}\\right|',
  '\\det(A^{-1}) must convert'
)

// 5. \det(A)\det(B)
assert.strictEqual(
  normDet('\\det(A)\\det(B)'),
  '\\left|A\\right|\\left|B\\right|',
  '\\det(A)\\det(B) multiply must convert'
)

// 6. \frac{1}{\det(A)}
assert.strictEqual(
  normDet('\\frac{1}{\\det(A)}'),
  '\\frac{1}{\\left|A\\right|}',
  '\\frac{1}{\\det(A)} must convert'
)

// 7. (\det A)^{n-1} with outer parens (single letter arg inside)
assert.strictEqual(
  normDet('(\\det A)^{n-1}'),
  '(\\left|A\\right|)^{n-1}',
  '(\\det A)^{n-1} must convert correctly'
)

// 8. Nested parens: \det(P^{-1}AP)
assert.strictEqual(
  normDet('\\det(P^{-1}AP)'),
  '\\left|P^{-1}AP\\right|',
  '\\det(P^{-1}AP) with nested parens must convert'
)

// 9. \det\begin{pmatrix}...\end{pmatrix} → \begin{vmatrix}...\end{vmatrix}
assert.strictEqual(
  normDet('\\det\\begin{pmatrix}a&b\\\\c&d\\end{pmatrix}'),
  '\\begin{vmatrix}a&b\\\\c&d\\end{vmatrix}',
  '\\det\\begin{pmatrix}...\\end{pmatrix} must become vmatrix'
)

// 10. Already vmatrix must not be double-converted
assert.strictEqual(
  normDet('\\begin{vmatrix}A&B\\\\0&C\\end{vmatrix}'),
  '\\begin{vmatrix}A&B\\\\0&C\\end{vmatrix}',
  'existing vmatrix must not be modified'
)

// 11. \text{...} with det inside must not be corrupted
assert.strictEqual(
  normDet('\\text{similar: det, tr, rank}'),
  '\\text{similar: det, tr, rank}',
  '\\text{...} with det must not be converted'
)

// 12. English word "determine" not affected
assert.strictEqual(normDet('determine'), 'determine', 'word determine must not be modified')

// 13. \operatorname{det}(A)
assert.strictEqual(
  normDet('\\operatorname{det}(A)'),
  '\\left|A\\right|',
  '\\operatorname{det}(A) must convert'
)

// 14. \det Q (single letter, no parens)
assert.strictEqual(
  normDet('\\det Q'),
  '\\left|Q\\right|',
  '\\det Q must convert'
)

// 15. \det = \prod (dirty data, no arg)
assert.strictEqual(
  normDet('\\det = \\prod'),
  '\\det = \\prod',
  '\\det without argument must not change'
)

// 16. Multiple calls give same result (idempotent)
var idempotentInput = '\\det(A) = \\det(A^T)'
var once = normDet(idempotentInput)
var twice = normDet(once)
assert.strictEqual(once, twice, 'normalizeDeterminantNotation must be idempotent')

// 17. id=39 real data block 2
assert.strictEqual(
  normDet('\\det(kA) = k^n\\det(A)'),
  '\\left|kA\\right| = k^n\\left|A\\right|',
  'id=39 real block: \\det(kA) = k^n\\det(A)'
)

// 18. id=193 real data: \det\begin{pmatrix}... format
assert.strictEqual(
  normDet('\\det\\begin{pmatrix}a_{11}&b_1\\\\a_{21}&b_2\\end{pmatrix}'),
  '\\begin{vmatrix}a_{11}&b_1\\\\a_{21}&b_2\\end{vmatrix}',
  'id=193: \\det\\begin{pmatrix} with matrix content'
)

// 19. \operatorname{tr} and other operators unaffected
assert.strictEqual(
  normDet('\\operatorname{tr}(A)'),
  '\\operatorname{tr}(A)',
  '\\operatorname{tr} must not be affected'
)

// 20. \sin, \cos, \ln etc. unaffected
assert.strictEqual(
  normDet('\\sin x + \\cos x'),
  '\\sin x + \\cos x',
  'sin and cos must not be affected'
)

console.log('✓ normalizeDeterminantNotation unit tests passed (all ' + 20 + ' cases correct)')

// =============================
// New Issue 4: verify existing content areas still work
// =============================

// Conditions should still parse
assert(conditionClasses.some(function (name) { return /katex/.test(name) }), 'conditions must still contain KaTeX nodes after all changes')
// Symbol notes should still parse
assert(collectClasses(structuredSymbolsNodes).some(function (name) { return /katex/.test(name) }), 'symbol notes must still contain KaTeX nodes')
// Secondary conclusions should still parse
assert(collectClasses(structuredConclusionsNodes).some(function (name) { return /mfrac/.test(name) }), 'conclusions must still contain fractions')

// Summary should not be affected
var summaryHtml = formulaContent.normalizeMixedContent('幂函数 y=x^a（a 为常数）')
assert(summaryHtml.indexOf('$') >= 0, 'summary with math must produce $ delimiters')

// Error tips should not be affected
var errorTipHtml = formulaContent.normalizeMixedContent('注意定义域：x≠0')
assert(errorTipHtml.indexOf('\\ne') >= 0 || errorTipHtml.indexOf('$') >= 0, 'error tips with math must produce conversion')

console.log('✓ Issue 4 (existing content areas) tests passed')


// Screenshot coverage: decimals inside the reader prose areas must stay inside
// the same KaTeX fragment. Previously `e≈2.71828` was split at the decimal point
// and rendered as KaTeX `e≈2` followed by plain `.71828` text.
var symbolDecimalHtml = formulaContent.normalizeMixedContent('e≈2.71828，为自然对数的底数。')
assert(symbolDecimalHtml.indexOf('2.71828') >= 0, 'symbol note decimal must be preserved')
assert((symbolDecimalHtml.match(/\$\\displaystyle/g) || []).length === 1, 'e≈2.71828 must use one inline KaTeX wrapper')
assert(!/\$\.71828/.test(symbolDecimalHtml), 'decimal tail must not leak outside the KaTeX wrapper')

var decimalEquationHtml = formulaContent.normalizeMixedContent('x=1.5，y=2.25。')
assert((decimalEquationHtml.match(/\$\\displaystyle/g) || []).length === 2, 'decimal equations on both sides must render as two complete math fragments')
assert(decimalEquationHtml.indexOf('x=1.5') >= 0 && decimalEquationHtml.indexOf('y=2.25') >= 0, 'decimal equations must remain intact inside reader rich text')

console.log('✓ Reader screenshot decimal LaTeX coverage tests passed')

// =============================
// Formula-table Unicode / legacy notation coverage
// =============================
// Representative values below come from formula_cards.csv and cover the
// notation that previously leaked as plain text or was split into malformed
// KaTeX fragments in summary / conditions / symbols / conclusions / errors.
var tableCoverageCases = [
  ['0/0或∞/∞型不定式', ['\\frac{0}{0}', '\\infty /\\infty']],
  ["且f'(x)/g'(x)的极限存在", ["f'(x)/g'(x)"]],
  ['lim_{x→−∞} arctan x = −π/2', ['\\lim_{x\\to -\\infty', '\\arctan x=-\\pi']],
  ['|sin x| ≤ 1', ['|\\sin x| \\le 1']],
  ['x∈ℝ', ['x\\in \\mathbb{R}']],
  ['f″(x₀)=0', ["f''(x_{0})=0"]],
  ['若∂P/∂y≠∂Q/∂x', ['\\partial P/\\partial y\\ne \\partial Q/\\partial x']],
  ['A为m×n矩阵', ['m\\times n']],
  ['x²-(x₁+x₂)x=0', ['x^{2}-(x_{1}+x_{2})x=0']],
  ['det Q = ±1', ['\\left|Q\\right|=\\pm 1']],
  ['∀α>0', ['\\forall \\alpha{}&gt;0']],
  ['x! 的增长速度更快', ['x!']],
  ['ln x ≺ x^α ≺ a^x', ['\\ln x \\prec x^\\alpha{} \\prec a^x']],
  ['分母为√(A²+B²)', ['\\sqrt{A^{2}+B^{2}}']],
  ['f\'(x)>0 ⇒ f 递增', ["f'(x)&gt;0 \\Rightarrow f"]],
]

tableCoverageCases.forEach(function (fixture) {
  var html = formulaContent.normalizeMixedContent(fixture[0])
  fixture[1].forEach(function (fragment) {
    assert(html.indexOf(fragment) >= 0, 'formula-table notation must be covered by KaTeX: ' + fixture[0] + ' -> ' + fragment)
  })
  var nodes = parse(html)
  var serialized = JSON.stringify(nodes)
  assert(collectClasses(nodes).some(function (name) { return /katex/.test(name) }), 'formula-table notation must create KaTeX nodes: ' + fixture[0])
  assert(serialized.indexOf('color:red') < 0, 'formula-table notation must not create red KaTeX errors: ' + fixture[0])
  assert(serialized.indexOf('KaTeX parse error') < 0, 'formula-table notation must not expose parse errors: ' + fixture[0])
})

assert.strictEqual(
  formulaContent.normalizeLatexSource('y = arccot x'),
  'y = \\operatorname{arccot} x',
  'bare arccot in formula blocks must use operatorname so KaTeX can render it',
)

// Multiplication used as Chinese prose should not be promoted just because the
// glyph × is present; only actual math operands such as m×n are converted.
assert.strictEqual(
  formulaContent.normalizeMixedContent('先把每一项写成 f(采样点)×区间宽度。'),
  '先把每一项写成 f(采样点)×区间宽度。',
  'prose multiplication wording must remain plain text',
)

console.log('✓ Formula-table Unicode / legacy notation coverage tests passed')

// =============================
// Extended formula-table audit regressions
// =============================
// Unicode subscript letters must stay attached to their variable instead of
// splitting one expression into several KaTeX/plain-text fragments.
var unicodeLetterSubscriptHtml = formulaContent.normalizeMixedContent("x²y''=yₜₜ''-yₜ'")
assert(unicodeLetterSubscriptHtml.indexOf("y_{tt}''-y_{t}'") >= 0, 'Unicode subscript letters t must become one LaTeX subscript')
assert.strictEqual((unicodeLetterSubscriptHtml.match(/\$\\displaystyle/g) || []).length, 1, 'Unicode subscript letters must not split the equation')

var betaSubscriptHtml = formulaContent.normalizeMixedContent('(βⱼ,βⱼ)≠0')
assert(betaSubscriptHtml.indexOf('\\beta{}_{j},\\beta{}_{j}') >= 0, 'Unicode subscript j must stay attached to beta')

var xiSubscriptHtml = formulaContent.normalizeMixedContent('ξᵢ 可在各小区间任取')
assert(xiSubscriptHtml.indexOf('\\xi{}_{i}') >= 0, 'Unicode subscript i must stay attached to xi')

// Macron variables are used by the centroid card and must render as x-bar/y-bar.
var centroidHtml = formulaContent.normalizeMixedContent('(x̄,ȳ)为形心坐标')
assert(centroidHtml.indexOf('\\bar{x}') >= 0 && centroidHtml.indexOf('\\bar{y}') >= 0, 'macron variables must become \\bar{} expressions')
assert.strictEqual((centroidHtml.match(/\$\\displaystyle/g) || []).length, 1, 'centroid coordinate pair must render as one formula')

// ASCII ellipsis inside a vector sequence belongs to the same math fragment.
var vectorSequenceHtml = formulaContent.normalizeMixedContent('α₁,α₂,...,α_n线性无关')
assert(vectorSequenceHtml.indexOf('\\ldots') >= 0, 'ASCII ... inside a vector sequence must become a LaTeX ellipsis')
assert.strictEqual((vectorSequenceHtml.match(/\$\\displaystyle/g) || []).length, 1, 'vector sequence must stay in one formula wrapper')

// Raw radicals occur in prose fields. Cover both √(...) and √x, including a
// radical used as the denominator of a fraction.
var radicalHtml = formulaContent.normalizeMixedContent('x+1/x−2=(√x−1/√x)²≥0')
assert(radicalHtml.indexOf('\\sqrt{x}') >= 0, 'raw square-root atom must become \\sqrt{x}')
assert(radicalHtml.indexOf('\\frac{1}{\\sqrt{x}}') >= 0, '1/√x must become a real LaTeX fraction')
assert(!radicalHtml.includes('√'), 'raw square-root glyph must not leak into KaTeX input')

// Simple symbol-table entries should also get math typography even when they do
// not contain an operator.
var simpleSymbolHtml = formulaContent.normalizeStructuredContent('[{"symbol":"dx","note":"自变量微分"},{"symbol":"C","note":"任意常数"}]', 'symbols')
assert(simpleSymbolHtml.indexOf('$\\displaystyle dx$') >= 0, 'dx symbol entry must render through KaTeX')
assert(simpleSymbolHtml.indexOf('$\\displaystyle C$') >= 0, 'single-letter symbol entry must render through KaTeX')

// Historical formula blocks contain four dirty-data shapes that previously
// fell back to visible raw LaTeX source. Each one must now remain renderable.
var repairedFormulaBlocks = [
  '\\text{反对幂指三——分部积分选取}u\\text{的优先级：',
  '\\begin{array}{l} \\text{等价：任意矩阵，保持秩} \\\\ \\text{相似：方阵，保持特征多项式、特征值、det、tr、秩} \\\\ \\text{合同：实对称，保持秩、惯性指数} \\end{array}',
  '\\text{原X型区域的边界函数x=ψ(y)在投影区间内出现分段表达式时，} \\\\ \\text{交换后需要拆成多个Y型积分之和。}',
  "\\iint_\\Sigma P(x,y,z)dydz=\\pm\\iint_D P[x(y,z),y,z]\\,dydz\\ (\\text{前}``+''\\ \\text{后}``-''\\ );\\ Q\\ \\text{类似，右}``+''\\ \\text{左}``-''\\",
  '①\\ f(t)=P_m(t);\\ ②\\ f(t)=P_m(t)b^t',
]
repairedFormulaBlocks.forEach(function (source) {
  var normalized = formulaContent.normalizeLatexSource(source)
  var nodes = parse('$' + normalized + '$')
  var serialized = JSON.stringify(nodes)
  assert(serialized.indexOf('color:red') < 0, 'repaired historical formula must not produce a red KaTeX error: ' + source)
  assert(serialized.indexOf('KaTeX parse error') < 0, 'repaired historical formula must not expose a parse error: ' + source)
})

assert.strictEqual(
  formulaContent.normalizeLatexSource('\\text{相似：特征值、det、tr、秩}'),
  '\\text{相似：特征值、det、tr、秩}',
  'function-name normalization must not rewrite det inside \\text{}',
)
var greekTextRepair = formulaContent.normalizeLatexSource('\\text{边界函数x=ψ(y)在区间内}')
assert(greekTextRepair.indexOf('\\psi{}') >= 0, 'Greek glyph inside \\text{} must be lifted into math mode')
assert(greekTextRepair.indexOf('\\text{边界函数x=}') >= 0, 'prose around lifted Greek glyph must stay in text mode')
assert(!/[①-⑳]/.test(formulaContent.normalizeLatexSource('① a>0; ② b>0')), 'circled numerals must not reach katex-mini as unsupported glyphs')
assert(!/\\\s*$/.test(formulaContent.normalizeLatexSource('x+y\\')), 'orphan trailing backslash must be removed from dirty formula data')

console.log('✓ Extended formula-table audit regression tests passed')


// =============================
// Follow-up full-table audit regressions
// =============================
// A permissive HTML-tag splitter previously interpreted inequality text such
// as `0<a<1 ... x>0` as a fake <a ...> tag, causing the middle of the sentence
// to disappear after mp-html parsing. Keep relational chains inside KaTeX while
// continuing to preserve real markup.
var chainedInequalitySource = '底数大于 1 时递增，0<a<1 时递减；二者定义域均 x>0，均过 (1,0)。'
var chainedInequalityHtml = formulaContent.normalizeMixedContent(chainedInequalitySource)
assert(chainedInequalityHtml.indexOf('$\\displaystyle 0&lt;a&lt;1$') >= 0, '0<a<1 must be serialized as math, not mistaken for an HTML tag')
assert(chainedInequalityHtml.indexOf('$\\displaystyle x&gt;0$') >= 0, 'x>0 after a chained inequality must remain a separate KaTeX fragment')
assert(collectText(parse(chainedInequalityHtml)).join('').indexOf('时递减；二者定义域均') >= 0, 'inequality prose between < and > must not disappear during HTML parsing')

var explicitLessThanSource = '\\ln(1+x)<x（x>0）。'
var explicitLessThanHtml = formulaContent.normalizeMixedContent(explicitLessThanSource)
assert(explicitLessThanHtml.indexOf('$\\displaystyle \\ln(1+x)&lt;x$') >= 0, 'bare \\ln inequality must keep < inside the KaTeX fragment')
assert(explicitLessThanHtml.indexOf('$\\displaystyle x&gt;0$') >= 0, 'parenthetical x>0 must remain renderable after the < relation')
assert(collectText(parse(explicitLessThanHtml)).join('').indexOf('0）') >= 0, 'text following a <x ... > sequence must not be swallowed as markup')

var realMarkupHtml = formulaContent.normalizeMixedContent('<b>重点</b> 与 x<0')
assert(realMarkupHtml.indexOf('<b>重点</b>') === 0, 'real simple HTML markup must still be preserved by mixed-content normalization')
assert(realMarkupHtml.indexOf('$\\displaystyle x&lt;0$') >= 0, 'math next to preserved HTML markup must still be normalized')

// Function-valued denominators must include their arguments. Previously
// `sin x/cos x` became `\\frac{\\sin x}{\\cos}x` and `ln x/ln a` became
// `\\frac{\\ln x}{\\ln}a`, which is visibly and semantically wrong.
assert.strictEqual(formulaContent.normalizeMathRun('sin x/cos x'), '\\frac{\\sin x}{\\cos x}')
assert.strictEqual(formulaContent.normalizeMathRun('cos x/sin x'), '\\frac{\\cos x}{\\sin x}')
assert.strictEqual(formulaContent.normalizeMathRun('ln x/ln a'), '\\frac{\\ln x}{\\ln a}')
assert.strictEqual(formulaContent.normalizeMathRun('x/sin(x)'), '\\frac{x}{\\sin(x)}')

var changeOfBaseHtml = formulaContent.normalizeMixedContent('log_a x = ln x / ln a（换底公式）')
assert(changeOfBaseHtml.indexOf('\\frac{\\ln x}{\\ln a}') >= 0, 'change-of-base formula denominator must include the logarithm argument')
assert(changeOfBaseHtml.indexOf('}{\\ln} a') < 0, 'truncated function denominator must not remain in output')

console.log('✓ Follow-up full-table audit regressions passed')

// =============================
// New: non-math patterns guard
// =============================

// Dates must not be converted
assert.strictEqual(formulaContent.normalizeMixedContent('2026-07-18'), '2026-07-18', 'dates must not be converted')
assert.strictEqual(formulaContent.normalizeMixedContent('2026/07/18'), '2026/07/18', 'dates with slash must not be converted')

// URLs must not be converted
assert.strictEqual(formulaContent.normalizeMixedContent('https://xzshub.top/api/v1'), 'https://xzshub.top/api/v1', 'URLs must not be converted')

// Version numbers must not be converted
assert.strictEqual(formulaContent.normalizeMixedContent('v2.1.0'), 'v2.1.0', 'version numbers must not be converted')
assert.strictEqual(formulaContent.normalizeMixedContent('V3.0.1'), 'V3.0.1', 'version numbers (capital V) must not be converted')

// File paths must not be converted
assert.strictEqual(formulaContent.normalizeMixedContent('/usr/local/bin/node'), '/usr/local/bin/node', 'absolute paths must not be converted')
assert.strictEqual(formulaContent.normalizeMixedContent('./src/utils/helper.js'), './src/utils/helper.js', 'relative paths must not be converted')
assert.strictEqual(formulaContent.normalizeMixedContent('/api/formulas/123'), '/api/formulas/123', 'API paths must not be converted')

console.log('✓ Non-math pattern guard tests passed')

// =============================
// Source file integrity — block.note rich text
// =============================

// block.note must be rendered via rich-text (not plain <text>)
assert(/\bnoteNodes\b/.test(cardJs), 'block.note must be converted via noteNodes in formula-card/index.js')
assert(/normalizeMixedContent\(block\.note\)/.test(cardJs), 'block.note must be processed through normalizeMixedContent')
assert(/\{\{block\.noteNodes\}\}/.test(cardWxml), 'WXML must use rich-text with noteNodes for block.note')
assert(!/<text class="fc-block-note"[^>]*>\{\{block\.note\}\}<\/text>/.test(cardWxml), 'raw block.note text rendering must be removed')

console.log('✓ Source file integrity checks passed')

// =============================
// Improved error detection — containsRenderError must check
// more than just color:red
// =============================

// containsRenderError must check for katex-error class and data-error attr
assert(/katex-error/.test(cardJs),
  'containsRenderError must detect katex-error class')
assert(/data-error/.test(cardJs),
  'containsRenderError must check data-error attribute')
// cleanFormulaErrorNodes must use surgical l === "T" targeting
assert(/l\s*===/.test(cardJs) && /['"]T['"]/.test(cardJs),
  'cleanFormulaErrorNodes must target formula spans by l="T" tag')
// extractReadableText must handle nested \text and \operatorname
assert(/walkNestedText/.test(cardJs) || /\\text.*\\text/.test(cardJs),
  'extractReadableText must handle nested \\text{...}')

console.log('✓ Improved error detection pattern checks passed')

// =============================
// Inline KaTeX scrollbar artifact
// =============================
// Android/WeChat can paint an `overflow-x:auto` inline span's native scrollbar
// as a thick gray underline even when the formula fits. Reproduce the exact
// periodic-function condition from the reported screenshot and verify that
// compact inline formulae no longer become scroll containers, while genuinely
// long formulae still retain horizontal-overflow containment.
var capturedFormulaCardComponent = null
var previousComponentGlobal = global.Component
global.Component = function (definition) {
  capturedFormulaCardComponent = definition
}
var formulaCardModulePath = path.join(__dirname, '../subpackages/formulas/components/formula-card/index.js')
delete require.cache[require.resolve(formulaCardModulePath)]
require(formulaCardModulePath)
global.Component = previousComponentGlobal

function renderConditionNodesThroughFormulaCard(expression, id) {
  assert(capturedFormulaCardComponent, 'formula-card component definition must be capturable')
  var observer = capturedFormulaCardComponent.properties.card.observer
  var ctx = {
    data: { cardRenderKey: '', card: null },
    setData: function (patch) {
      this.data = Object.assign({}, this.data, patch)
    },
  }
  // The real runtime invokes observers on the component instance, so methods
  // like _syncGraphViewportRatio are available on `this`.
  var methods = capturedFormulaCardComponent.methods || {}
  for (var name in methods) {
    if (Object.prototype.hasOwnProperty.call(methods, name)) ctx[name] = methods[name]
  }
  observer.call(ctx, {
    id: id,
    title: '回归测试',
    conditions: JSON.stringify([{ expression: expression, note: '条件说明' }]),
  }, null)
  return ctx.data.content.conditionsNodes
}

function findInlineFormulaWrapper(nodes) {
  var found = null
  function walk(items) {
    if (found || !Array.isArray(items)) return
    for (var i = 0; i < items.length; i++) {
      var node = items[i] || {}
      if (node.l === 'T') {
        found = node
        return
      }
      if (node.children) walk(node.children)
      if (found) return
    }
  }
  walk(nodes)
  return found
}

var periodicConditionNodes = renderConditionNodesThroughFormulaCard('\\forall x\\in D_f,\\ x\\pm T\\in D_f', 95001)
var periodicFormulaWrapper = findInlineFormulaWrapper(periodicConditionNodes)
assert(periodicFormulaWrapper, 'periodic condition must contain an inline KaTeX wrapper')
var periodicWrapperStyle = String((periodicFormulaWrapper.attrs && periodicFormulaWrapper.attrs.style) || '')
assert(!/overflow-x\s*:\s*auto/.test(periodicWrapperStyle), 'compact inline KaTeX must not use overflow-x:auto (prevents gray thick underline scrollbar)')
assert(/overflow\s*:\s*visible/.test(periodicWrapperStyle), 'compact inline KaTeX should remain overflow:visible')
assert(!/padding\s*:\s*5rpx\s+0\s+7rpx/.test(periodicWrapperStyle), 'compact inline KaTeX must not reserve scrollbar padding')

var longInlineConditionNodes = renderConditionNodesThroughFormulaCard('a_1+a_2+a_3+a_4+a_5+a_6+a_7+a_8+a_9+a_{10}+a_{11}+a_{12}+a_{13}+a_{14}+a_{15}=S', 95002)
var longInlineFormulaWrapper = findInlineFormulaWrapper(longInlineConditionNodes)
assert(longInlineFormulaWrapper, 'long condition must contain an inline KaTeX wrapper')
var longWrapperStyle = String((longInlineFormulaWrapper.attrs && longInlineFormulaWrapper.attrs.style) || '')
assert(/overflow-x\s*:\s*auto/.test(longWrapperStyle), 'genuinely long inline KaTeX should retain horizontal overflow containment')

assert(/function\s+shouldScrollInlineFormula\s*\(/.test(cardJs), 'formula-card must classify inline formulae before enabling native horizontal overflow')

console.log('✓ Inline KaTeX gray-underline scrollbar regression tests passed')

// =============================
// Summary
// =============================

console.log()
console.log('='.repeat(60))
console.log('ALL FORMULA READER RENDERING REGRESSION CHECKS PASSED')
console.log('='.repeat(60))
