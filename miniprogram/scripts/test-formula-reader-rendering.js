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

console.log('Formula reader rendering regression checks passed.')
console.log('conditions:', conditionsHtml)
console.log('errorTips:', errorTipsHtml)
console.log('blockLabel:', blockLabelHtml)
console.log('greekExponentBlockLabel:', greekExponentBlockLabelHtml)
