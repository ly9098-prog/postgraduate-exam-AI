/**
 * Mini Program API client module boundaries.
 *
 * `utils/api.js` stays the single public HTTP entry. The modules behind it must
 * keep 300/50 budgets, an explicit acyclic dependency graph, no page/subpackage
 * or third-party imports, and no module may reach back into the facade.
 *
 * Run: node --test tests/test-api-client-boundaries.js
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
const FACADE = 'api.js'
const MODULES = {
  'api-error.js': [],
  'api-correlation.js': [],
  'api-transport.js': ['../config'],
  'api-clock.js': ['./china-time', './api-error'],
  'api-auth.js': ['./storage', './china-time', './api-correlation', './api-transport', './api-error'],
  'api-request.js': ['./api-error', './api-correlation', './api-transport', './api-clock',
    './api-auth', './debug'],
  'api-upload.js': ['./storage', './api-error', './api-correlation', './api-transport',
    './api-auth'],
  'api.js': ['./api-error', './api-auth', './api-correlation', './api-clock', './api-request',
    './api-upload'],
}
const AGGREGATORS = ['api.js']
const ALLOWED_SHARED = ['./storage', './china-time', './debug', '../config']

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
        const local = /^\.\/api-[a-z-]+$/.test(request) || request === './storage' ||
          request === './china-time' || request === './debug'
        if (!local && request !== '../config') {
          errors.push(`${name}: require must stay in the API client, found ${request}`)
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
      if (!request.startsWith('./api-')) continue
      const next = `${request.slice(2)}.js`
      if (!(next in graph)) errors.push(`${name} imports undeclared ${next}`)
      else visit(next, [...parents, name])
    }
  }
  Object.keys(graph).forEach(name => visit(name))
  return errors
}

test('api client modules keep their budgets and declared dependency graph', () => {
  const graph = {}
  for (const name of Object.keys(MODULES)) {
    const info = inspect(fs.readFileSync(path.join(UTILS, name), 'utf8'), name)
    assert.deepEqual(info.errors, [], name)
    assert.deepEqual(info.imports, MODULES[name], name)
    if (AGGREGATORS.includes(name)) {
      assert.ok(info.imports.length > 0, `${name} must aggregate modules`)
    } else {
      assert.ok(info.functions.length > 0, `${name} must declare functions`)
      assert.ok(info.lines <= 300, `${name} has ${info.lines} lines`)
    }
    graph[name] = info.imports
  }
  assert.deepEqual(graphErrors(graph), [])
})

test('only the facade composes the client and nothing reaches back into it', () => {
  for (const [name, imports] of Object.entries(MODULES)) {
    if (name === FACADE) continue
    assert.ok(!imports.includes('./api'), `${name} must not require the facade`)
  }
  for (const shared of MODULES['api.js']) {
    assert.ok(ALLOWED_SHARED.concat(Object.keys(MODULES).filter(key => key.startsWith('api-'))
      .map(key => `./${key.slice(0, -3)}`)).includes(shared) || shared.startsWith('./api-'), shared)
  }
})

test('facade re-exports the same functions the submodules own', () => {
  const api = require('../utils/api')
  const error = require('../utils/api-error')
  const auth = require('../utils/api-auth')
  const clock = require('../utils/api-clock')
  const request = require('../utils/api-request')
  const upload = require('../utils/api-upload')
  assert.equal(api.ApiError, error.ApiError)
  assert.equal(api.ensureValidToken, auth.ensureValidToken)
  assert.equal(api.forceRefreshToken, auth.forceRefreshToken)
  assert.equal(api.resetRedirecting, auth.resetRedirecting)
  assert.equal(api.normalizeExpiresAt, auth.normalizeExpiresAt)
  assert.equal(api.now, clock.now)
  assert.equal(api.request, request.request)
  assert.equal(api.uploadFile, upload.uploadFile)
  assert.deepEqual(Object.keys(error), ['ApiError', 'getResponseHeader', 'safeHttpMessage',
    'extractErrorCode', 'safeErrorMeta', 'summarizeResponseData', 'parseUploadResponseData'])
  assert.deepEqual(Object.keys(request), ['request'])
  assert.deepEqual(Object.keys(upload), ['uploadFile'])
})

for (const [label, source] of [
  ['module length', 'void 0\n'.repeat(301)],
  ['nested function', 'function outer() {\nfunction inner() {\n' + 'void 0\n'.repeat(49) + '}\n}'],
  ['page import', "require('../../pages/home/home')"],
  ['subpackage import', "require('../../../subpackages/study/practice/practice')"],
  ['third party import', "require('acorn')"],
  ['parent escape', "require('../../utils/storage')"],
  ['dynamic require', 'require(name)'],
  ['dynamic import', "import('./api-auth')"],
  ['TypeScript', 'const value: string = "invalid"'],
]) {
  test(`api client gate rejects ${label}`, () => {
    assert.ok(inspect(source, 'fixture.js').errors.length > 0, `${label} must be rejected`)
  })
}

test('api client gate rejects an undeclared or cyclic dependency', () => {
  const stray = inspect("require('./api-auth')\nmodule.exports = {}", 'api-error.js')
  assert.deepEqual(stray.imports, ['./api-auth'])
  assert.notDeepEqual(stray.imports, MODULES['api-error.js'])
  assert.ok(graphErrors({ 'api-request.js': ['./api-auth'], 'api-auth.js': ['./api-request'] }).length > 0)
  assert.ok(graphErrors({ 'api.js': ['./api-missing'] }).some(error => error.includes('undeclared')))
})

test('api client inspection never executes module statements', () => {
  const info = inspect("require('./api-auth')\nthrow Error('not executed')", 'fixture.js')
  assert.deepEqual(info.errors, [])
  assert.deepEqual(info.imports, ['./api-auth'])
})
