const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { test } = require('node:test')
const {
  DIRECTORY, MODULES, DELEGATES, PAGE_CEILING, pageViolations, moduleViolations, scanWrongBook,
} = require('../scripts/architecture/wrong-book-boundaries')

const root = path.resolve(__dirname, '../..')
const page = fs.readFileSync(path.join(root,
  'miniprogram/subpackages/study/wrong-book/wrong-book.js'), 'utf8')
const modules = Object.fromEntries(MODULES.map(name =>
  [name, fs.readFileSync(path.join(root, DIRECTORY, name), 'utf8')]))

test('wrong-book page and five modules stay bounded', () => {
  const result = scanWrongBook()
  assert.deepEqual(result.errors, [])
  assert.equal(result.pageLines, PAGE_CEILING)
  assert.equal(result.modules, 5)
  assert.equal(result.delegates, 33)
})

test('all moved methods must preserve their parameter and delegation contracts', () => {
  for (const [name, template] of Object.entries(DELEGATES)) {
    assert.ok(page.includes(template), name)
    assert.ok(pageViolations(page.replace(template, `${name}() { return null }`))
      .includes(`delegate drift: ${name}`), name)
  }
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
