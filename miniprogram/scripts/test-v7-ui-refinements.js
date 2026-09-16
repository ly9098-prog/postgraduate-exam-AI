/**
 * v7 targeted regression checks for timer dial / wrong-book capsule / pomodoro palette.
 * Static checks only; no WeChat runtime or backend required.
 */
/* eslint-disable no-console */
const assert = require('assert')
const fs = require('fs')
const path = require('path')

function source(rel) {
  return fs.readFileSync(path.resolve(__dirname, '..', rel), 'utf8')
}

function balancedBraces(text, label) {
  let depth = 0
  let inBlockComment = false
  let inString = null
  for (let i = 0; i < text.length; i += 1) {
    const c = text[i]
    const n = text[i + 1]
    if (inBlockComment) {
      if (c === '*' && n === '/') { inBlockComment = false; i += 1 }
      continue
    }
    if (!inString && c === '/' && n === '*') { inBlockComment = true; i += 1; continue }
    if (inString) {
      if (c === '\\') { i += 1; continue }
      if (c === inString) inString = null
      continue
    }
    if (c === '"' || c === "'") { inString = c; continue }
    if (c === '{') depth += 1
    if (c === '}') depth -= 1
    assert.ok(depth >= 0, `${label}: unexpected closing brace near ${i}`)
  }
  assert.strictEqual(depth, 0, `${label}: unbalanced braces`)
}

const pomodoroWxml = source('pages/pomodoro/pomodoro.wxml')
const pomodoroWxss = source('pages/pomodoro/pomodoro.wxss')
const wrongBookWxml = source('subpackages/study/wrong-book/wrong-book.wxml')
const wrongBookWxss = source('subpackages/study/wrong-book/wrong-book.wxss')

// 1) Running timer: v8 restores the original native Canvas dial. Text still
// lives in its own center layer, and the canvas is revealed only after paint.
assert.ok(pomodoroWxml.includes('class="ring-center"'))
assert.ok(pomodoroWxml.includes('{{displayMin}}:{{displaySec}}'))
assert.ok(pomodoroWxml.includes('id="progress-ring"'))
assert.ok(pomodoroWxml.includes('ring-canvas-ready'))
assert.ok(/\.ring-center\s*\{[\s\S]*?z-index:\s*3;[\s\S]*?pointer-events:\s*none;/.test(pomodoroWxss))
assert.ok(/\.ring-canvas\s*\{[\s\S]*?z-index:\s*1;/.test(pomodoroWxss))

// 2) Wrong-book overview remains the same 3-part capsule, but is materially shorter.
assert.strictEqual((wrongBookWxml.match(/class="overview-item"/g) || []).length, 3)
assert.ok(/\/\* v7: tighten the overview capsule[\s\S]*?\.overview-card\s*\{[\s\S]*?min-height:\s*126rpx;[\s\S]*?padding:\s*14rpx 12rpx;/.test(wrongBookWxss))
assert.ok(/\/\* v7: tighten the overview capsule[\s\S]*?\.overview-icon\s*\{[\s\S]*?width:\s*62rpx;[\s\S]*?height:\s*62rpx;/.test(wrongBookWxss))

// 3-4) Pomodoro selectors: both themes have explicit coherent palettes and
// task types are larger with clearer separation between decision groups.
assert.ok(/v7 visual polish[\s\S]*?\.subj-section\s*\{[\s\S]*?margin-bottom:\s*36rpx;/.test(pomodoroWxss))
assert.ok(/v7 visual polish[\s\S]*?\.task-type-section\s*\{[\s\S]*?margin-bottom:\s*40rpx;/.test(pomodoroWxss))
assert.ok(/v7 visual polish[\s\S]*?\.task-type-chip\s*\{[\s\S]*?height:\s*56rpx;[\s\S]*?font-size:\s*22rpx;/.test(pomodoroWxss))
assert.ok(/\.theme-light \.subj-icon-wrap\s*\{[\s\S]*?rgba\(244, 247, 241, \.98\)/.test(pomodoroWxss))
assert.ok(/\.theme-dark \.subj-icon-wrap\s*\{[\s\S]*?rgba\(31, 43, 66, \.96\)/.test(pomodoroWxss))
assert.ok(pomodoroWxss.includes('.theme-light .task-type-chip.active'))
assert.ok(pomodoroWxss.includes('.theme-dark .task-type-chip.active'))

balancedBraces(pomodoroWxss, 'pomodoro.wxss')
balancedBraces(wrongBookWxss, 'wrong-book.wxss')

console.log('v7 targeted UI regression checks passed')
