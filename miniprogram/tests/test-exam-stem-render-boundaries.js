const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { createRequire } = require('node:module')
const { Script } = require('node:vm')
const { test } = require('node:test')
const { assertRenderParity } = require('./exam-stem-render-support')

const ts = createRequire(path.resolve(__dirname, '../../admin-frontend/package.json'))('typescript')
const DEPENDENCIES = {
  'stem-render': ['stem-render-dependencies', 'stem-render-text', 'stem-render-options',
    'stem-render-segments', 'stem-render-blocks', 'stem-render-diagnostics', 'stem-render-model'],
  'stem-render-dependencies': ['../../../config', 'math-format', 'code-reconstructor',
    'table-structure', 'question-image-cache'],
  'stem-render-text': ['stem-render-dependencies'],
  'stem-render-options': ['stem-render-text'],
  'stem-render-segments': ['stem-render-dependencies', 'stem-render-text', 'stem-render-options',
    'segment-types'],
  'stem-render-blocks': ['stem-render-dependencies', 'stem-render-text'],
  'stem-render-diagnostics': ['stem-render-dependencies', 'stem-render-text'],
  'stem-render-model': ['stem-render-dependencies', 'stem-render-text', 'stem-render-options',
    'stem-render-segments', 'stem-render-blocks', 'stem-render-diagnostics'],
}

function localImports(source, name) {
  const tree = ts.createSourceFile(name, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS)
  const imports = []
  function walk(node) {
    if (ts.isCallExpression(node) && ts.isIdentifier(node.expression) &&
        node.expression.text === 'require') {
      assert.ok(ts.isStringLiteral(node.arguments[0]))
      imports.push(node.arguments[0].text.replace(/^\.\//, ''))
    }
    ts.forEachChild(node, walk)
  }
  walk(tree)
  return imports
}

function inspect(source) {
  const lines = source.split('\n').length - (source.endsWith('\n') ? 1 : 0)
  assert.ok(lines <= 300, 'module exceeds 300 lines')
  new Script(source, { filename: 'stem-render-boundary.js' })
  const tree = ts.createSourceFile('stem-render-boundary.js',
    source, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS)
  assert.equal(tree.parseDiagnostics.length, 0, 'invalid JavaScript')
  let functions = 0
  function walk(node) {
    if (ts.isFunctionLike(node) && node.body) {
      functions++
      const start = tree.getLineAndCharacterOfPosition(node.getStart(tree)).line
      const end = tree.getLineAndCharacterOfPosition(node.end).line
      assert.ok(end - start + 1 <= 50, 'function exceeds 50 lines')
    }
    if (ts.isCallExpression(node) && ts.isIdentifier(node.expression) &&
        node.expression.text === 'require') {
      assert.equal(node.arguments.length, 1)
      assert.ok(ts.isStringLiteral(node.arguments[0]), 'require must have a static path')
      const request = node.arguments[0].text
      assert.ok(request.startsWith('./') || request === '../../../config', 'subpackage escape')
      assert.ok(request === '../../../config' || !request.slice(2).includes('../'), 'subpackage escape')
    }
    if (ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword) {
      assert.fail('dynamic package import')
    }
    ts.forEachChild(node, walk)
  }
  walk(tree)
  return functions
}

for (const pkg of ['study', 'exam']) {
  test(`all ${pkg} stem-render modules obey 300/50 and local package dependencies`, () => {
    const directory = path.resolve(__dirname, `../subpackages/${pkg}/utils`)
    const files = fs.readdirSync(directory).filter(name => /^stem-render(?:-.*)?\.js$/.test(name))
    assert.ok(files.includes('stem-render.js'))
    assert.ok(files.includes('stem-render-model.js'))
    const count = files.reduce((sum, name) =>
      sum + inspect(fs.readFileSync(path.join(directory, name), 'utf8')), 0)
    assert.ok(count > 50, 'the module scan must not be empty')
  })

  test(`${pkg} renderer has the explicit dependency graph and no local cycle`, () => {
    const directory = path.resolve(__dirname, `../subpackages/${pkg}/utils`)
    const files = fs.readdirSync(directory).filter(name => /^stem-render(?:-.*)?\.js$/.test(name))
    assert.deepEqual(files.sort(), Object.keys(DEPENDENCIES).map(name => name + '.js').sort())
    const graph = {}
    for (const name of Object.keys(DEPENDENCIES)) {
      const source = fs.readFileSync(path.join(directory, name + '.js'), 'utf8')
      graph[name] = localImports(source, name)
      assert.deepEqual(graph[name], DEPENDENCIES[name], name)
    }
    function visit(name, parents = []) {
      assert.ok(!parents.includes(name), 'cyclic renderer dependency')
      for (const dependency of graph[name].filter(name => name in graph)) {
        visit(dependency, [...parents, name])
      }
    }
    Object.keys(graph).forEach(name => visit(name))
  })
}

for (const [name, source] of [
  ['module', 'void 0\n'.repeat(301)],
  ['nested function', 'function outer() {\nfunction inner() {\n' + 'void 0\n'.repeat(49) + '}\n}'],
  ['arrow', 'const render = () => {\n' + 'void 0\n'.repeat(49) + '}'],
  ['getter', 'const value = { get text() {\n' + 'void 0\n'.repeat(49) + '} }'],
  ['study import', "require('../../study/utils/stem-render')"],
  ['absolute import', "require('/subpackages/study/utils/stem-render')"],
  ['dynamic require', 'require(source)'],
  ['dynamic import', "import('./stem-render')"],
  ['class method', 'class Render { build() {\n' + 'void 0\n'.repeat(49) + '} }'],
  ['typed variable', 'const value: string = "text"'],
  ['typed parameter', 'function render(value: string) { return value }'],
  ['interface', 'interface Render { value: string }'],
  ['type assertion', 'const value = input as string'],
  ['invalid syntax', 'const value = (1 + 2'],
]) {
  test(`budget/package gate rejects injected ${name}`, () => {
    assert.throws(() => inspect(source))
  })
}

test('JavaScript compilation checks syntax without executing source', () => {
  assert.equal(inspect("require('./missing-fixture')\nthrow new Error('not executed')"), 0)
})

test('study/exam export and rendering parity replaces source duplication', () => {
  assertRenderParity(require('../subpackages/study/utils/stem-render'),
    require('../subpackages/exam/utils/stem-render'))
})

for (const mode of ['RICH_TEXT', 'LATEX', 'CODE', 'MIXED', 'SEGMENTS']) {
  test(`parity rejects changed ${mode} payloads`, () => {
    const original = require('../subpackages/study/utils/stem-render')
    const changed = { ...original, buildRenderModel: function (q, options, config) {
      const model = original.buildRenderModel(q, options, config)
      return model.mode === mode ? { ...model, html: 'mutated' } : model
    } }
    assert.throws(() => assertRenderParity(original, changed))
  })
}

test('parity rejects removed exports and changed public helper behavior', () => {
  const original = require('../subpackages/study/utils/stem-render')
  const removed = { ...original }
  delete removed.resolveAssetUrl
  assert.throws(() => assertRenderParity(original, removed))
  assert.throws(() => assertRenderParity(original,
    { ...original, computeCodeHash: function (value) { return 123 } }))
})

test('parity rejects corrupt nonempty asset URLs', () => {
  const original = require('../subpackages/study/utils/stem-render')
  const changed = { ...original, resolveAssetUrl: function _resolveAssetUrl(url) {
    return url ? 'BROKEN:' + url : original.resolveAssetUrl(url)
  } }
  assert.throws(() => assertRenderParity(original, changed), /resolveAssetUrl/)
})

test('parity rejects changed option segment asset URLs', () => {
  const original = require('../subpackages/study/utils/stem-render')
  const changed = { ...original, buildOptionList: function buildOptionList(opts, keys, flags) {
    const result = original.buildOptionList(opts, keys, flags)
    for (const item of result) {
      for (const segment of item._segments || []) {
        if (segment.url) segment.url = 'BROKEN:' + segment.url
      }
    }
    return result
  } }
  assert.throws(() => assertRenderParity(original, changed), /buildOptionList/)
})

for (const method of ['resetRenderGuard', 'setRenderGuardPage']) {
  test(`parity rejects a ${method} no-op that preserves name and arity`, () => {
    const original = require('../subpackages/study/utils/stem-render')
    const replacement = method === 'resetRenderGuard'
      ? function resetRenderGuard() {}
      : function setRenderGuardPage(page) {}
    assert.throws(() => assertRenderParity(original,
      { ...original, [method]: replacement }), /render guard state parity/)
  })
}
