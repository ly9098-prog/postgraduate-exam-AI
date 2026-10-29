const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { test } = require('node:test')
const {
  PAGE, DIRECTORY, MODULES, DELEGATES, PAGE_CEILING, pageViolations,
  moduleViolations, teacherPortViolations, scanWrongDetail,
} = require('../scripts/architecture/wrong-detail-boundaries')

const root = path.resolve(__dirname, '../..')
const page = fs.readFileSync(path.join(root, PAGE), 'utf8')
const modules = Object.fromEntries(MODULES.map(name =>
  [name, fs.readFileSync(path.join(root, DIRECTORY, name), 'utf8')]))

test('wrong-detail page and four modules preserve budgets and teacher ports', () => {
  const result = scanWrongDetail()
  assert.deepEqual(result.errors, [])
  assert.equal(result.pageLines, PAGE_CEILING)
  assert.equal(result.modules, 4)
  assert.equal(result.teacherPorts, 22)
})

test('page wrappers and lazy teacher assembly cannot drift', () => {
  for (const [name, expected] of Object.entries(DELEGATES)) {
    assert.ok(page.includes(expected), name)
    assert.ok(pageViolations(page.replace(expected, expected.replace('return ', 'throw ')))
      .includes(`delegate drift: ${name}`), name)
  }
})

test('moved AI helpers must stay imported and cannot return inline', () => {
  assert.ok(pageViolations(page + '\nfunction _fallbackMessage() {}')
    .includes('helper returned: _fallbackMessage'))
  assert.ok(pageViolations(page.replace(' } = aiState', ' } = otherState'))
    .includes('AI helper import drift'))
})

test('teacher port gate rejects missing and stale capability wiring', () => {
  const source = modules['wrong-detail-teacher-page-adapter.js']
  assert.deepEqual(teacherPortViolations(source), [])
  assert.ok(teacherPortViolations(source.replace('page._alive', 'true'))
    .includes('teacher port drift: isAlive'))
  assert.ok(teacherPortViolations(source.replace('getWq:', 'getOldWq:'))
    .includes('teacher port keys drift'))
})

test('modules reject direct network or platform dependencies and dynamic execution', () => {
  const name = 'wrong-detail-ai-state.js'
  for (const added of [
    "require('../../../../utils/api')", 'require(variable)', "import('remote')",
    "eval('1')", "new Function('return 1')", "Function('return wx')()",
    'wx.showToast({})', 'api.get("/")', 'storage.get("key")',
    'function run() { return this.data }',
  ]) assert.ok(moduleViolations(name, modules[name] + '\n' + added).length, added)
})

test('page and module budget growth and invalid JavaScript are rejected', () => {
  assert.ok(pageViolations(page + '\nvoid 0\n'.repeat(PAGE_CEILING)).includes('page budget'))
  for (const source of [
    'void 0\n'.repeat(301),
    'function large() {\n' + 'void 0\n'.repeat(49) + '}\n',
    'const value: string = "invalid JavaScript"',
  ]) assert.ok(moduleViolations('wrong-detail-ai-state.js', source).length)
})

test('new missing or disconnected modules cannot escape the gate', () => {
  assert.ok(scanWrongDetail({ modules: { ...modules, 'extra.js': 'void 0' } }).errors
    .includes('unregistered module: extra.js'))
  const missing = { ...modules }
  delete missing[MODULES[0]]
  assert.ok(scanWrongDetail({ modules: missing }).errors.includes(`missing module: ${MODULES[0]}`))
  const changed = page.replace("require('./utils/wrong-detail-ai-state')", "require('./other')")
  assert.ok(pageViolations(changed).includes('page import: wrong-detail-ai-state.js'))
})
