const fs = require('node:fs')
const path = require('node:path')
const assert = require('node:assert/strict')
const { test } = require('node:test')
const { PAGE, tokens, pageViolations, moduleViolations, scanStats } = require('../scripts/architecture/pomodoro-stats-boundaries')
const source = fs.readFileSync(path.join(__dirname, '../..', PAGE), 'utf8')

test('stats entry and six responsibility modules satisfy the registered boundary', () => {
  assert.deepEqual(scanStats(), { errors: [], modules: 6, pageProperties: 115 })
})

test('page config rejects unknown, duplicate, nested, aliased and spread properties', () => {
  for (const addition of ['extra() {},', 'noop() {},', 'extra: () => {},', '...other,', 'extra,']) {
    assert.notEqual(pageViolations(source.replace('var pageConfig = {', 'var pageConfig = {' + addition)).length, 0)
  }
  assert.notEqual(pageViolations(source.replace('noop() {},', 'nested: { noop() {} },')).length, 0)
})

test('stats checks direct config declaration and registration without rejecting the original conditional registration', () => {
  assert.deepEqual(pageViolations(source), [])
  assert.notEqual(pageViolations(source + '\nPage({})').length, 0)
  assert.notEqual(pageViolations(source.replace('Page(pageConfig)', 'Page({})')).length, 0)
  assert.notEqual(pageViolations(source.replace('var pageConfig = {', 'var pageConfig = unknown; var other = {')).length, 0)
})

test('page detects data defaults, async, return and dependency getter drift', () => {
  for (const [oldText, newText] of [
    ["themeMode: 'light'", "themeMode: 'dark'"],
    ['async _init()', '_init()'],
    ['return loadViewFlow.', 'loadViewFlow.'],
    ['getPlatform: () => wx', 'getPlatform: () => ({})'],
  ]) {
    assert.ok(source.includes(oldText))
    assert.notEqual(pageViolations(source.replace(oldText, newText)).length, 0)
  }
})

test('module binding checks retain const, exact require path and unique declaration', () => {
  const original = "const lifecyclePage = require('./stats-lifecycle-page-adapter')"
  for (const replacement of [
    "const lifecyclePage = require('./stats-date-page-adapter')",
    'const lifecyclePage = {}',
    "let lifecyclePage = require('./stats-lifecycle-page-adapter')",
    '', original + '\n' + original,
  ]) assert.notEqual(pageViolations(source.replace(original, replacement)).length, 0)
})

test('module dependency boundaries reject imports, platform globals and dynamic evaluation', () => {
  for (const text of [
    "require('./api')", "import('./api')", "import api from './api'",
    "export { api } from './api'", 'wx.showToast({})', 'globalThis.wx',
    'eval("1")', 'new Function("return 1")',
  ]) assert.notEqual(moduleViolations(text, 'fixture.js').length, 0, text)
  assert.deepEqual(moduleViolations('function load({ getPlatform }) { return getPlatform().getStorageSync("user") }', 'fixture.js'), [])
})

test('token templates retain literal whitespace while allowing formatting changes', () => {
  assert.equal(tokens('return value'), tokens('return   value'))
  assert.notEqual(tokens("'a b'"), tokens("'ab'"))
  assert.deepEqual(pageViolations(source.replace('loading: true', 'loading:   true')), [])
})

test('page registration condition and standalone duration export retain their original statements', () => {
  for (const [oldText, newText] of [
    ["if (typeof Page === 'function') Page(pageConfig)", 'false && Page(pageConfig)'],
    ["if (typeof Page === 'function')", "if (typeof Page === 'undefined')"],
    ['formatDuration: durationFormatter.formatDuration', 'formatDuration: () => 0'],
    ["typeof module !== 'undefined' && module.exports", 'false'],
  ]) {
    assert.ok(source.includes(oldText))
    assert.notEqual(pageViolations(source.replace(oldText, newText)).length, 0)
  }
})
