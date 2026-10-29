const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { test } = require('node:test')
const {
  DIRECTORY, MODULES, DELEGATES, PAGE_METHODS, PAGE_CEILING, pageViolations, moduleViolations, scanWrongBook,
} = require('../scripts/architecture/wrong-book-boundaries')

const root = path.resolve(__dirname, '../..')
const page = fs.readFileSync(path.join(root,
  'miniprogram/subpackages/study/wrong-book/wrong-book.js'), 'utf8')
const modules = Object.fromEntries(MODULES.map(name =>
  [name, fs.readFileSync(path.join(root, DIRECTORY, name), 'utf8')]))

test('wrong-book page and fifteen modules stay bounded', () => {
  const result = scanWrongBook()
  assert.deepEqual(result.errors, [])
  assert.equal(result.pageLines, PAGE_CEILING)
  assert.equal(result.modules, 15)
  assert.equal(result.delegates, 112)
  assert.equal(result.pageMethods, 114)
})

test('all moved methods must preserve their parameter and delegation contracts', () => {
  assert.equal(Object.keys(DELEGATES).length, 112)
  for (const [name, template] of Object.entries(PAGE_METHODS)) {
    assert.ok(page.includes(template), name)
    assert.ok(pageViolations(page.replaceAll(template, `${name}() { return null }`))
      .includes(`delegate drift: ${name}`), name)
  }
})

test('page gate rejects new methods, accessors, callable aliases and spreads', () => {
  for (const [extra, error] of [
    ['unexpected() {},', 'unregistered page method: unexpected'],
    ['unexpected: () => {},', 'page field drift: unexpected'],
    ['unexpected: function () {},', 'page field drift: unexpected'],
    ['unexpected: existingFunction,', 'page field drift: unexpected'],
    ['unexpected,', 'unregistered page property: unexpected'],
    ['get unexpected() { return 1 },', 'unregistered page property: unexpected'],
    ['set unexpected(value) {},', 'unregistered page property: unexpected'],
    ['...extraMethods,', 'unregistered page spread'],
  ]) assert.ok(pageViolations(page.replace('Page({', `Page({${extra}`)).includes(error), extra)
})

test('page gate validates state defaults, declaration shape and original method occurrence counts', () => {
  assert.ok(pageViolations(page.replace('_ready: false', '_ready: existingFunction'))
    .includes('page field drift: _ready'))
  assert.ok(pageViolations(page.replace('_ready: false,', ''))
    .includes('missing page field: _ready'))
  assert.ok(pageViolations(page.replace('data: {', 'data: existingData, ignored: {'))
    .includes('page data drift'))
  assert.ok(pageViolations(page + '\nPage({})').includes('page declaration'))
  assert.ok(pageViolations(page.replace('Page({', 'Page({noop() {},'))
    .includes('page method count: noop'))
  assert.ok(pageViolations(page.replace('noop() {},', ''))
    .includes('page method count: noop'))
  assert.ok(pageViolations(page.replace('noop() {},', 'noop() { this.loadList(true) },'))
    .includes('delegate drift: noop'))
})

test('a nested method cannot hide drift in a registered page entry', () => {
  const template = DELEGATES._hasFilters
  const mutated = page.replace(template, '_hasFilters() { return null }')
    .replace('data: {', `data: { nested: { ${template} },`)
  assert.ok(pageViolations(mutated).includes('delegate drift: _hasFilters'))
})

test('page cannot grow or lose one of its module imports', () => {
  assert.ok(pageViolations(page + '\nvoid 0\n'.repeat(PAGE_CEILING)).includes('page budget'))
  const mutated = page.replace("require('./utils/wrong-book-item-view')", "require('./other')")
  assert.ok(pageViolations(mutated).includes('page import: wrong-book-item-view.js'))
})

test('view modules reject platform and network dependencies and dynamic code', () => {
  const name = MODULES[0]
  for (const added of [
    "require('../../../../utils/api')", 'require(variable)',
    "import('remote')", "eval('1')", "Function('return 1')",
    "new Function('return 1')", "new Function('return wx')()",
    'wx.showToast({})', 'api.get("/")', 'storage.get("key")', 'Page({})',
    'function run() { return this.data }',
  ]) {
    assert.ok(moduleViolations(name, modules[name] + '\n' + added).length, added)
  }
})

test('module gate rejects oversized files and functions and invalid JavaScript', () => {
  const name = MODULES[0]
  for (const source of [
    'void 0\n'.repeat(301),
    'function large() {\n' + 'void 0\n'.repeat(49) + '}\n',
    'const value: string = "invalid JavaScript"',
  ]) assert.ok(moduleViolations(name, source).length)
})

test('new or missing projection modules cannot escape registration', () => {
  assert.ok(scanWrongBook({ modules: { ...modules, 'extra.js': 'void 0' } }).errors
    .includes('unregistered module: extra.js'))
  const missing = { ...modules }
  delete missing[MODULES[0]]
  assert.ok(scanWrongBook({ modules: missing }).errors.includes(`missing module: ${MODULES[0]}`))
})
