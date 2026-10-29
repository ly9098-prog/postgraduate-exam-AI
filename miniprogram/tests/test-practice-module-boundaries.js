const fs = require('node:fs')
const path = require('node:path')
const assert = require('node:assert/strict')
const { test } = require('node:test')
const { PAGE, tokens, pageViolations, moduleViolations, scanPractice } = require('../scripts/architecture/practice-boundaries')
const source = fs.readFileSync(path.join(__dirname, '../..', PAGE), 'utf8')

test('practice page and six responsibility modules satisfy the registered boundary', () => {
  assert.deepEqual(scanPractice(), { errors: [], modules: 6, pageProperties: 113 })
})

test('page rejects unknown methods, duplicate overrides, aliases and spreads', () => {
  for (const addition of ['extra() {},', 'noop() {},', 'extra: () => {},', '...other,', 'extra,']) {
    assert.notEqual(pageViolations(source.replace('Page({', 'Page({' + addition)).length, 0)
  }
})

test('page checks actual direct declarations and cannot be satisfied by a nested method', () => {
  const changed = source.replace('noop() {},', 'nested: { noop() {} },')
  assert.notEqual(pageViolations(changed).length, 0)
  assert.notEqual(pageViolations(source + '\nPage({})').length, 0)
})

test('page detects dependency, state, return and async signature drift', () => {
  for (const [oldText, newText] of [
    ['getPlatform: () => wx', 'getPlatform: () => ({})'],
    ['_pageAlive: false', '_pageAlive: true'],
    ['return exitPage.', 'exitPage.'],
    ['async onReady()', 'onReady()'],
  ]) {
    assert.ok(source.includes(oldText))
    assert.notEqual(pageViolations(source.replace(oldText, newText)).length, 0)
  }
})

test('token comparison ignores formatting while retaining whitespace inside strings', () => {
  assert.equal(tokens('return value'), tokens('return   value'))
  assert.notEqual(tokens("'a b'"), tokens("'ab'"))
  assert.deepEqual(pageViolations(source.replace('_pageAlive: false', '_pageAlive:   false')), [])
})

test('page checks unique direct require bindings for all six responsibility modules', () => {
  const original = "const subjectPage = require('./utils/practice-subject-page-adapter')"
  for (const replacement of [
    "const subjectPage = require('./utils/practice-submit-page-adapter')",
    "const subjectPage = {}",
    "let subjectPage = require('./utils/practice-subject-page-adapter')",
    '',
    original + '\n' + original,
  ]) {
    assert.notEqual(pageViolations(source.replace(original, replacement)).length, 0)
  }
})

test('responsibility modules reject new imports, direct platform access and dynamic execution', () => {
  for (const text of [
    "require('./api')", "import('./api')", "import api from './api'",
    "export { api } from './api'", 'wx.showToast({})', 'globalThis.wx',
    'eval("1")', 'new Function("return 1")',
  ]) assert.notEqual(moduleViolations(text, 'fixture.js').length, 0, text)
  assert.deepEqual(moduleViolations('function load({ getPlatform }) { return getPlatform().getStorageSync("user") }', 'fixture.js'), [])
})
