const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { test } = require('node:test')
const {
  moduleViolations, pageViolations, scanPomodoro, MODULES, PAGE_MAX_LINES,
} = require('../scripts/architecture/pomodoro-boundaries')

const root = path.resolve(__dirname, '../..')
const pageSource = fs.readFileSync(path.join(root, 'miniprogram/pages/pomodoro/pomodoro.js'), 'utf8')
const check = (source, allowed = []) => moduleViolations('fixture.js', source, allowed).errors

test('scans every governed production module and real page', () => {
  const result = scanPomodoro()
  assert.deepEqual(result.violations, [])
  assert.equal(result.modules, 14)
  assert.equal(result.edges, 1)
})

test('dependency injection examples cannot import page, API, storage or another package', () => {
  for (const dependency of ['../pomodoro', '../../../utils/api', '../../../utils/storage',
    '../../../subpackages/study/practice/practice', './show-recovery', 'node:fs']) {
    assert.ok(check(`const forbidden = require('${dependency}')`).some(error =>
      error === `forbidden dependency: ${dependency}`))
  }
})

test('literal require edge is accepted only for its owning module policy', () => {
  const source = "const { formatElapsedSec } = require('./timer-math'); module.exports = { formatElapsedSec }"
  assert.deepEqual(check(source, MODULES['confirm-recovery.js']), [])
  assert.ok(check(source, MODULES['show-recovery.js']).length > 0)
})

test('rejects require aliases, computed targets and dynamic imports', () => {
  for (const source of [
    'const load = require; load(target)',
    'require(target)',
    "require('./' + target)",
    "require(`./timer-math`)",
    "require.call(null, './timer-math')",
    "import('./timer-math')",
    "import { x } from './timer-math'",
    "export { x } from './timer-math'",
    'export default value',
    'export function x() {}',
    'export const x = 1',
  ]) assert.ok(check(source).length > 0, source)
})

test('detects global capabilities inside nested functions and computed accesses', () => {
  for (const source of [
    "function retry() { return () => wx.request({}) }",
    "const host = wx; host['request']({})",
    'Page({})', 'getApp()', 'getCurrentPages()', 'api.post()',
    'globalThis.wx', "global['wx']", 'window.fetch(url)', "self['wx']", 'process.env', 'new Date()', 'Date.now()',
    'setTimeout(fn, 2000)', 'clearInterval(timer)', 'fetch(url)',
    "eval('value')", "new Function('return value')", 'exports.retry = value',
    'const owner = module', 'const retry = () => this.retry()',
  ]) assert.ok(check(source).length > 0, source)
})

test('ignores words in comments and strings and permits explicit capability callbacks', () => {
  assert.deepEqual(check(`
    // wx.request and require('../pomodoro') are intentionally only examples.
    const message = 'Page and setTimeout are not runtime accesses here'
    function schedule(options) {
      options.setTimeout(() => options.retry(), 2000)
      options.clearTimeout(options.timer)
      return message
    }
    module.exports = { schedule }
  `), [])
})

test('rejects invalid and empty source rather than silently scanning zero nodes', () => {
  for (const source of ['', '  \n ', '// comments only', 'function broken( {']) {
    assert.ok(check(source).length > 0)
    assert.ok(pageViolations(source).length > 0)
  }
})

test('checks all nested function forms against 50-line budget', () => {
  const body = Array(50).fill('void 0').join('\n')
  for (const source of [
    `function long() {\n${body}\n}`,
    `const long = () => {\n${body}\n}`,
    `const long = function() {\n${body}\n}`,
    `const owner = { long() {\n${body}\n} }`,
    `function outer() { return () => {\n${body}\n} }`,
    `class Owner { get value() {\n${body}\n} }`,
  ]) assert.ok(check(source).some(error => error.startsWith('function exceeds 50 lines')), source)
})

test('checks 300-line module budget independently of function length', () => {
  assert.ok(check(Array(301).fill('void 0').join('\n')).includes('module exceeds 300 lines'))
  assert.ok(!check(Array(300).fill('void 0').join('\n')).includes('module exceeds 300 lines'))
})

test('page cannot exceed current legacy ceiling or regrow governed lifecycle methods', () => {
  assert.ok(pageViolations(Array(PAGE_MAX_LINES + 1).fill('// legacy').join('\n'))
    .includes(`page exceeds legacy ceiling ${PAGE_MAX_LINES}`))
  const expanded = pageSource.replace('  async onShow() {',
    `  async onShow() {\n${Array(51).fill('    void 0').join('\n')}`)
  assert.ok(pageViolations(expanded).some(error => error.startsWith('function exceeds 50 lines')))
})

test('page must still import the isolated modules and keep the governed lifecycle entry', () => {
  const detached = pageSource.replace("require('./utils/show-recovery')", "require('./utils/legacy-recovery')")
  assert.ok(pageViolations(detached).includes('page no longer imports governed module: show-recovery.js'))
  const missing = pageSource.replace('  async onShow() {', '  async removedOnShow() {')
  assert.ok(pageViolations(missing).includes('missing governed method: onShow'))
  const fake = `${missing}\nconst fake = { async onShow() {} }\n`
  assert.ok(pageViolations(fake).includes('missing governed method: onShow'))
  assert.ok(pageViolations(`${pageSource}\nPage({})\n`)
    .includes('expected exactly one literal Page definition'))
})

test('missing governed source aborts the scan instead of reducing coverage', () => {
  assert.throws(() => scanPomodoro(root, filename => {
    if (filename.endsWith('/show-recovery.js')) throw new Error('synthetic missing source')
    return fs.readFileSync(filename, 'utf8')
  }), /synthetic missing source/)
})

test('full scan finds an injected reverse dependency and an emptied module', () => {
  for (const injected of ["require('../pomodoro')", '']) {
    const result = scanPomodoro(root, filename => filename.endsWith('/show-recovery.js')
      ? injected : fs.readFileSync(filename, 'utf8'))
    assert.ok(result.violations.some(error => error.includes('show-recovery.js')))
    assert.equal(result.modules, 14)
  }
})
