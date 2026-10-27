const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { createRequire } = require('node:module')
const { test } = require('node:test')
const { inspectSource } = require('../scripts/architecture/learning-controller-budgets')

const MINI = path.resolve(__dirname, '..')
const ts = createRequire(path.resolve(MINI, '../admin-frontend/package.json'))('typescript')
const NAMES = [
  'quiz-runner.js', 'question-sync.js', 'question-render-patch.js',
  'question-answer-patch.js', 'question-view-commit.js', 'navigation-methods.js',
]

function inspect(source, name) {
  const info = inspectSource(source, name)
  assert.deepEqual(info.errors, [])
  const tree = ts.createSourceFile(name, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS)
  const imports = []
  function walk(node) {
    if (ts.isCallExpression(node) && ts.isIdentifier(node.expression) &&
        node.expression.text === 'require') {
      assert.equal(node.arguments.length, 1)
      assert.ok(ts.isStringLiteral(node.arguments[0]), 'dynamic require')
      const request = node.arguments[0].text
      assert.ok(NAMES.some(file => request === './' + file.slice(0, -3)) ||
        request === '../../utils/code-block-render' ||
        request === '../../utils/question-runner-adapter', 'package escape')
      imports.push(request)
    }
    if (ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword) {
      assert.fail('dynamic import')
    }
    ts.forEachChild(node, walk)
  }
  walk(tree)
  return { ...info, imports }
}

for (const pkg of ['study', 'exam']) {
  test(`${pkg}: component and all local helpers obey 300/50 and package boundaries`, () => {
    const directory = path.join(MINI, `subpackages/${pkg}/components/quiz-runner`)
    const names = fs.readdirSync(directory).filter(name => name.endsWith('.js')).sort()
    assert.deepEqual(names, [...NAMES].sort())
    const modules = names.map(name => inspect(fs.readFileSync(path.join(directory, name), 'utf8'), name))
    assert.ok(modules.reduce((n, info) => n + info.functions.length, 0) > 30)
    function visit(name, ancestors = []) {
      assert.ok(!ancestors.includes(name), 'cyclic local dependency')
      const info = modules.find(module => module.path === name)
      for (const request of info.imports.filter(request => request.startsWith('./'))) {
        visit(request.slice(2) + '.js', [...ancestors, name])
      }
    }
    names.forEach(name => visit(name))
  })
}

test('six component sources stay synchronized without cross-package runtime imports', () => {
  for (const name of NAMES) {
    const read = pkg => fs.readFileSync(path.join(MINI,
      `subpackages/${pkg}/components/quiz-runner`, name), 'utf8')
    assert.equal(read('study'), read('exam'), name)
  }
})

for (const [name, source] of [
  ['module', 'void 0\n'.repeat(301)],
  ['nested function', 'function outer() {\nfunction inner() {\n' + 'void 0\n'.repeat(49) + '}\n}'],
  ['arrow', 'const project = () => {\n' + 'void 0\n'.repeat(49) + '}'],
  ['getter', 'const view = { get text() {\n' + 'void 0\n'.repeat(49) + '} }'],
  ['other package', "require('../../../exam/utils/answer')"],
  ['absolute path', "require('/subpackages/study/utils/answer')"],
  ['dynamic require', 'require(source)'],
  ['dynamic import', "import('./question-sync')"],
  ['invalid JavaScript', 'const value: string = "text"'],
]) {
  test(`gate rejects ${name}`, () => assert.throws(() => inspect(source, 'fixture.js')))
}

test('source inspection never executes a dependency or top-level business statement', () => {
  assert.equal(inspect("require('./question-sync')\nthrow Error('not executed')", 'fixture.js')
    .imports[0], './question-sync')
})
