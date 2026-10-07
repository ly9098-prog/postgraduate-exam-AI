/* Regression checks for the mint reference layout and existing runner actions.
 * Run: node tests/test-practice-reference-ui.js (no WeChat/network required).
 */
const assert = require('assert')
const fs = require('fs')
const path = require('path')
const root = path.resolve(__dirname, '..')
const read = (p) => fs.readFileSync(path.join(root, p), 'utf8')
const runnerPath = 'subpackages/study/components/quiz-runner/'
const wxml = read(runnerPath + 'quiz-runner.wxml')
const theme = read(runnerPath + 'practice-theme.wxss')
const setup = read('subpackages/study/practice/practice.wxml')
const setupCss = read('subpackages/study/practice/practice.wxss')
const runnerCss = read(runnerPath + 'quiz-runner.wxss')
assert.ok(runnerCss.indexOf("@import './practice-theme.wxss'") >= 0)
assert.ok(runnerCss.indexOf("@import './practice-theme.wxss'") < runnerCss.indexOf('.quiz-runner{'), 'WeChat theme import precedes style rules')
for (const importPath of ['../../../../styles/tokens.wxss', '../code-block/code-block.wxss']) {
  assert.ok(runnerCss.includes("@import '" + importPath + "'"), 'runner retains icon/code primitives')
}
assert.ok(setupCss.includes("@import '../../../styles/tokens.wxss'"), 'setup keeps icon primitives')
assert.ok(setupCss.includes('.reward-strip'), 'live reward-strip styling is retained during source budget cleanup')
const resultCss = read('subpackages/study/practice-result/index.wxss')
for (const cls of ['compact-list-content-all', 'review-status-correct', 'review-answer-user-partial']) {
  assert.ok(resultCss.includes('.' + cls), 'dynamic result status class is preserved: ' + cls)
}

// Formatting is not a UI invariant. Keep descendant-selector whitespace while
// allowing the package's declaration-spacing cleanup.
const normalizeCss = css => css.replace(/\s+/g, ' ').replace(/\s*([{}:;,])\s*/g, '$1').replace(/;}/g, '}')
const hasCss = (css, rule) => normalizeCss(css).includes(normalizeCss(rule))

assert.ok(wxml.includes('runner-reference-hero'))
assert.ok(wxml.includes('runner-timer-pill'))
assert.ok(wxml.includes('/assets/icons/practice/clock.svg'))
assert.ok(wxml.includes('navigationBarHeight'))
assert.ok(setup.includes('navigationBarHeight="{{navBarHeight}}"'))
const referenceHero = wxml.slice(wxml.indexOf('<view class="runner-hero runner-reference-hero'), wxml.indexOf('<scroll-view'))
assert.ok(!referenceHero.includes('runner-eyebrow'), 'reference header has no duplicate practice label')
assert.ok(referenceHero.indexOf('runner-timer-pill') > referenceHero.indexOf('runner-number-row'), 'timer belongs to the number row')
assert.strictEqual((wxml.match(/<template name="runner-navigation">/g) || []).length, 1)
assert.strictEqual((wxml.match(/<template is="runner-navigation"/g) || []).length, 1)
const scroll = wxml.slice(wxml.indexOf('<scroll-view'), wxml.indexOf('</scroll-view>'))
assert.ok(!scroll.includes('runner-navigation'), 'no navigation controls scroll with the question')
assert.ok(wxml.slice(wxml.indexOf('</scroll-view>')).includes('wx:if="{{showNavigation}}"'), 'all variants render navigation after the viewport')
for (const mode of ['SEGMENTS', 'RICH_TEXT', 'CODE', 'LATEX', 'MIXED']) {
  assert.strictEqual((wxml.match(new RegExp("_displayQuestion\\._renderModel\\.mode === '" + mode + "'", 'g')) || []).length, 1, mode + ' has one rendering branch')
}
assert.ok(/\.runner-reference \.runner-q-wrap\s*\{[^}]*min-height:\s*0;/.test(theme), 'card uses natural content height')
assert.ok(/\.runner-reference:not\(\.runner-compact\) \.runner-bottom-bar\s*\{[^}]*position:\s*fixed;[^}]*bottom:\s*0;/.test(theme), 'full sessions anchor navigation to viewport bottom')
assert.ok(theme.includes('env(safe-area-inset-bottom)'))
assert.ok(/\.runner-reference \.runner-bottom-inner > \.runner-next,[\s\S]*?background:\s*linear-gradient\(110deg,\s*#32AF8B 0%,\s*#3A6F5B 100%\)/.test(theme), 'mint primary matches legacy selector specificity')
assert.ok(!/(?:color|background(?:-color)?):[^;]*!important/.test(theme), 'palette overrides are scoped without forced colors')
assert.ok(hasCss(setupCss, '.mode-card.active .mode-title, .count-btn.active .count-main { color: #23483C; }'))
assert.ok(hasCss(setupCss, '.mode-card.active .mode-desc, .count-btn.active .count-time { color: #507568; }'))
assert.ok(hasCss(setupCss, '.parent-arrow.up { transform: rotate(90deg); }'), 'expanded subject chevron points down')
assert.ok(setup.includes('panel-collapse-arrow line-icon icon-chevron-down up'), 'collapse chevron points up')
assert.ok(!/>(?:›|⌄|⌃|↝|≡|◎|✓)<\//.test(setup), 'setup controls use drawn icons rather than font glyphs')
for (const css of [theme, setupCss]) {
  assert.ok(hasCss(css, 'left: 50%; top: 50%; width: 12rpx; height: 12rpx;'), 'chevron is centred in the actual box')
}

let definition
const originalComponent = global.Component
global.Component = (config) => { definition = config }
require(path.join(root, runnerPath, 'quiz-runner.js'))
global.Component = originalComponent
function instance(overrides = {}) {
  const data = Object.assign({}, definition.data)
  for (const [key, prop] of Object.entries(definition.properties)) data[key] = prop.value
  Object.assign(data, overrides)
  const events = []
  const target = Object.assign({ data, events, setData(patch, cb) { Object.assign(this.data, patch); if (cb) cb() }, triggerEvent(name, detail) { events.push({ name, detail }) } }, definition.methods)
  definition.created.call(target)
  return target
}
const runner = instance({ totalCount: 5, externalSwitchAnimation: true, currentQuestion: { id: 1 } })
runner.goPrev()
assert.strictEqual(runner.events.length, 0, 'first question cannot go back')
runner.goNext()
assert.deepStrictEqual(runner.events.pop(), { name: 'next', detail: { index: 1 } })
runner.data.currentIndex = 4
runner.goNext()
assert.strictEqual(runner.events.length, 0, 'last question cannot go forward')
runner.data.submitDisabled = true
runner.onSubmit()
assert.strictEqual(runner.events.length, 0, 'disabled submission cannot fire')
runner.data.submitDisabled = false
runner.data.submitting = true
runner.onSubmit()
assert.strictEqual(runner.events.length, 0, 'submission in progress cannot fire')
runner.data.submitting = false
runner.onSubmit()
assert.strictEqual(runner.events.pop().name, 'submit')
runner.toggleSheet()
assert.strictEqual(runner.data.showSheet, true)
assert.strictEqual(runner.events.pop().name, 'toggleanswercard')
runner.goQuestion({ currentTarget: { dataset: { index: '2' } } })
assert.deepStrictEqual(runner.events.pop(), { name: 'jump', detail: { index: 2 } })
assert.strictEqual(runner.data.showSheet, false)
const scrollWrites = []
const originalSetData = runner.setData
runner.setData = patch => { scrollWrites.push(patch); Object.assign(runner.data, patch) }
runner.onQuestionScroll({ detail: { scrollTop: 120 } })
assert.strictEqual(runner._lastQuestionScrollTop, 120)
assert.strictEqual(scrollWrites.length, 0, 'scrolling tracks viewport without changing the header')
assert.ok(!Object.hasOwn(definition.properties, 'heroCollapseEnabled'))
assert.ok(!Object.hasOwn(definition.data, 'heroCollapsed'))
assert.strictEqual(typeof runner.expandHero, 'undefined')
runner.setData = originalSetData
const stable = instance({ currentIndex: 1, totalCount: 3, externalSwitchAnimation: true })
const writes = []
stable.setData = function (patch, cb) { writes.push(patch); Object.assign(this.data, patch); if (cb) cb() }
stable.goNext()
assert.deepStrictEqual(stable.events.pop(), { name: 'next', detail: { index: 2 } })
assert.strictEqual(writes.length, 0, 'external-animation parents retain synchronous navigation')
stable.goPrev()
assert.deepStrictEqual(stable.events.pop(), { name: 'prev', detail: { index: 0 } })
stable._lastQuestionScrollTop = 0
const observeQuestion = definition.observers['currentQuestion, answerState']
const first = { id: 100, _renderModel: { mode: 'RICH_TEXT', richTextNodes: [] } }
const second = { id: 101, _renderModel: { mode: 'CODE', rawText: '  return 1;' } }
observeQuestion.call(stable, first, null)
stable._lastQuestionScrollTop = 0
writes.length = 0
observeQuestion.call(stable, second, null)
assert.ok(!Object.hasOwn(stable.data, 'heroCollapsed'), 'header has no collapsible state')
assert.strictEqual(writes.length, 1, 'new question at top has only the render data update')
assert.ok(writes.every(patch => !Object.hasOwn(patch, 'animClass') && !Object.hasOwn(patch, 'questionScrollIntoView')))
assert.strictEqual(stable.data._codeLines.length, 1, 'code rendering still decorates each line')
const sameAnswer = { questionId: 101, answer: 'A' }
writes.length = 0
observeQuestion.call(stable, second, sameAnswer)
assert.ok(writes.every(patch => !Object.hasOwn(patch, 'questionScrollIntoView')), 'answer-only updates never scroll the question')
const review = read('subpackages/study/review-today/review-today.wxml')
assert.ok(review.includes('flowLayout="{{false}}"'), 'review uses the same internal scroll viewport')
assert.ok(review.includes('reviewNavigationHeight'), 'review viewport accounts for its navbar height')
for (const icon of ['shuffle', 'list-ordered', 'target', 'clock', 'notebook-tabs']) {
  assert.ok(fs.existsSync(path.join(root, 'assets/icons/practice/' + icon + '.svg')))
}
assert.ok(setup.includes('hero-config-icon'), 'reference plan 2 summary has a mode icon')
const confirmationCss = read('subpackages/study/components/submit-confirm/submit-confirm.wxss')
assert.ok(confirmationCss.includes('.sc-icon-line.icon-exclamation::before'), 'confirmation owns its component-scoped drawn icon primitives')
assert.ok(/\.sc-theme-mint \.sc-card \.sc-top-accent\s*\{[^}]*#7ED8B5/.test(confirmationCss), 'mint accent matches legacy scenario specificity')
console.log('Practice reference UI and runner action regressions passed')

// Optional: validate WeChat's actual compiled template, not a replacement HTML layout.
if (process.argv[2]) {
  const vm = require('vm')
  const context = { window: { __webview_engine_version__: 0.02 }, console }
  vm.createContext(context)
  vm.runInContext(fs.readFileSync(process.argv[2], 'utf8'), context)
  const render = context.$gwx('subpackages/study/components/quiz-runner/quiz-runner.wxml')
  assert.strictEqual(typeof render, 'function')
  const fixture = { mode: 'practice', theme: 'default', totalCount: 5, currentIndex: 0, showNavigation: true, showSubmitButton: true, submitText: '交卷复盘', showBackButton: true, questions: Array.from({ length: 5 }, (_, i) => ({ id: i })), _displayQuestion: { id: 1, _renderModel: { mode: 'RICH_TEXT', richTextNodes: [] } }, _optionList: [], subjectName: '数据结构', elapsedText: '00:04', _qTypeLabel: '单选题' }
  const all = (node) => [node, ...(node.children || []).flatMap((child) => typeof child === 'object' && child ? all(child) : [])]
  const byClass = (tree, cls) => all(tree).filter((n) => ((n.attr || {}).class || '').split(/\s+/).includes(cls))
  for (const [mode, index, expected] of [['practice', 0, 'runner-next'], ['practice', 4, 'runner-final-submit'], ['review', 0, 'runner-next'], ['review', 4, 'runner-final-submit'], ['exam', 0, 'runner-next'], ['exam', 4, 'runner-final-submit'], ['wrong-detail', 0, 'runner-next']]) {
    const tree = render(Object.assign({}, fixture, { mode, currentIndex: index }))
    assert.strictEqual(byClass(tree, 'runner-bottom-bar').length, 1, mode + ' only renders one action bar')
    assert.strictEqual(byClass(tree, expected).length, 1, mode + ' renders the expected final/next action')
    if (mode === 'practice' || mode === 'review' || mode === 'exam') {
      assert.strictEqual(byClass(tree, 'runner-reference-hero').length, 1)
      assert.strictEqual(byClass(tree, 'runner-timer-pill').length, 1)
      assert.strictEqual(byClass(tree, 'runner-eyebrow').length, 0)
      assert.strictEqual(byClass(byClass(tree, 'runner-question-area')[0], 'runner-bottom-bar').length, 0)
    } else {
      assert.strictEqual(byClass(tree, 'runner-reference-hero').length, 0)
      assert.strictEqual(byClass(byClass(tree, 'runner-question-area')[0], 'runner-bottom-bar').length, 0)
    }
  }
  const compact = render(Object.assign({}, fixture, { mode: 'review', compactReviewMode: true }))
  assert.strictEqual(byClass(compact, 'runner-reference-hero').length, 0, 'compact review is not restyled')
  assert.strictEqual(byClass(compact, 'runner-bottom-bar').length, 1)
  const noNav = render(Object.assign({}, fixture, { showNavigation: false }))
  assert.strictEqual(byClass(noNav, 'runner-bottom-bar').length, 0)
  console.log('Compiled WeChat WXML first/last and shared-mode checks passed')
}
