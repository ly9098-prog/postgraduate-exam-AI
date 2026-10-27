const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { spawnSync } = require('node:child_process')
const { test } = require('node:test')

const {
  DIRECTORIES, MODULE_DIRECTORIES, PAGE_ENTRIES, FUNCTION_BUDGET, MODULE_BUDGET,
  inspectSource, scanControllers, scanModules,
} = require('../scripts/architecture/learning-controller-budgets')

function fixtureRoot(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'learning-controller-budgets-'))
  t.after(() => fs.rmSync(root, { recursive: true, force: true }))
  return root
}

function writeFixture(root, relativePath, source) {
  const filename = path.join(root, relativePath)
  fs.mkdirSync(path.dirname(filename), { recursive: true })
  fs.writeFileSync(filename, source)
}

function populatedRoot(t) {
  const root = fixtureRoot(t)
  for (const directory of DIRECTORIES) {
    writeFixture(root, `${directory}/fixture-controller.js`, 'function run() {}\n')
  }
  return root
}

test('all seven controller directories stay within the fixed function and module budgets', () => {
  assert.equal(DIRECTORIES.length, 7)
  assert.equal(FUNCTION_BUDGET, 50)
  assert.equal(MODULE_BUDGET, 300)
  const result = scanControllers()
  assert.deepEqual(result.errors, [])
  assert.equal(result.directories.length, 7)
  assert.ok(result.directories.every(directory => directory.controllers > 0))
  assert.equal(result.modules.length,
    result.directories.reduce((sum, directory) => sum + directory.controllers, 0))
  assert.ok(result.modules.every(module => module.lines <= 300))
  assert.ok(result.modules.flatMap(module => module.functions).every(fn => fn.lines <= 50))
})

test('missing directories fail instead of silently reducing coverage', t => {
  const result = scanControllers(fixtureRoot(t))
  assert.equal(result.errors.length, DIRECTORIES.length)
  assert.ok(result.errors.every(error => error.includes('required controller directory')))
})

test('a configured path must be a directory', t => {
  const root = fixtureRoot(t)
  writeFixture(root, DIRECTORIES[0], 'not a directory')
  const result = scanControllers(root)
  assert.ok(result.errors.some(error => error.startsWith(`${DIRECTORIES[0]}:`) &&
    error.includes('not a directory')))
})

test('each directory must contain controllers, not just unrelated files', t => {
  const root = fixtureRoot(t)
  for (const directory of DIRECTORIES) writeFixture(root, `${directory}/helper.js`, 'void 0')
  const result = scanControllers(root)
  assert.equal(result.errors.length, DIRECTORIES.length)
  assert.ok(result.errors.every(error => error.includes('controller directory is empty')))
})

test('discovery includes newly added controllers recursively in every governed directory', t => {
  const root = populatedRoot(t)
  assert.equal(scanControllers(root).modules.length, 7)
  for (const directory of DIRECTORIES) {
    writeFixture(root, `${directory}/nested/new-controller.js`, 'const run = () => 1\n')
    writeFixture(root, `${directory}/nested/helper.js`, 'void 0\n'.repeat(301))
  }
  const result = scanControllers(root)
  assert.deepEqual(result.errors, [])
  assert.equal(result.modules.length, 14)
  assert.ok(result.directories.every(directory => directory.controllers === 2))
})

const longBody = Array(49).fill('void 0').join('\n')
const mutations = [
  ['nested', `function outer() {\nfunction inner() {\n${longBody}\n}\n}`],
  ['method', `const owner = {\nasync run() {\n${longBody}\n}\n}`],
  ['arrow', `const run = () => {\n${longBody}\n}`],
  ['class method', `class Owner {\nrun() {\n${longBody}\n}\n}`],
  ['getter', `const owner = {\nget value() {\n${longBody}\nreturn 1\n}\n}`],
  ['function expression', `const run = function () {\n${longBody}\n}`],
]

for (const [kind, source] of mutations) {
  test(`new ${kind} function exceeding 50 lines is rejected through filesystem discovery`, t => {
    const root = populatedRoot(t)
    const filename = `${DIRECTORIES[0]}/nested/new-controller.js`
    writeFixture(root, filename, source)
    const result = scanControllers(root)
    assert.ok(result.errors.some(error => error.startsWith(`${filename}:`) &&
      error.includes('function has') && error.includes('limit 50')))
    if (kind === 'nested') {
      const module = result.modules.find(item => item.path === filename)
      assert.deepEqual(module.functions.map(fn => fn.lines), [53, 51])
      assert.equal(module.errors.length, 2)
    }
  })
}

test('function bodies at exactly 50 lines and expression arrows are accepted', () => {
  const body = Array(48).fill('void 0').join('\n')
  const source = `function run() {\n${body}\n}\nconst value = () => 1`
  const result = inspectSource(source, 'fixture-controller.js')
  assert.deepEqual(result.errors, [])
  assert.deepEqual(result.functions.map(fn => fn.lines), [50, 1])
})

test('module boundary accepts 300 lines and rejects an added line without long functions', t => {
  const root = populatedRoot(t)
  const filename = `${DIRECTORIES[0]}/new-controller.js`
  writeFixture(root, filename, 'void 0\n'.repeat(300))
  assert.deepEqual(scanControllers(root).errors, [])
  writeFixture(root, filename, 'void 0\n'.repeat(301))
  assert.deepEqual(scanControllers(root).errors, [
    `${filename}: module has 301 lines, limit 300`,
  ])
})

test('invalid JavaScript cannot silently pass a budget scan', () => {
  assert.ok(inspectSource('function broken( {', 'fixture-controller.js').errors.length > 0)
})

const syntaxMutations = [
  ['typed variable', 'const x = 1', 'const x: number = 1'],
  ['typed parameter', 'function run(args) { return args }',
    'function run(args: string) { return args }'],
  ['interface', 'const Shape = {}', 'interface Shape { value: string }'],
  ['type assertion', 'const value = input', 'const value = input as string'],
  ['unclosed parentheses', 'const value = (1 + 2)', 'const value = (1 + 2'],
]

for (const [kind, valid, invalid] of syntaxMutations) {
  test(`JavaScript parser rejects ${kind} through filesystem discovery`, t => {
    const root = populatedRoot(t)
    const filename = `${DIRECTORIES[0]}/nested/syntax-controller.js`
    writeFixture(root, filename, valid)
    assert.deepEqual(scanControllers(root).errors, [])
    writeFixture(root, filename, invalid)
    assert.ok(scanControllers(root).errors.some(error =>
      error.startsWith(`${filename}: invalid JavaScript:`)))
  })
}

test('JavaScript syntax checking compiles without executing CommonJS source', () => {
  const source = "module.exports = require('missing-controller-budget-fixture')\n" +
    "throw new Error('controller source must not execute')\n"
  assert.deepEqual(inspectSource(source, 'fixture-controller.js').errors, [])
})

test('standalone command reports the actual discovered controller and function counts', () => {
  const script = path.resolve(__dirname, '../scripts/architecture/learning-controller-budgets.js')
  const result = spawnSync(process.execPath, [script], { cwd: os.tmpdir(), encoding: 'utf8' })
  const scan = scanControllers()
  const functions = scan.modules.reduce((sum, module) => sum + module.functions.length, 0)
  assert.equal(result.status, 0, result.stderr)
  assert.ok(result.stdout.includes(`${scan.modules.length} controllers, ${functions} functions`))
})

test('every governed module, not only controllers, stays within budgets', () => {
  const result = scanModules()
  assert.deepEqual(result.errors, [])
  assert.equal(MODULE_DIRECTORIES.length, 7)
  assert.equal(result.directories.length, MODULE_DIRECTORIES.length)
  const controllers = scanControllers()
  assert.ok(result.modules.length > controllers.modules.length)
  assert.ok(result.modules.every(module => module.lines <= MODULE_BUDGET))
  assert.ok(result.modules.flatMap(module => module.functions)
    .every(fn => fn.lines <= FUNCTION_BUDGET))
})

test('module scan covers non-controller helpers and excludes governed page entries', () => {
  const modules = scanModules().modules.map(module => module.path)
  for (const filename of [
    'subpackages/study/practice-result/utils/format-helpers.js',
    'subpackages/study/practice-result/utils/review-preview-format.js',
    'subpackages/study/practice-result/utils/review-analysis-view.js',
    'subpackages/exam/utils/answer.js',
    'pages/pomodoro/utils/timer-math.js',
  ]) assert.ok(modules.includes(filename), filename)
  assert.ok(PAGE_ENTRIES.every(entry => !modules.includes(entry)))
})

test('a missing governed module directory fails the module scan as well', t => {
  assert.equal(scanModules(fixtureRoot(t)).errors.length, MODULE_DIRECTORIES.length)
})

test('module scan rejects an over-budget helper but accepts the excluded page entry', t => {
  const root = populatedRoot(t)
  const helper = `${DIRECTORIES[0]}/helper-module.js`
  writeFixture(root, helper, 'void 0\n'.repeat(301))
  assert.ok(scanModules(root).errors.some(error =>
    error.startsWith(`${helper}:`) && error.includes('module has 301 lines')))
  const entry = PAGE_ENTRIES[0]
  writeFixture(root, entry, 'void 0\n'.repeat(400))
  assert.deepEqual(scanModules(root).errors.filter(error => error.startsWith(entry)), [])
})

test('standalone command reports the discovered module and function counts', () => {
  const script = path.resolve(__dirname, '../scripts/architecture/learning-controller-budgets.js')
  const result = spawnSync(process.execPath, [script], { cwd: os.tmpdir(), encoding: 'utf8' })
  const scan = scanModules()
  const functions = scan.modules.reduce((sum, module) => sum + module.functions.length, 0)
  assert.equal(result.status, 0, result.stderr)
  assert.ok(result.stdout.includes(`${scan.modules.length} modules, ${functions} functions`))
})
