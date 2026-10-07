/* Formula reading regressions; Node only, no credentials or network. */
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const content = require('../subpackages/formulas/utils/formula-content')
const katex = require('../subpackages/formulas/utils/katex/katex.min')
const root = path.resolve(__dirname, '..')
const read = file => fs.readFileSync(path.join(root, file), 'utf8')
const prepare = latex => content.prepareFormulaBlocks({ formula_blocks: [{ label: '根式积分', latex }] })[0]
const longIntegral = String.raw`\int \sqrt{a^2-x^2}\,dx=\frac{a^2}{2}\arcsin\frac{x}{a}+\frac{x}{2}\sqrt{a^2-x^2}+C`
const fixture = prepare(longIntegral)
assert.equal(fixture.readingRows.length, 1)
assert.equal(fixture.readingRows[0].lines.length, 2, 'long equality breaks at its equals sign')
assert.equal(fixture.readingRows[0].lines.join('').replace(/\s/g, ''), fixture.latex.replace(/\s/g, ''),
  'layout must not drop operands, constants or conditions')
const grouped = prepare(String.raw`\int x\,dx=\frac{x^2}{2}+C\\\int x^2\,dx=\frac{x^3}{3}+C\\\int x^3\,dx=\frac{x^4}{4}+C`)
assert.equal(grouped.readingRows.length, 3, 'independent identities become separate rows')
assert.equal(prepare(String.raw`\begin{aligned}a&=b\\c&=d\end{aligned}`).readingRows.length, 2)
const preserved = [
  String.raw`\begin{aligned}a&=b\\&=c\end{aligned}`,
  String.raw`\begin{cases}x&x>0\\0&x\le0\end{cases}`,
  String.raw`\begin{pmatrix}1&2\\3&4\end{pmatrix}`,
  String.raw`\begin{aligned}x&=\begin{cases}1&t>0\\0&t\le0\end{cases}\\y&=0\end{aligned}`,
  String.raw`\begin{gathered}\text{a=b\\c=d}\end{gathered}`,
]
for (const latex of preserved) {
  const block = prepare(latex)
  assert.equal(block.readingRows.length, 1, 'structured expression stays atomic: ' + latex)
  assert.deepEqual(block.readingRows[0].lines, [block.latex])
}
for (const latex of [longIntegral + '=z', longIntegral.replace('=', '<='), longIntegral.replace('=', '< ='),
  longIntegral.replace('=', ':='),
  String.raw`\left|` + longIntegral + String.raw`\right|`,
  String.raw`\left\{` + longIntegral + String.raw`\right\}`, longIntegral + '{']) {
  assert.deepEqual(content.formulaReadingLines(latex), [latex], 'ambiguous splitting fails closed')
}
assert.deepEqual(content.formulaReadingLines('x=y'), ['x=y'])
const absoluteIntegral = longIntegral.replace('=\\frac', '=\\left|\\frac') + String.raw`\right|`
assert.equal(content.formulaReadingLines(absoluteIntegral).length, 2,
  'absolute values on the right must not block a safe equality split')
for (const block of [fixture, grouped, ...preserved.slice(0, 4).map(prepare)]) {
  for (const row of block.readingRows) for (const latex of row.lines) {
    assert.doesNotMatch(katex.renderToString(latex, { throwOnError: true }), /katex-error/)
  }
}
// Exercise component methods and observer invalidation without a WeChat runtime.
let definition
const previousWx = global.wx
global.wx = { getWindowInfo: () => ({ windowWidth: 375 }), getDeviceInfo: () => ({ system: 'Node test' }) }
const previous = global.Component
global.Component = value => { definition = value }
try { require('../subpackages/formulas/components/formula-card/index') } finally {
  if (previous === undefined) delete global.Component
  else global.Component = previous
  if (previousWx === undefined) delete global.wx
  else global.wx = previousWx
}
const runtimeFixture = Object.assign({}, fixture, {
  readingRows: fixture.readingRows.map(row => Object.assign({}, row, {
    lineItems: row.lines.map((line, index) => ({ _key: String(index), mathNodes: [] })),
    fullLineItem: { _key: row._key + '-full', mathNodes: [] },
  })),
})
const target = Object.assign({
  data: { ...definition.data, formulaBlocks: [runtimeFixture], card: {} },
  events: [], writes: [],
  createSelectorQuery: () => queryFixture([[{ width: 100, height: 40 }, { width: 100, height: 40 }], { height: 18 }, null]),
  setData(patch, callback) { this.writes.push(patch); Object.assign(this.data, patch); if (callback) callback() },
  triggerEvent(name) { this.events.push(name) },
}, definition.methods)
target.openFormulaReading({ currentTarget: { dataset: { index: 0 } } })
assert.equal(target.data.expandedBlock.latex, fixture.latex)
assert.equal(target.data.expandedBlock.readingRows[0].lineItems.length, 1, 'panel starts with complete equations')
assert.equal(runtimeFixture.readingRows[0].lineItems.length, 2, 'panel never mutates the reader source')
assert.deepEqual(target.events, ['formulastart', 'readingchange'])
target.closeFormulaReading()
target.closeFormulaReading() // Native afterleave may fire after the close button.
assert.equal(target.data.expandedBlock, null)
assert.deepEqual(target.events, ['formulastart', 'readingchange', 'readingchange', 'formulaend'])
target.openFormulaReading({ currentTarget: { dataset: { index: 99 } } })
assert.equal(target.data.expandedBlock, null)
target.openFormulaReading({ currentTarget: { dataset: { index: 0 } } })
definition.properties.card.observer.call(target, { id: 2, formula_blocks: [{ latex: 'x=y' }] }, { id: 1 })
assert.equal(target.data.expandedBlock, null, 'switching card dismisses stale expanded content')
assert.equal(target.events.at(-1), 'formulaend')
assert.equal(target.data.formulaBlocks[0].readingRows[0].lineItems.length, 1)
assert.match(read('subpackages/formulas/reader/index.wxml'), /currentCard && !formulaReadingExpanded/)
// Reader must not interpret horizontal formula scrolling as card navigation.
let readerDefinition
require('node:vm').runInNewContext(read('subpackages/formulas/reader/index.js'), {
  require: () => ({}), Page: value => { readerDefinition = value }, console,
  clearTimeout: () => {}, setTimeout: callback => { callback(); return 1 },
})
const reader = Object.assign({}, readerDefinition, {
  data: { ...readerDefinition.data, readerScrollTop: 1750 },
  nextCount: 0,
  setData(patch) { Object.assign(this.data, patch) },
  goNext() { this.nextCount++ },
})
function swipeLeft() {
  reader.onReaderTouchStart({ touches: [{ clientX: 200, clientY: 100 }] })
  reader.onReaderTouchMove({ touches: [{ clientX: 80, clientY: 100 }] })
  reader.onReaderTouchEnd({ changedTouches: [{ clientX: 80, clientY: 100 }] })
}
reader.onFormulaReadingChange({ detail: { expanded: true } })
reader.onFormulaGestureStart()
swipeLeft()
assert.equal(reader.nextCount, 0, 'expanded/formula gesture cannot change the card')
reader.onFormulaReadingChange({ detail: { expanded: false } })
reader.onFormulaGestureEnd()
assert.equal(reader.data.readerScrollTop, 1750, 'closing must not reset scroll position')
swipeLeft()
assert.equal(reader.nextCount, 1, 'normal page swipe still changes the card')
const template = read('subpackages/formulas/components/formula-card/index.wxml')
assert.match(template, /class="fc-formula-line-scroll"/)
assert.match(template, /<page-container[\s\S]*bind:afterleave="closeFormulaReading"/)
assert.match(template, /bindtouchstart="onFormulaTouchStart"/)
assert.doesNotMatch(template, /bind:afterenter|fitFormulaReading/)
assert.doesNotMatch(template, /height:90vh|>完成<|>展开阅读<|<button[^>]*fc-(?:reading-close|expand-button)/)
assert.match(template, /role="button" aria-label="关闭公式阅读"/)
const { fitReadingHeight, readingViewport, prepareReadingLayout } = require('../subpackages/formulas/utils/formula-reading-layout')
assert.deepEqual(readingViewport({ windowWidth: 375, windowHeight: 800 }), { width: 375, rpx: 0.5, maxHeight: 640, bottomInset: 0 })
assert.deepEqual(fitReadingHeight(70, 60, 640), { height: 130, scrollHeight: 70 })
assert.deepEqual(fitReadingHeight(900, 60, 640), { height: 640, scrollHeight: 580 })
assert.deepEqual(fitReadingHeight(250, 60, 640), { height: 310, scrollHeight: 250 })
// Geometry is resolved BEFORE visibility, using only existing reader nodes.
function queryFixture(rects, deferred) {
  return {
    selectAll() { return this }, select() { return this }, boundingClientRect() { return this },
    exec(callback) { if (deferred) deferred.push(() => callback(rects)); else callback(rects) },
  }
}
const viewport = readingViewport({ windowWidth: 375, windowHeight: 800 })
const fitting = [[{ width: 100, height: 40 }, { width: 100, height: 40 }], { height: 18 }, null]
let layout = prepareReadingLayout(runtimeFixture, fitting, viewport)
assert.equal(layout.expandedBlock.readingRows[0].lineItems.length, 1)
assert.equal(layout.expandedBlock.hasWideRows, false)
assert.equal('fullLineItem' in layout.expandedBlock.readingRows[0], false, 'panel payload excludes unused math trees')
assert.ok(layout.expandedHeight < 200, 'small content remains compact')
layout = prepareReadingLayout(runtimeFixture,
  [[{ width: 200, height: 900 }, { width: 500, height: 900 }], { height: 18 }, null], viewport)
assert.equal(layout.expandedBlock.readingRows[0].lineItems.length, 2)
assert.equal(layout.expandedHeight, viewport.maxHeight)
assert.equal(layout.expandedBlock.hasWideRows, true)
assert.deepEqual(readingViewport({ windowWidth: 375, windowHeight: 800, screenHeight: 844, safeArea: { bottom: 810 } }),
  { width: 375, rpx: 0.5, maxHeight: 640, bottomInset: 34 })
const deferred = []
target.data.formulaBlocks = [runtimeFixture]
target._readingLayouts = {}
target.writes = []
let queryCount = 0
target.createSelectorQuery = () => { queryCount++; return queryFixture(fitting, deferred) }
target.openFormulaReading({ currentTarget: { dataset: { index: 0 } } })
assert.equal(target.data.expandedBlock, null, 'native entry waits for final layout')
assert.equal(target.writes.length, 0, 'no provisional visible panel')
target.openFormulaReading({ currentTarget: { dataset: { index: 0 } } })
assert.equal(queryCount, 1, 'double-tap does not queue a second opening')
deferred.shift()()
assert.equal(target.writes.length, 1, 'final nodes and dimensions are supplied in ONE update')
assert.ok(target.writes[0].expandedHeight > 0)
assert.ok(target.writes[0].expandedHeaderHeight > 0)
assert.equal(target.data.expandedBlock.readingRows[0].lineItems.length, 1)
const cachedHeight = target.data.expandedHeight
target.closeFormulaReading()
target.writes = []
target.openFormulaReading({ currentTarget: { dataset: { index: 0 } } })
assert.equal(queryCount, 1, 'reopening uses cached layout, not a new measurement')
assert.equal(target.data.expandedHeight, cachedHeight)
assert.equal(target.writes.length, 1)
target.closeFormulaReading()
target._readingLayouts = {}
target.openFormulaReading({ currentTarget: { dataset: { index: 0 } } })
target.closeFormulaReading()
deferred.shift()()
assert.equal(target.data.expandedBlock, null, 'late measurement must not reopen a dismissed panel')
assert.equal(target._readingOpening, false)
target.openFormulaReading({ currentTarget: { dataset: { index: 0 } } })
definition.properties.card.observer.call(target, { id: 3, formula_blocks: [{ latex: 'x=z' }] }, { id: 2 })
deferred.shift()()
assert.equal(target.data.expandedBlock, null, 'card change cancels a pending opening')
const componentSource = read('subpackages/formulas/components/formula-card/index.js')
const opening = componentSource.slice(componentSource.indexOf('    openFormulaReading('), componentSource.indexOf('    closeFormulaReading('))
assert.doesNotMatch(opening, /renderFormulaNodes|setTimeout/, 'click path never parses math or waits for animation')

for (const page of ['library', 'reader']) {
  assert.match(read(`subpackages/formulas/${page}/index.wxml`), /variant="mint"/)
  const config = JSON.parse(read(`subpackages/formulas/${page}/index.json`))
  assert.equal(config.backgroundColor, '#F3FBF8')
  assert.doesNotMatch(read(`subpackages/formulas/${page}/index.wxss`), /#(?:B7E82A|F4F4EE|C9F44D)/i)
}
console.log('Formula reader layout, math integrity, expanded reading and mint theme checks passed')
