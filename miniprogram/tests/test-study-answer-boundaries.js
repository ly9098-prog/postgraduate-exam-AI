/**
 * Study answer normalization boundaries.
 *
 * The study copy of `subpackages/study/utils/answer.js` is consumed by practice,
 * review-today, wrong-detail and the study question-runner adapter. This gate keeps
 * its 300/50 budgets, its dispatch shape and its behavioral parity with the reviewed
 * exam copy that carries the same grading semantics.
 *
 * Run: node --test tests/test-study-answer-boundaries.js
 */

const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { createRequire } = require('node:module')
const { isDeepStrictEqual } = require('node:util')
const { test } = require('node:test')
const { inspectSource } = require('../scripts/architecture/learning-controller-budgets')

const MINI = path.resolve(__dirname, '..')
const ts = createRequire(path.resolve(MINI, '../admin-frontend/package.json'))('typescript')
const STUDY = 'subpackages/study/utils/answer.js'
const EXAM = 'subpackages/exam/utils/answer.js'
const EXPORT_KEYS = [
  'normalizeChoiceAnswer', 'serializeChoiceAnswer', 'normalizeAnswerSet',
  'isMultipleChoiceType', 'isTrueFalseType', 'isMultiBlankType',
  'isMultiBlankMultipleType', 'normalizeTrueFalseAnswer', 'normalizeBlankAnswer',
  'serializeBlankAnswer', 'isAnswerCorrect',
]
const DISPATCH = [
  ['parseCanonicalBlankAnswer', 2], ['parseMarkedBlankAnswer', 2],
  ['parsePositionalBlankAnswer', 3],
]
const DISPATCH_SHAPE = ['if:parseCanonicalBlankAnswer', 'if:parseMarkedBlankAnswer',
  'return:parsePositionalBlankAnswer']

function read(relativePath) {
  return fs.readFileSync(path.join(MINI, relativePath), 'utf8')
}

function statementText(node, file) {
  return node.getText(file).replace(/\s+/g, ' ').trim()
}

function inspect(source, name = 'fixture.js') {
  const info = inspectSource(source, name)
  const tree = ts.createSourceFile(name, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS)
  const errors = [...info.errors]
  const declarations = []
  let dispatch = null
  let exportKeys = null
  for (const statement of tree.statements) {
    if (ts.isFunctionDeclaration(statement) && statement.name) {
      declarations.push({ name: statement.name.getText(tree), arity: statement.parameters.length })
      if (statement.name.getText(tree) === 'normalizeBlankAnswer') {
        dispatch = []
        for (const inner of statement.body.statements) {
          if (ts.isIfStatement(inner) && ts.isCallExpression(inner.expression) &&
              ts.isIdentifier(inner.expression.expression) &&
              ts.isReturnStatement(inner.thenStatement)) {
            dispatch.push(`if:${inner.expression.expression.text}`)
          }
          if (ts.isReturnStatement(inner) && inner.expression &&
              ts.isCallExpression(inner.expression) &&
              ts.isIdentifier(inner.expression.expression)) {
            dispatch.push(`return:${inner.expression.expression.text}`)
          }
        }
      }
    }
    if (ts.isExpressionStatement(statement) &&
        ts.isBinaryExpression(statement.expression) &&
        statement.expression.operatorToken.kind === ts.SyntaxKind.EqualsToken &&
        statementText(statement.expression.left, tree) === 'module.exports' &&
        ts.isObjectLiteralExpression(statement.expression.right)) {
      exportKeys = statement.expression.right.properties.map(property =>
        property.name.getText(tree))
    }
  }
  const declared = new Map(declarations.map(entry => [entry.name, entry.arity]))
  if (!dispatch) errors.push(`${name}: normalizeBlankAnswer is missing`)
  else if (!isDeepStrictEqual(dispatch, DISPATCH_SHAPE)) {
    errors.push(`${name}: normalizeBlankAnswer must dispatch ${DISPATCH_SHAPE.join(' -> ')}`)
  }
  for (const [parser, arity] of DISPATCH) {
    if (declared.get(parser) !== arity) {
      errors.push(`${name}: ${parser} must be declared with ${arity} parameters`)
    }
  }
  if (!isDeepStrictEqual(exportKeys, EXPORT_KEYS)) {
    errors.push(`${name}: module.exports keys must keep their names and order`)
  }
  const normalize = info.functions.filter(entry => entry.start > 0)
  if (!normalize.length) errors.push(`${name}: no functions inspected`)
  return { errors, declarations, lines: info.lines, functions: info.functions }
}

const CORPUS = [
  undefined, null, false, 0, '', ' ', 'A', 'a', 'ABCD', 'CBAC', 'A,B', 'A;B', '1:A',
  '1:A;2:B', '1:C,A;1:B;2:d', '①＝B;②:C', '①：b，c；②=Ⅶ', 'x:A\nB;y:C', '①B;x:C',
  '①B、(1)D', '(1)B、第2空D', '①B、①D', '①A,C、②Ⅶ', '（1）b、(2)D', '第一空B，第2空D',
  '①AC、②VII', 'b,d', 'BAD', 'IX', 'unrecognized', 'x:', '__proto__:A;constructor:B',
  '1:A；2:B；3:C', '①A②B', { '1': 'A' }, [], new String('1:A'), 'yes', '对', '错误',
]
const SLOTS = [undefined, [], ['1'], ['1', '2'], ['x', 'y'], [' x ', 'y'], ['x', 'x'], ['1', '2', '3']]
const TYPES = [undefined, '', 'single_choice', 'multiple_choice', 'true_false', 'judgement',
  'multi_blank_choice', 'multi_blank_multiple_choice']

function outcome(module, name, args) {
  try {
    return { value: module[name](...args) }
  } catch (error) {
    return { error: `${error && error.constructor && error.constructor.name}:${error && error.message}` }
  }
}

function parityMismatches(study, exam, corpus) {
  const mismatches = []
  const calls = {
    normalizeChoiceAnswer: [], serializeChoiceAnswer: [], normalizeAnswerSet: [],
    isMultipleChoiceType: [], isTrueFalseType: [], isMultiBlankType: [],
    isMultiBlankMultipleType: [], normalizeTrueFalseAnswer: [], normalizeBlankAnswer: [],
    serializeBlankAnswer: [], isAnswerCorrect: [],
  }
  const compare = (name, args) => {
    calls[name].push(args)
    const left = outcome(study, name, args)
    const right = outcome(exam, name, args)
    if (!isDeepStrictEqual(left, right) && mismatches.length < 10) {
      mismatches.push(`${name}(${JSON.stringify(args)}) ${JSON.stringify(left)} != ${JSON.stringify(right)}`)
    }
  }
  for (const value of corpus) {
    compare('normalizeChoiceAnswer', [value])
    compare('serializeChoiceAnswer', [value])
    compare('normalizeAnswerSet', [value])
    compare('normalizeTrueFalseAnswer', [value])
    for (const slots of SLOTS) compare('normalizeBlankAnswer', [value, slots])
    for (const type of TYPES) {
      compare('isMultipleChoiceType', [type])
      compare('isTrueFalseType', [type])
      compare('isMultiBlankType', [type])
      compare('isMultiBlankMultipleType', [type])
      for (const correct of ['A', '1:A', '1:A,C', 'yes', '①B']) {
        compare('isAnswerCorrect', [value, correct, type])
      }
    }
  }
  for (const groups of [[{ id: 'y' }, { id: 'x' }], [], [{ id: '' }], [{ id: 'x' }, { id: 'x' }]]) {
    for (const blanks of [{ x: 'c,a', y: 'b' }, {}, { x: '' }, { y: 'B,C,D' }]) {
      compare('serializeBlankAnswer', [groups, blanks])
    }
  }
  return { mismatches, calls }
}

function load(relativePath) {
  return require(path.join(MINI, relativePath))
}

test('study answer module keeps 300/50 budgets, dispatch shape and export order', () => {
  const result = inspect(read(STUDY), STUDY)
  assert.deepEqual(result.errors, [])
  assert.ok(result.lines <= 300, `module has ${result.lines} lines`)
})

test('study and exam answer sources stay synchronized', () => {
  assert.equal(read(STUDY), read(EXAM))
})

test('study and exam answer behavior stays in parity over the grading corpus', () => {
  const { mismatches, calls } = parityMismatches(load(STUDY), load(EXAM), CORPUS)
  assert.deepEqual(mismatches, [])
  for (const [name, invocations] of Object.entries(calls)) {
    assert.ok(invocations.length > 0, `corpus must exercise ${name}`)
  }
})

test('parity corpus rejects a divergent study normalizer', () => {
  const study = { ...load(STUDY), normalizeBlankAnswer: () => ({ x: 'A' }) }
  const { mismatches } = parityMismatches(study, load(EXAM), ['1:A'])
  assert.ok(mismatches.length > 0)
})

const source = read(STUDY)
const mutations = {
  'reordered dispatch': source.replace(
    'if (parseCanonicalBlankAnswer(text, result)) return result\n' +
    'if (parseMarkedBlankAnswer(text, result)) return result',
    'if (parseMarkedBlankAnswer(text, result)) return result\n' +
    'if (parseCanonicalBlankAnswer(text, result)) return result'),
  'inlined canonical parser': source.replace(
    'function parseCanonicalBlankAnswer(text, result) {', 'function inlinedCanonicalParser(text, result) {'),
  'removed positional parser': source.replace(
    'function parsePositionalBlankAnswer(text, slotIds, result) {', 'function parsePositionalBlank(text, slotIds, result) {'),
  'added parser arity': source.replace(
    'function parseMarkedBlankAnswer(text, result) {', 'function parseMarkedBlankAnswer(text, result, extra) {'),
  'dropped dispatch return': source.replace(
    'if (parseCanonicalBlankAnswer(text, result)) return result',
    'parseCanonicalBlankAnswer(text, result)'),
  'extra dispatch call': source.replace(
    'return parsePositionalBlankAnswer(text, slotIds, result)',
    'if (parsePositionalBlankAnswer(text, slotIds, result)) return result\n' +
    'return parsePositionalBlankAnswer(text, slotIds, result)'),
  'dropped export entry': source.replace('isAnswerCorrect: isAnswerCorrect,\n', ''),
  'over budget function': source.replace(
    'function parsePositionalBlankAnswer(text, slotIds, result) {',
    `function parsePositionalBlankAnswer(text, slotIds, result) {\n${'void 0\n'.repeat(60)}`),
}

test('answer gate rejects each mutated source shape', () => {
  for (const [label, mutated] of Object.entries(mutations)) {
    assert.notEqual(mutated, source, `${label}: mutation must change the source`)
    assert.ok(inspect(mutated).errors.length > 0, `${label} must be rejected`)
  }
})
