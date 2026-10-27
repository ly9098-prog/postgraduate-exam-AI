const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { createRequire } = require('node:module')
const { test } = require('node:test')
const { inspectSource } = require('../scripts/architecture/learning-controller-budgets')

const MINI = path.resolve(__dirname, '..')
const ts = createRequire(path.resolve(MINI, '../admin-frontend/package.json'))('typescript')
const DEPENDENCIES = {
  'question-runner-adapter': ['question-adapter-options', 'question-adapter-groups',
    'question-adapter-answers', 'question-adapter-views', 'question-adapter-images'],
  'question-adapter-dependencies': ['stem-render', 'answer'],
  'question-adapter-options': ['question-adapter-dependencies'],
  'question-adapter-groups': ['question-adapter-dependencies', 'question-adapter-options'],
  'question-adapter-answers': ['question-adapter-dependencies', 'question-adapter-groups'],
  'question-adapter-views': ['question-adapter-dependencies', 'question-adapter-options',
    'question-adapter-groups', 'question-adapter-answers'],
  'question-adapter-images': ['question-adapter-dependencies'],
}

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
      assert.ok(request.startsWith('./') && !request.slice(2).includes('/'), 'package escape')
      const dependency = request.slice(2)
      assert.ok(dependency in DEPENDENCIES || ['stem-render', 'answer'].includes(dependency),
        'unexpected dependency')
      imports.push(dependency)
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
  test(`${pkg}: all adapter modules obey 300/50 and their explicit acyclic dependency graph`, () => {
    const directory = path.join(MINI, `subpackages/${pkg}/utils`)
    const files = fs.readdirSync(directory).filter(name =>
      name === 'question-runner-adapter.js' || /^question-adapter-.*\.js$/.test(name))
    assert.deepEqual(files.sort(), Object.keys(DEPENDENCIES).map(name => name + '.js').sort())
    const graph = {}
    let count = 0
    for (const name of Object.keys(DEPENDENCIES)) {
      const info = inspect(fs.readFileSync(path.join(directory, name + '.js'), 'utf8'), name)
      assert.deepEqual(info.imports, DEPENDENCIES[name], name)
      count += info.functions.length
      graph[name] = info.imports
    }
    assert.ok(count > 60, 'module scan must not be empty or partial')
    function visit(name, parents = []) {
      assert.ok(!parents.includes(name), 'cyclic local dependency')
      for (const next of graph[name].filter(next => next in graph)) {
        visit(next, [...parents, name])
      }
    }
    Object.keys(graph).forEach(name => visit(name))
  })
}

test('study and exam adapter sources stay synchronized without cross-package imports', () => {
  for (const name of Object.keys(DEPENDENCIES)) {
    const source = pkg => fs.readFileSync(path.join(MINI, `subpackages/${pkg}/utils/${name}.js`), 'utf8')
    assert.equal(source('study'), source('exam'), name)
  }
})

for (const [name, source] of [
  ['module length', 'void 0\n'.repeat(301)],
  ['nested function', 'function outer() {\nfunction inner() {\n' + 'void 0\n'.repeat(49) + '}\n}'],
  ['arrow function', 'const build = () => {\n' + 'void 0\n'.repeat(49) + '}'],
  ['getter', 'const value = { get text() {\n' + 'void 0\n'.repeat(49) + '} }'],
  ['subpackage import', "require('../../study/utils/answer')"],
  ['absolute import', "require('/subpackages/exam/utils/answer')"],
  ['unknown local import', "require('./unknown-helper')"],
  ['dynamic require', 'require(source)'],
  ['dynamic import', "import('./question-adapter-options')"],
  ['TypeScript', 'const value: string = "invalid"'],
]) {
  test(`adapter gate rejects ${name}`, () => assert.throws(() => inspect(source, 'fixture.js')))
}

test('adapter source inspection never executes imports or business statements', () => {
  assert.deepEqual(inspect("require('./question-adapter-options')\nthrow Error('not executed')",
    'fixture.js').imports, ['question-adapter-options'])
})
