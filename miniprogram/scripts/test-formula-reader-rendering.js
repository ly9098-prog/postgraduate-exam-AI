/* eslint-disable no-console */
const assert = require('assert')

const formulaContent = require('../utils/formula-content')

global.wx = global.wx || {
  getWindowInfo() { return { windowWidth: 375 } },
  getDeviceInfo() { return { system: 'Node.js regression test' } },
}

const Parser = require('../components/mp-html/parser')
const LatexPlugin = require('../components/mp-html/latex/index')

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
    if (node && node.children) collectClasses(node.children, result)
  })
  return result
}

function collectText(nodes, result) {
  result = result || []
  ;(nodes || []).forEach(function (node) {
    if (node && node.type === 'text') {
      result.push(String(node.text))
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
const cardJs = fs.readFileSync(path.join(__dirname, '../components/formula-card/index.js'), 'utf8')
const cardWxml = fs.readFileSync(path.join(__dirname, '../components/formula-card/index.wxml'), 'utf8')
const cardWxss = fs.readFileSync(path.join(__dirname, '../components/formula-card/index.wxss'), 'utf8')
assert(/labelNodes:\s*parseRichNodes\(formulaContent\.normalizeMixedContent\(block\.label\)\)/.test(cardJs), 'block.label must be converted into rich LaTeX nodes')
assert(/nodes="\{\{block\.labelNodes\}\}"/.test(cardWxml), 'upper-left formula block label must render labelNodes')
assert(!/<text class="fc-block-label"[^>]*>\{\{block\.label\}\}<\/text>/.test(cardWxml), 'raw block.label text rendering must be removed')
assert(/class="fc-graph-viewport"/.test(cardWxml), 'graph image must be wrapped in a crop viewport')
assert(/\.fc-graph-image\s*\{[\s\S]*transform:\s*scale\(1\.12\)/.test(cardWxss), 'graph image must be enlarged inside the reader')

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
// New Issue 3: det operator rendering
// =============================

// det(A) must become \det(A) via normalizeLatexSource
var detSource = formulaContent.normalizeLatexSource('det(A)')
assert(detSource.indexOf('\\det') >= 0, 'normalizeLatexSource must convert det(A) to include \\det')
assert(detSource.indexOf('\\\\det') < 0, '\\det must not be double-escaped')

// \det(A) must stay as \det(A) — no double escaping
var detPreEscaped = formulaContent.normalizeLatexSource('\\det(A)')
assert(detPreEscaped.indexOf('\\det') >= 0, '\\det must be preserved in normalizeLatexSource')
assert(detPreEscaped.indexOf('\\\\det') < 0, 'pre-escaped \\det must not be double-escaped')

// Within normalizeMathRun, det must also be handled
var detMathRun = formulaContent.normalizeLatexSource('det(A^T)=det(A)')
assert(detMathRun.indexOf('\\det') >= 0, 'det must be converted in compound expressions')

// det(AB)=det(A)det(B) with multiple det
var detProduct = formulaContent.normalizeLatexSource('det(AB)=det(A)det(B)')
assert(detProduct.indexOf('\\det') >= 0, 'det in product expression must be converted')
// Count occurrences of bare det (not preceded by backslash)
var bareDetRe = /(^|[^\\])det(?=[^A-Za-z]|$)/g
var bareDetMatches = detProduct.match(bareDetRe)
assert(bareDetMatches === null, 'all bare det must be converted — none should remain (found ' + (bareDetMatches || []).length + ')')

// Full rendering: det(A) should produce KaTeX math operator (class mop or similar)
var detHtml = formulaContent.normalizeMixedContent('det(A)')
assert(detHtml.indexOf('\\det') >= 0, 'det(A) in mixed content must produce \\det')

var detNodes = parse(detHtml)
var detClasses = collectClasses(detNodes)
// In katex-mini, \det produces a math operator, typically with class "mop"
var hasOperatorClass = detClasses.some(function (name) { return /mop/.test(name) })
assert(hasOperatorClass, 'det(A) rendered nodes must contain math operator class (mop)')
assert(!JSON.stringify(detNodes).includes('color:red'), 'det(A) rendering must not produce KaTeX error')

// sin, cos, tan, ln etc. must still work
assert(formulaContent.normalizeLatexSource('sin x').indexOf('\\sin') >= 0, 'sin must still be converted')
assert(formulaContent.normalizeLatexSource('cos x').indexOf('\\cos') >= 0, 'cos must still be converted')

// English words containing "det" substring should NOT be affected
assert.strictEqual(formulaContent.normalizeLatexSource('determine'), 'determine', 'words containing det must not be modified')

console.log('✓ Issue 3 (det operator) tests passed')

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
// Summary
// =============================

console.log()
console.log('='.repeat(60))
console.log('ALL FORMULA READER RENDERING REGRESSION CHECKS PASSED')
console.log('='.repeat(60))
