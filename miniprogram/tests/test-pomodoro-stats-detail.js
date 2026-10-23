/**
 * Detail-popup interaction and backdrop-style regression checks.
 * Run: cd miniprogram && node tests/test-pomodoro-stats-detail.js
 * These checks do not replace WeChat simulator/device rendering verification.
 */
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')

const pageDir = path.join(__dirname, '../subpackages/productivity/pomodoro-stats')
const styles = fs.readFileSync(path.join(pageDir, 'index.wxss'), 'utf8')
const template = fs.readFileSync(path.join(pageDir, 'index.wxml'), 'utf8')
const rules = Array.from(styles.replace(/\/\*[\s\S]*?\*\//g, '').matchAll(/([^{}]+)\{([^{}]*)\}/g))

function getDeclarations(selector) {
  const declarations = {}
  for (const [, selectors, body] of rules) {
    if (!selectors.split(',').map(value => value.trim()).includes(selector)) continue
    for (const declaration of body.split(';')) {
      const separator = declaration.indexOf(':')
      if (separator < 0) continue
      declarations[declaration.slice(0, separator).trim()] = declaration.slice(separator + 1).trim()
    }
  }
  return declarations
}

// Include later grouped theme rules, which previously extended opacity fading to 440ms.
const overlay = getDeclarations('.detail-overlay')
const visibleOverlay = { ...overlay, ...getDeclarations('.detail-overlay.visible') }
assert.equal(overlay.visibility, 'hidden', 'closed overlay must be hidden without opacity fading')
assert.equal(overlay['pointer-events'], 'none', 'closed overlay must not intercept taps')
assert.equal(visibleOverlay.visibility, 'visible', 'open overlay must be visible immediately')
assert.equal(visibleOverlay['pointer-events'], 'auto', 'open overlay must accept dismissal taps')
for (const state of [overlay, visibleOverlay]) {
  assert.ok(!state.opacity || state.opacity === '1', 'overlay must not isolate its backdrop with opacity < 1')
  assert.ok(!state.transition || state.transition === 'none', 'overlay must not delay visibility changes')
  assert.ok(!state['transition-property'], 'theme transitions must exclude the overlay')
  assert.ok(!state.animation || state.animation === 'none', 'only the card may animate on opening')
}
const backdrop = getDeclarations('.detail-overlay::before')
assert.equal(backdrop['backdrop-filter'], 'blur(12rpx)')
assert.equal(backdrop['-webkit-backdrop-filter'], 'blur(12rpx)')
assert.ok(backdrop.background, 'dark theme must retain its dimming backdrop')
assert.ok(getDeclarations('.theme-light .detail-overlay::before').background, 'light theme must retain its backdrop')
assert.match(getDeclarations('.detail-card').animation, /popup-in/, 'card entrance animation must be preserved')
assert.match(template, /class="detail-overlay \{\{selectedSubjectDetail \? 'visible' : ''\}\}"\s+catchtap="closeDetail"\s+catchtouchmove="noop"/)
assert.match(template, /class="detail-card" catchtap="noop" wx:if="\{\{selectedSubjectDetail\}\}"/)

// Load the actual page handlers with isolated dependencies and a synchronous selector mock.
let pageConfig
let selectedRectCallback
const pieTapControllerModule = require('../subpackages/productivity/pomodoro-stats/pie-tap-controller')
const wxQueryMock = {
  createSelectorQuery: () => ({
    in() { return this },
    select(selector) { assert.equal(selector, '#pie-canvas'); return this },
    boundingClientRect(callback) { selectedRectCallback = callback; return this },
    exec() { selectedRectCallback(rect) },
  }),
}
const timers = []
const rect = { left: 10, top: 20, width: 200, height: 200 }
vm.runInNewContext(fs.readFileSync(path.join(pageDir, 'index.js'), 'utf8'), {
  require: () => ({}),
  Page: config => { pageConfig = config },
  setTimeout: (callback, delay) => { timers.push({ callback, delay }) },
  wx: {
    createSelectorQuery: () => ({
      in() { return this },
      select(selector) { assert.equal(selector, '#pie-canvas'); return this },
      boundingClientRect(callback) { selectedRectCallback = callback; return this },
      exec() { selectedRectCallback(rect) },
    }),
  },
}, { filename: path.join(pageDir, 'index.js') })

// Expose the page controller factory for the isolated detail regression fixture.
pageConfig._createPieTapControllerForPage = page =>
  pieTapControllerModule.createPieTapController({
    isAlive: () => page._alive,
    hasDistributionData: () => page.data.distributionHasData,
    getSubjects: () => page.data.subjects,
    getSelectedSubjectDetail: () => page.data.selectedSubjectDetail,
    getGeometry: pageRect => page._getPieGeometry(pageRect),
    createSelectorQuery: () => wxQueryMock.createSelectorQuery(),
    setData: (patch, callback) => page.setData(patch, callback),
    renderPie: progress => page._renderPieChart(progress),
    setTimeout: (callback, delay) => { timers.push({ callback, delay }) },
  })

const subjects = [
  { subject: 'math', duration_sec: 60, sessions: 1, _label: '数学' },
  { subject: 'english', duration_sec: 60, sessions: 1, _label: '英语' },
]
const patches = []
const renders = []
const page = {
  data: { ...pageConfig.data, subjects, distributionHasData: true },
  _alive: true,
  _getPieGeometry: () => ({ centerX: 100, centerY: 100, radius: 80, tilt: 0.5 }),
  _getPieTapController() {
    if (!this.__pieTapController) this.__pieTapController = pageConfig._createPieTapControllerForPage(this)
    return this.__pieTapController
  },
  _renderPieChart: progress => { renders.push(progress) },
  setData(patch, callback) {
    patches.push(patch)
    Object.assign(this.data, patch)
    if (callback) callback()
  },
}
function tap(clientX, clientY) {
  pageConfig.onPieTap.call(page, { changedTouches: [{ clientX, clientY }] })
}

tap(150, 120)
assert.equal(patches[0].selectedSubjectDetail, subjects[0], 'first update must show details, without a timer')
assert.equal(page.data._selectedSubject, 'math')
assert.equal(page.data.pieTapped, true)
assert.deepEqual(renders, [1], 'selected sector must redraw')
assert.equal(timers.length, 1)
assert.equal(timers[0].delay, 350, 'timer is only for pie tap feedback')
timers[0].callback()
assert.equal(page.data.pieTapped, false)
assert.equal(page.data.selectedSubjectDetail, subjects[0], 'feedback timer must not dismiss details')

pageConfig.noop.call(page)
assert.equal(page.data.selectedSubjectDetail, subjects[0], 'card tap must not dismiss details')
pageConfig.closeDetail.call(page)
assert.equal(page.data.selectedSubjectDetail, null)
assert.equal(page.data._selectedSubject, null)
tap(70, 120)
assert.equal(page.data.selectedSubjectDetail, subjects[1], 'reopening must select the new sector')
tap(310, 120)
assert.equal(page.data.selectedSubjectDetail, null, 'outside-pie tap must clear selection')
page.data.distributionHasData = false
const patchCount = patches.length
tap(150, 120)
assert.equal(patches.length, patchCount, 'empty chart must not open details')

console.log('Pomodoro stats detail popup regression checks passed')
