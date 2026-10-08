// Run: node miniprogram/tests/test-pomodoro-timer-shimmer.js
// Static style contracts; simulator/device animation rendering still needs verification.
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const root = path.join(__dirname, '../pages/pomodoro')
const css = fs.readFileSync(path.join(root, 'pomodoro.wxss'), 'utf8')
const template = fs.readFileSync(path.join(root, 'pomodoro.wxml'), 'utf8')
const rules = Array.from(css.replace(/\/\*[\s\S]*?\*\//g, '').matchAll(/([^{}]+)\{([^{}]*)\}/g))
function bodies(selector) {
  return rules.filter(([, selectors]) => selectors.split(',').map(s => s.trim()).includes(selector)).map(([, , body]) => body)
}
assert.match(template, /ring-time-free \{\{isPaused/)
assert.match(template, /ring-time-timed \{\{isPaused/)
assert.match(template, /\{\{displayMin\}\}:\{\{displaySec\}\}/)
const shared = bodies('.ring-time-timed')[0]
assert.match(shared, /animation: free-shimmer 4s linear infinite/)
assert.match(shared, /background-size: 200% 100%/)
assert.match(shared, /background-clip: text/)
assert.doesNotMatch(shared, /font-size|font-weight|letter-spacing|(?:^|;)\s*color:/)
assert.match(bodies('.ring-time-timed')[0], /linear-gradient\(90deg, currentColor/)
assert.doesNotMatch(bodies('.ring-time-timed')[0], /#[\da-f]+|font-size|font-weight/i)
assert.match(bodies('.ring-time-timed')[0], /currentColor 35%, var\(--timer-shimmer-highlight, currentColor\) 47%, var\(--timer-shimmer-highlight, currentColor\) 53%, currentColor 65%/)
const palettes = [
  ['.theme-light.page-focus .ring-time', '#168CB8', '#67D8F1'],
  ['.theme-dark.page-focus .ring-time', '#72DDF2', '#D0F8FF'],
  ['.theme-light.page-break .ring-time', '#C66A1B', '#F5BA70'],
  ['.theme-dark.page-break .ring-time', '#F8B96B', '#FFE6C5'],
]
for (const [selector, color, highlight] of palettes) {
  const body = bodies(selector)[0]
  assert(body.includes(`color: ${color};`), `${selector} keeps original color`)
  assert(bodies(selector + '-timed')[0].includes(`--timer-shimmer-highlight: ${highlight};`), `${selector} uses a visible same-hue highlight`)
}
assert.match(bodies('.ring-time-free')[0], /#6EE7B7 0%, #34D399 25%, #10B981 50%, #059669 75%, #34D399 100%/)
assert.match(bodies('.ring-time-timed.time-dim')[0], /animation: none/)
assert.match(bodies('.ring-time-free.time-dim')[0], /opacity: 0.45/)
const reduced = css.slice(css.lastIndexOf('@media (prefers-reduced-motion: reduce)'))
assert.match(reduced, /\.ring-time-timed[\s\S]*animation: none !important/)
assert.match(reduced, /\.ring-time-timed[\s\S]*-webkit-text-fill-color: currentColor/)
assert.equal((css.match(/@keyframes free-shimmer/g) || []).length, 1)
console.log('Pomodoro countdown shimmer/color and unchanged free timer regression passed')

// Guard the full free-timer template and style blocks against accidental edits.
const { execFileSync } = require('node:child_process')
const originalCss = execFileSync('git', ['show', 'HEAD:miniprogram/pages/pomodoro/pomodoro.wxss'], { encoding: 'utf8', cwd: path.join(__dirname, '../..') })
const originalTemplate = execFileSync('git', ['show', 'HEAD:miniprogram/pages/pomodoro/pomodoro.wxml'], { encoding: 'utf8', cwd: path.join(__dirname, '../..') })
for (const selector of ['.ring-time-free', '.ring-time-free.time-dim']) {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const pattern = new RegExp(escaped + '\\s*\\{[^}]*\\}')
  assert.equal(css.match(pattern)[0], originalCss.match(pattern)[0], selector + ' remains byte-identical')
}
const freeText = /<text class="ring-time ring-time-free[^>]*>[\s\S]*?<\/text>/
assert.equal(template.match(freeText)[0], originalTemplate.match(freeText)[0])
