/**
 * Client storage module boundaries.
 *
 * `utils/storage.js` stays the single aggregated namespace for pages,
 * controllers, subpackages and scripts. The modules behind it must keep the
 * 300/50 budgets, an explicit acyclic dependency graph and no way back into the
 * facade, the pages, the network layer or third-party code.
 *
 * Run: node --test tests/test-client-storage-boundaries.js
 */

const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { createRequire } = require('node:module')
const { test } = require('node:test')
const { inspectSource } = require('../scripts/architecture/learning-controller-budgets')

const MINI = path.resolve(__dirname, '..')
const UTILS = path.join(MINI, 'utils')
const ts = createRequire(path.resolve(MINI, '../admin-frontend/package.json'))('typescript')
const FACADE = 'storage.js'
const AGGREGATORS = ['storage.js', 'study-strategy.js']
const MODULES = {
  'storage-core.js': [],
  'study-strategy-meta.js': [],
  'pomodoro-task-types.js': ['./storage-core'],
  'knowledge-practice-sync.js': ['./storage-core'],
  'study-strategy-profile.js': ['./storage-core', './study-strategy-meta'],
  'study-strategy-plan.js': ['./study-strategy-meta', './study-strategy-profile'],
  'study-strategy.js': ['./study-strategy-meta', './study-strategy-profile', './study-strategy-plan'],
  'storage.js': ['./storage-core', './study-strategy', './pomodoro-task-types',
    './knowledge-practice-sync'],
}

function inspect(source, name) {
  const info = inspectSource(source, name)
  const tree = ts.createSourceFile(name, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS)
  const errors = [...info.errors]
  const imports = []
  function walk(node) {
    if (ts.isCallExpression(node) && ts.isIdentifier(node.expression) &&
        node.expression.text === 'require') {
      if (node.arguments.length !== 1 || !ts.isStringLiteral(node.arguments[0])) {
        errors.push(`${name}: require must take a single string literal`)
      } else {
        const request = node.arguments[0].text
        if (!/^\.\/[^/]+$/.test(request)) {
          errors.push(`${name}: require must stay in the same directory, found ${request}`)
        }
        imports.push(request)
      }
    }
    if (ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword) {
      errors.push(`${name}: dynamic import is not allowed`)
    }
    ts.forEachChild(node, walk)
  }
  walk(tree)
  return { errors, imports, lines: info.lines, functions: info.functions }
}

function graphErrors(graph) {
  const errors = []
  function visit(name, parents = []) {
    if (parents.includes(name)) {
      errors.push(`cyclic local dependency at ${name}`)
      return
    }
    for (const request of graph[name] || []) {
      const next = request.slice(2) + '.js'
      if (!(next in graph)) errors.push(`${name} imports undeclared ${next}`)
      else visit(next, [...parents, name])
    }
  }
  Object.keys(graph).forEach(name => visit(name))
  return errors
}

test('client storage modules keep their budgets and declared dependency graph', () => {
  const graph = {}
  let functions = 0
  for (const name of Object.keys(MODULES)) {
    const info = inspect(fs.readFileSync(path.join(UTILS, name), 'utf8'), name)
    assert.deepEqual(info.errors, [], name)
    assert.deepEqual(info.imports, MODULES[name], name)
    if (AGGREGATORS.includes(name)) {
      assert.ok(info.imports.length > 0, `${name} must aggregate modules`)
    } else {
      assert.ok(info.functions.length > 0, `${name} must declare functions`)
    }
    functions += info.functions.length
    graph[name] = info.imports
  }
  assert.ok(functions > 40, 'module scan must not be empty or partial')
  assert.deepEqual(graphErrors(graph), [])
})

test('only the facade may aggregate domains and nothing reaches back into it', () => {
  for (const [name, imports] of Object.entries(MODULES)) {
    if (name !== FACADE) {
      assert.ok(!imports.includes('./storage'), `${name} must not require the facade`)
      assert.ok(!imports.includes('./study-strategy'), `${name} must not aggregate the strategy domain`)
      assert.ok(!imports.includes('./pomodoro-task-types'), `${name} must not aggregate task typing`)
      assert.ok(!imports.includes('./knowledge-practice-sync'), `${name} must not aggregate receipts`)
    }
  }
  const facade = inspect(fs.readFileSync(path.join(UTILS, FACADE), 'utf8'), FACADE)
  assert.deepEqual(facade.errors, [])
  assert.deepEqual(facade.imports, MODULES[FACADE])
})

test('facade re-exports the same objects the submodules own', () => {
  const storage = require('../utils/storage')
  const core = require('../utils/storage-core')
  const strategy = require('../utils/study-strategy')
  const taskTypes = require('../utils/pomodoro-task-types')
  const receipts = require('../utils/knowledge-practice-sync')
  assert.equal(storage.KEYS, core.KEYS)
  assert.equal(storage.BUSINESS_CACHE_KEYS, core.BUSINESS_CACHE_KEYS)
  assert.equal(storage.PROTECTED_KEYS, core.PROTECTED_KEYS)
  assert.equal(storage.SESSION_DYNAMIC_KEY_PREFIXES, core.SESSION_DYNAMIC_KEY_PREFIXES)
  for (const name of ['get', 'set', 'setStrict', 'remove', 'clearSession']) {
    assert.equal(storage[name], core[name], name)
  }
  assert.equal(storage.studyStrategy, strategy.studyStrategy)
  assert.equal(storage.pomodoroTaskTypes, taskTypes.pomodoroTaskTypes)
  assert.equal(storage.knowledgePracticeSync, receipts.knowledgePracticeSync)
  assert.deepEqual(Object.keys(strategy), ['studyStrategy'])
  assert.deepEqual(Object.keys(taskTypes), ['pomodoroTaskTypes'])
  assert.deepEqual(Object.keys(receipts), ['knowledgePracticeSync'])
})

for (const [label, source] of [
  ['module length', 'void 0\n'.repeat(301)],
  ['nested function', 'function outer() {\nfunction inner() {\n' + 'void 0\n'.repeat(49) + '}\n}'],
  ['arrow function', 'const build = () => {\n' + 'void 0\n'.repeat(49) + '}'],
  ['parent directory import', "require('../storage-core')"],
  ['subpackage import', "require('../../pages/home/home')"],
  ['third party import', "require('acorn')"],
  ['dynamic require', 'require(name)'],
  ['dynamic import', "import('./storage-core')"],
  ['TypeScript', 'const value: string = "invalid"'],
]) {
  test(`client storage gate rejects ${label}`, () => {
    const info = inspect(source, 'fixture.js')
    assert.ok(info.errors.length > 0, `${label} must be rejected`)
  })
}

test('client storage gate rejects an undeclared or cyclic dependency', () => {
  const stray = inspect("require('./knowledge-practice-sync')\nmodule.exports = {}", 'storage-core.js')
  assert.deepEqual(stray.imports, ['./knowledge-practice-sync'])
  assert.notDeepEqual(stray.imports, MODULES['storage-core.js'])
  const cyclic = { 'storage.js': ['./storage-core'], 'storage-core.js': ['./storage'] }
  assert.ok(graphErrors(cyclic).length > 0)
  const undeclared = { 'storage.js': ['./storage-core', './missing-module'] }
  assert.ok(graphErrors(undeclared).some(error => error.includes('undeclared')))
})

test('client storage inspection never executes module statements', () => {
  const info = inspect("require('./storage-core')\nthrow Error('not executed')", 'fixture.js')
  assert.deepEqual(info.errors, [])
  assert.deepEqual(info.imports, ['./storage-core'])
})
