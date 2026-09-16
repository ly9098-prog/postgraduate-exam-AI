/**
 * v9 targeted regression checks:
 * - KaTeX span-compat classes restore fraction / limit / vertical-list layout
 * - formula mixed-content normalization still emits correct LaTeX
 * - Pomodoro free timer restores its original fluorescent gradient text
 * - obsolete CSS replacement-ring code is gone
 * - formula reader has one bottom spacer with enough fixed-nav clearance
 */
/* eslint-disable no-console */
const assert = require('assert')
const fs = require('fs')
const path = require('path')

function source(rel) {
  return fs.readFileSync(path.resolve(__dirname, '..', rel), 'utf8')
}

global.wx = global.wx || {
  getWindowInfo() { return { windowWidth: 375, pixelRatio: 2 } },
  getDeviceInfo() { return { system: 'Node.js regression test' } },
}

const formulaContent = require('../subpackages/formulas/utils/formula-content')
const LatexPlugin = require('../subpackages/formulas/utils/katex/index')

// 1) The exact dirty/plain forms shown in the reader must normalize to real
// fraction/limit LaTeX rather than visual underscores or plain slash text.
assert.strictEqual(
  formulaContent.normalizeMixedContent('lim(x → 0)(sin x)/x = 1'),
  '$\\displaystyle \\lim_{x\\to 0}\\frac{\\sin x}{x}=1$',
)
assert.strictEqual(
  formulaContent.normalizeMixedContent('lim(x → 0)(sin 2x)/x = 2'),
  '$\\displaystyle \\lim_{x\\to 0}\\frac{\\sin 2x}{x}=2$',
)
assert.ok(formulaContent.normalizeMixedContent('(1 + 1/x)').includes('\\frac{1}{x}'))

// 2) Component-safe KaTeX CSS replaces `> span` with `> .katex-span`.
// Every parsed span underneath a KaTeX root therefore has to receive that
// compatibility class, otherwise vlist/mfrac/op-limits collapse on device.
const formulaNode = {
  type: 'text',
  text: '$\\displaystyle \\lim_{x\\to 0}\\frac{\\sin x}{x}=1$',
}
new LatexPlugin().onParse(formulaNode, {
  options: { editable: false },
  properties: { mathLayout: '' },
})

let katexSpanCount = 0
let unclassifiedKatexSpanCount = 0
let mfracCount = 0
let vlistCount = 0
let opLimitsCount = 0

function classList(node) {
  return String((node.attrs && node.attrs.class) || '').split(/\s+/).filter(Boolean)
}
function walk(node, inKatex = false) {
  if (Array.isArray(node)) {
    node.forEach((item) => walk(item, inKatex))
    return
  }
  if (!node || typeof node !== 'object') return
  const classes = classList(node)
  const nowInKatex = inKatex || classes.includes('katex')
  if (nowInKatex && node.name === 'span') {
    katexSpanCount += 1
    if (!classes.includes('katex-span')) unclassifiedKatexSpanCount += 1
  }
  if (classes.includes('mfrac')) mfracCount += 1
  if (classes.includes('vlist')) vlistCount += 1
  if (classes.includes('op-limits')) opLimitsCount += 1
  if (node.children) walk(node.children, nowInKatex)
}
walk(formulaNode)
assert.ok(katexSpanCount > 20, 'expected a non-trivial KaTeX span tree')
assert.strictEqual(unclassifiedKatexSpanCount, 0, 'every KaTeX span must carry katex-span')
assert.ok(mfracCount >= 1, 'fraction node must exist')
assert.ok(vlistCount >= 1, 'vertical-list node must exist')
assert.ok(opLimitsCount >= 1, 'limit operator node must exist')

const katexWxss = source('subpackages/formulas/utils/katex/katex.wxss')
assert.ok(katexWxss.includes('.katex .vlist > .katex-span'))
assert.ok(katexWxss.includes('.katex .mfrac > .katex-span > .katex-span'))

// Non-formula rich text should not be polluted with the compatibility class.
const Parser = require('../subpackages/formulas/utils/mp-html-parser')
const plainNodes = new Parser({ properties: {}, imgList: [], plugins: [] }).parse('<span class="plain-copy">hello</span>')
assert.ok(!String((plainNodes[0].attrs && plainNodes[0].attrs.class) || '').includes('katex-span'))

// 3) Free timing should keep the original emerald shimmer. v5's static text
// override and the abandoned CSS replacement rings must not reappear.
const pomodoroWxss = source('pages/pomodoro/pomodoro.wxss')
assert.ok(/\.ring-time-free\s*\{[\s\S]*?linear-gradient\(90deg,[\s\S]*?-webkit-text-fill-color:\s*transparent;[\s\S]*?animation:\s*free-shimmer/.test(pomodoroWxss))
assert.ok(!pomodoroWxss.includes('.free-ring-static'))
assert.ok(!pomodoroWxss.includes('.progress-ring-css'))
assert.ok(!pomodoroWxss.includes('.progress-ring-end-dot'))
assert.ok(/\.theme-light\.page-focus \.ring-time\s*\{[\s\S]*?color:\s*#168CB8;[\s\S]*?text-shadow:/.test(pomodoroWxss))
assert.ok(/\.theme-dark\.page-focus \.ring-time\s*\{[\s\S]*?color:\s*#72DDF2;[\s\S]*?text-shadow:/.test(pomodoroWxss))
assert.ok(/\.theme-light\.page-free \.ring-time-free\s*\{[\s\S]*?color:\s*#10B981;[\s\S]*?text-shadow:/.test(pomodoroWxss))
assert.ok(/\.theme-dark\.page-free \.ring-time-free\s*\{[\s\S]*?color:\s*#6EE7B7;[\s\S]*?text-shadow:/.test(pomodoroWxss))

// 4) Reader fixed navigation gets a single effective bottom spacer so the last
// content can scroll fully above the nav capsule.
const readerWxss = source('subpackages/formulas/reader/index.wxss')
assert.strictEqual((readerWxss.match(/\.fr-bottom-space\s*\{/g) || []).length, 1)
assert.ok(/\.fr-bottom-space\s*\{\s*height:\s*calc\(152rpx \+ env\(safe-area-inset-bottom\)\);\s*\}/.test(readerWxss))

console.log('v9 formula layout / pomodoro glow / dead-code cleanup checks passed')
