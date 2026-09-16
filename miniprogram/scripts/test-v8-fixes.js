/**
 * v8 targeted regression checks:
 * - formula rich-text nodes use WeChat's native {name, attrs, children} schema
 * - component WXSS contains no forbidden mp-html tag selector
 * - formula reader navigation guards against stale/double route completion
 * - Pomodoro uses the original Canvas 2D dial instead of the CSS substitute
 * - wrong-book overview uses locally bundled, web-sourced Lucide SVG icons
 */
/* eslint-disable no-console */
const assert = require('assert')
const fs = require('fs')
const path = require('path')

function source(rel) {
  return fs.readFileSync(path.resolve(__dirname, '..', rel), 'utf8')
}
function exists(rel) {
  return fs.existsSync(path.resolve(__dirname, '..', rel))
}

// mp-html parser reads platform information at require time.
global.wx = global.wx || {
  getWindowInfo() { return { windowWidth: 375, pixelRatio: 2 } },
  getDeviceInfo() { return { system: 'Node.js regression test' } },
}

// 1) Formula KaTeX output must be safe for native <rich-text>.
const LatexPlugin = require('../subpackages/formulas/utils/katex/index')
const formulaNode = { type: 'text', text: '行内 $\\frac{a}{b}$，块级 $$\\sqrt{x^2+1}$$' }
new LatexPlugin().onParse(formulaNode, {
  options: { editable: false },
  properties: { mathLayout: '' },
})

let elementCount = 0
function assertNativeRichTextTree(value, at = 'root') {
  if (Array.isArray(value)) {
    value.forEach((item, index) => assertNativeRichTextTree(item, `${at}[${index}]`))
    return
  }
  if (!value || typeof value !== 'object') return
  assert.ok(!Object.prototype.hasOwnProperty.call(value, 'attributes'), `${at} leaked KaTeX private attributes`)
  assert.ok(!Object.prototype.hasOwnProperty.call(value, 'classes'), `${at} leaked KaTeX private classes`)
  if (value.name) {
    elementCount += 1
    if (value.attrs !== undefined) {
      assert.strictEqual(typeof value.attrs, 'object', `${at}.attrs must be an object`)
      assert.ok(!Array.isArray(value.attrs), `${at}.attrs must not be an array`)
    }
  }
  if (value.children) assertNativeRichTextTree(value.children, `${at}.children`)
}
assertNativeRichTextTree(formulaNode)
assert.ok(elementCount > 3, 'expected rendered KaTeX element nodes')

const cardWxss = source('subpackages/formulas/components/formula-card/index.wxss')
assert.ok(!/(^|[,\s>+~])mp-html(?=[\s.{:#>+~[,]|$)/m.test(cardWxss), 'component WXSS must not use mp-html tag selectors')

const readerJs = source('subpackages/formulas/reader/index.js')
assert.ok(readerJs.includes('if (this._navigatingBack) return'), 'reader must debounce back navigation')
assert.ok(readerJs.includes('this._readerAlive = false'), 'reader must mark itself inactive on unload')
assert.ok(readerJs.includes('if (!this._readerAlive) return'), 'reader must guard late async/timer callbacks')

// 2) Pomodoro dial: original native Canvas renderer must be the active path.
const pomodoroJs = source('pages/pomodoro/pomodoro.js')
const pomodoroWxml = source('pages/pomodoro/pomodoro.wxml')
assert.ok(!pomodoroJs.includes('USE_CSS_RING'), 'superseded CSS renderer flag must be removed')
assert.ok(pomodoroWxml.includes('type="2d"'))
assert.ok(pomodoroWxml.includes('id="progress-ring"'))
assert.ok(!pomodoroWxml.includes('class="progress-ring-css"'), 'CSS replacement ring must not be mounted')
assert.ok(!pomodoroWxml.includes('class="free-ring-static"'), 'static free ring must not replace original Canvas')
assert.ok(/lineWidth\s*=\s*12/.test(pomodoroJs), 'original thick progress stroke must be preserved')
assert.ok(/lineWidth\s*\+\s*14/.test(pomodoroJs), 'original progress glow must be preserved')
assert.ok(pomodoroJs.includes('createLinearGradient'), 'original gradient progress paint must be preserved')

// 3) Wrong-book overview icon replacement is local/offline-safe and attributed.
const wrongWxml = source('subpackages/study/wrong-book/wrong-book.wxml')
const iconFiles = [
  'assets/icons/wrong-book/notebook-text.svg',
  'assets/icons/wrong-book/badge-check.svg',
  'assets/icons/wrong-book/chart-increasing.svg',
]
iconFiles.forEach((rel) => {
  assert.ok(exists(rel), `missing icon ${rel}`)
  const svg = source(rel)
  assert.ok(/^<svg\b/.test(svg.trim()), `${rel} is not SVG`)
  assert.ok(svg.includes('viewBox="0 0 24 24"'), `${rel} must retain Lucide viewBox`)
})
assert.ok(exists('assets/icons/wrong-book/LICENSE-LUCIDE.txt'))
assert.ok(wrongWxml.includes('/assets/icons/wrong-book/notebook-text.svg'))
assert.ok(wrongWxml.includes('/assets/icons/wrong-book/badge-check.svg'))
assert.ok(wrongWxml.includes('/assets/icons/wrong-book/chart-increasing.svg'))

console.log('v8 formula / pomodoro / wrong-book targeted regression checks passed')
