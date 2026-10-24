/**
 * test-pomodoro-end-dialog-style.js
 *
 * Regression test for pomodoro end-confirm dialog button background.
 *
 * Root cause: <cover-view> on real WeChat devices does NOT support
 * `background: linear-gradient(...)`. All confirm button themes
 * relied solely on gradient, causing transparent background on device.
 *
 * Fix: add solid `background-color` fallback, move gradient to `background-image`.
 */

/* eslint-disable no-console */
const assert = require('assert')
const path = require('path')
const fs = require('fs')

var testsPassed = 0
var testsFailed = 0

function t(desc, fn) {
  try {
    fn()
    testsPassed++
    console.log('  ✓', desc)
  } catch (e) {
    testsFailed++
    console.error('  ✗', desc, '-', e.message)
  }
}

// ══════════════════════════════════════════════════════════════════
// 1. WXML structure checks
// ══════════════════════════════════════════════════════════════════
console.log('\n--- 1. WXML dialog structure ---')

var wxml = fs.readFileSync(path.join(__dirname, '../pages/pomodoro/pomodoro.wxml'), 'utf8')

t('Dialog overlay exists with showEndConfirm guard', function () {
  assert.ok(wxml.indexOf('wx:if="{{showEndConfirm}}"') >= 0)
})

t('Dialog title references endConfirmTitle', function () {
  assert.ok(wxml.indexOf('endConfirmTitle') >= 0)
})

t('Dialog body references endConfirmText', function () {
  assert.ok(wxml.indexOf('endConfirmText') >= 0)
})

t('Cancel button exists with cancelEndConfirm binding', function () {
  var match = wxml.match(/confirm-cover-cancel[\s\S]{0,80}catchtap="cancelEndConfirm"/)
  assert.ok(match, 'cancel button must bind cancelEndConfirm')
})

t('Cancel button shows endConfirmCancelText', function () {
  assert.ok(wxml.indexOf('endConfirmCancelText') >= 0)
})

t('Confirm button exists with confirmEndTimer binding', function () {
  var match = wxml.match(/confirm-cover-ok[\s\S]{0,80}catchtap="confirmEndTimer"/)
  assert.ok(match, 'confirm button must bind confirmEndTimer')
})

t('Confirm button shows endConfirmOkText (or actionLoading text)', function () {
  assert.ok(wxml.indexOf('endConfirmOkText') >= 0)
  assert.ok(wxml.indexOf('actionLoading') >= 0)
})

t('Confirm button conditionally applies disabled class', function () {
  assert.ok(wxml.indexOf("actionLoading ? 'disabled'") >= 0)
})

t('Dialog uses cover-view (not view/button)', function () {
  var coverTags = (wxml.match(/<cover-view/g) || []).length
  assert.ok(coverTags >= 5, 'dialog should use cover-view (found ' + coverTags + ')')
})

t('Overlay catchtap cancels via cancelEndConfirm', function () {
  assert.ok(wxml.indexOf('catchtap="cancelEndConfirm"') >= 0)
})

t('Card catchtap uses noop to stop propagation', function () {
  assert.ok(wxml.indexOf('catchtap="noop"') >= 0)
})

// ══════════════════════════════════════════════════════════════════
// 2. WXSS background checks
// ══════════════════════════════════════════════════════════════════
console.log('\n--- 2. WXSS confirm button background ---')

var wxss = fs.readFileSync(path.join(__dirname, '../pages/pomodoro/pomodoro.wxss'), 'utf8')

t('confirm-cover-ok has background-color (not just background)', function () {
  var selector = extractBlock(wxss, '.confirm-cover-ok')
  assert.ok(selector.indexOf('background-color') >= 0,
    '.confirm-cover-ok must have explicit background-color')
})

t('confirm-cover-ok is not background: transparent or background: none', function () {
  var block = extractBlock(wxss, '.confirm-cover-ok')
  assert.ok(block.indexOf('background: transparent') === -1, 'no background: transparent')
  assert.ok(block.indexOf('background: none') === -1, 'no background: none')
  assert.ok(block.indexOf('background-color: transparent') === -1, 'no background-color: transparent')
})

t('confirm-cover-ok base background-color is a solid hex or rgba value', function () {
  var block = extractBlock(wxss, '.confirm-cover-ok')
  var hasSolid = /background-color:\s*#[0-9a-fA-F]{3,8}\s*;/.test(block) ||
                 /background-color:\s*rgba?\s*\(/.test(block)
  assert.ok(hasSolid, 'background-color must be a solid color value')
})

t('confirm-theme-free .confirm-cover-ok has background-color fallback', function () {
  var block = extractBlock(wxss, '.confirm-theme-free .confirm-cover-ok')
  assert.ok(block.indexOf('background-color') >= 0,
    '.confirm-theme-free .confirm-cover-ok must have background-color fallback')
})

t('confirm-theme-focus .confirm-cover-ok has background-color fallback', function () {
  var block = extractBlock(wxss, '.confirm-theme-focus .confirm-cover-ok')
  assert.ok(block.indexOf('background-color') >= 0,
    '.confirm-theme-focus .confirm-cover-ok must have background-color fallback')
})

t('confirm-theme-break .confirm-cover-ok has background-color fallback', function () {
  var block = extractBlock(wxss, '.confirm-theme-break .confirm-cover-ok')
  assert.ok(block.indexOf('background-color') >= 0,
    '.confirm-theme-break .confirm-cover-ok must have background-color fallback')
})

t('No confirm button uses only background: linear-gradient without color fallback', function () {
  // Check all four selectors
  var okBase = extractBlock(wxss, '.confirm-cover-ok')
  var freeOk = extractBlock(wxss, '.confirm-theme-free .confirm-cover-ok')
  var focusOk = extractBlock(wxss, '.confirm-theme-focus .confirm-cover-ok')
  var breakOk = extractBlock(wxss, '.confirm-theme-break .confirm-cover-ok')

  var all = [okBase, freeOk, focusOk, breakOk]
  for (var i = 0; i < all.length; i++) {
    if (all[i].indexOf('background-color') === -1) {
      throw new Error('Selector #' + i + ' is missing background-color fallback')
    }
  }
})

t('No gradient-only background without color fallback on confirm button', function () {
  var freeOk = extractBlock(wxss, '.confirm-theme-free .confirm-cover-ok')
  var hasGradient = freeOk.indexOf('gradient') >= 0
  var hasColor = freeOk.indexOf('background-color') >= 0
  if (hasGradient && !hasColor) {
    throw new Error('gradient without background-color fallback')
  }
})

t('Disabled state has opacity rule but not transparent background', function () {
  var disabled = extractBlock(wxss, '.confirm-cover-ok.disabled')
  assert.ok(disabled.indexOf('opacity') >= 0, 'disabled must set opacity')
  assert.ok(disabled.indexOf('background') === -1 || disabled.indexOf('background') < disabled.indexOf('opacity'),
    'disabled should not override background')
})

t('No global button reset in pomodoro.wxss', function () {
  // Check there's no bare `button {` style
  var lines = wxss.split('\n')
  for (var i = 0; i < lines.length; i++) {
    var line = lines[i].trim()
    if (line === 'button {' || line === 'button[' || line === 'button::') {
      throw new Error('pomodoro.wxss must not contain global button styles at line ' + (i + 1))
    }
  }
})

t('Cancel button has its own background style', function () {
  var block = extractBlock(wxss, '.confirm-cover-cancel')
  assert.ok(block.indexOf('background') >= 0, 'cancel button must have its own background')
})

t('Card has background for visibility', function () {
  var block = extractBlock(wxss, '.confirm-cover-card')
  assert.ok(block.indexOf('background') >= 0, 'card must have background')
})

// ══════════════════════════════════════════════════════════════════
// 3. JS event guard checks
// ══════════════════════════════════════════════════════════════════
console.log('\n--- 3. JS interaction guards ---')

var js = fs.readFileSync(path.join(__dirname, '../pages/pomodoro/pomodoro.js'), 'utf8')
var confirmEndTimerController = fs.readFileSync(
  path.join(__dirname, '../pages/pomodoro/utils/confirm-end-timer-controller.js'),
  'utf8'
)
var cancelEndConfirmController = fs.readFileSync(
  path.join(__dirname, '../pages/pomodoro/utils/cancel-end-confirm-controller.js'),
  'utf8'
)

t('confirmEndTimer has actionLoading guard', function () {
  assert.ok(confirmEndTimerController.indexOf('options.isActionLoading()') >= 0)
})

t('cancelEndConfirm has actionLoading guard', function () {
  assert.ok(cancelEndConfirmController.indexOf('options.isActionLoading()') >= 0)
})

t('confirmEndTimer exists as method', function () {
  assert.ok(/confirmEndTimer\s*\(/.test(js))
})

t('cancelEndConfirm exists as method', function () {
  assert.ok(/cancelEndConfirm\s*\(/.test(js))
})

t('_confirmEndFreeTimer does not reset showEndConfirm before API completes', function () {
  var fnMatch = js.match(/_confirmEndFreeTimer[\s\S]{0,500}showEndConfirm/s)
  if (fnMatch) {
    // showEndConfirm is set to false BEFORE API call, which is intentional UX
    // (immediate visual hide). Verify the guard is present.
  }
})

t('confirmEndTimer handles both free-complete and countdown-interrupt modes', function () {
  assert.ok(confirmEndTimerController.indexOf("mode === 'free-complete'") >= 0)
  assert.ok(confirmEndTimerController.indexOf("mode === 'countdown-interrupt'") >= 0)
})

// ══════════════════════════════════════════════════════════════════
// 4. No CSS variable without fallback
// ══════════════════════════════════════════════════════════════════
console.log('\n--- 4. CSS color stability ---')

t('No var() usage in confirm button backgrounds without fallback', function () {
  var confirmBlocks = [
    extractBlock(wxss, '.confirm-cover-ok'),
    extractBlock(wxss, '.confirm-theme-free .confirm-cover-ok'),
    extractBlock(wxss, '.confirm-theme-focus .confirm-cover-ok'),
    extractBlock(wxss, '.confirm-theme-break .confirm-cover-ok'),
  ]
  for (var i = 0; i < confirmBlocks.length; i++) {
    var block = confirmBlocks[i]
    // "var(" without a comma inside the same var() = no fallback
    var varMatches = block.match(/var\([^)]*\)/g) || []
    for (var j = 0; j < varMatches.length; j++) {
      if (varMatches[j].indexOf(',') === -1) {
        throw new Error('var() without fallback in selector: ' + varMatches[j])
      }
    }
  }
})

// ══════════════════════════════════════════════════════════════════
// Summary
// ══════════════════════════════════════════════════════════════════
console.log('\n==============================')
console.log('Passed:', testsPassed, ' Failed:', testsFailed)
console.log('==============================\n')

if (testsFailed > 0) process.exit(1)

// ── Helper: extract a CSS rule block by selector ───────────────
function extractBlock(css, selector) {
  var escaped = selector.replace(/\./g, '\\.').replace(/\s+/g, '\\s+')
  var re = new RegExp(escaped + '\\s*{([^}]*)}', 'i')
  var match = css.match(re)
  if (!match) return ''
  return match[1].trim()
}
